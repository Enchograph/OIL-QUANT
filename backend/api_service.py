from __future__ import annotations

import json
import logging
import os
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from flask import Flask, g, jsonify, request

from .admin_console import (
    AdminSessionStore,
    build_config_payload,
    build_logs_payload,
    build_overview_payload,
    build_program_payload,
    build_run_detail_payload,
    validate_admin_password,
)
from . import core_backend as backend_core
from .chat_service import ChatOrchestrator
from .logging_utils import configure_backend_logging
from .query_service import QueryService
from .runtime_store import RuntimeStore


REPO_ROOT = Path(__file__).resolve().parent.parent
HEAVY_WORKER_MODULES = {
    "backend.workers.factor_worker",
    "backend.workers.model_worker",
    "backend.workers.ai_analysis_worker",
}
WORKER_SINGLE_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
}
WORKER_NICE_LEVEL = max(0, int(os.getenv("WORKER_NICE_LEVEL", "10")))
HEAVY_WORKER_MEMORY_LIMIT_MB = max(256, int(os.getenv("HEAVY_WORKER_MEMORY_LIMIT_MB", "700")))
HEAVY_WORKER_CPU_CORE_INDEX = max(0, int(os.getenv("HEAVY_WORKER_CPU_CORE_INDEX", "1")))


def _apply_worker_priority() -> None:
    if WORKER_NICE_LEVEL > 0:
        os.nice(WORKER_NICE_LEVEL)
    memory_limit_bytes = HEAVY_WORKER_MEMORY_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    if hasattr(os, "sched_setaffinity"):
        available = sorted(os.sched_getaffinity(0))
        if available:
            target_core = available[min(HEAVY_WORKER_CPU_CORE_INDEX, len(available) - 1)]
            os.sched_setaffinity(0, {target_core})


def _resolve_allowed_origin() -> str:
    return os.getenv("BACKEND_ALLOWED_ORIGIN", "*").strip() or "*"


def _is_origin_allowed(origin: str, allowed_origin: str) -> bool:
    return allowed_origin == "*" or origin == allowed_origin


def _is_direct_local_request() -> bool:
    remote_addr = (request.remote_addr or "").strip()
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    return remote_addr in {"127.0.0.1", "::1"} and not forwarded_for

def _runtime_store() -> RuntimeStore:
    store = RuntimeStore(backend_core.DB_PATH, backend_core.iso_now)
    store.init()
    store.bootstrap_views_from_existing_data()
    return store


def _run_worker_module(module: str, args: list[str] | None = None) -> dict:
    command = [sys.executable, "-m", module]
    if args:
        command.extend(args)
    heavy_worker = module in HEAVY_WORKER_MODULES
    worker_env = os.environ.copy()
    if heavy_worker:
        worker_env.update(WORKER_SINGLE_THREAD_ENV)
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=worker_env,
        preexec_fn=_apply_worker_priority if heavy_worker else None,
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = result.stdout.strip().splitlines()
    if not stdout:
        return {"status": "success"}
    return json.loads(stdout[-1])


class ResponseCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}

    def get_or_set(self, key: str, ttl_seconds: int, loader: Callable[[], Any]) -> Any:
        now = time.time()
        with self._lock:
            cached = self._entries.get(key)
            if cached and cached[0] > now:
                return cached[1]
        payload = loader()
        with self._lock:
            self._entries[key] = (now + ttl_seconds, payload)
        return payload

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            stale_keys = [key for key in self._entries if key.startswith(prefix)]
            for key in stale_keys:
                self._entries.pop(key, None)


def create_app() -> Flask:
    configure_backend_logging()
    backend_core.ensure_dirs()
    database = backend_core.create_database()
    runtime_store = _runtime_store()
    queries = QueryService(runtime_store, database=database)
    chat = ChatOrchestrator(queries)
    admin_sessions = AdminSessionStore()
    response_cache = ResponseCache()
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    access_logger = logging.getLogger("api.access")
    error_logger = logging.getLogger("api.error")
    allowed_origin = _resolve_allowed_origin()

    @app.after_request
    def add_cors_headers(response):
        request_origin = request.headers.get("Origin", "").strip()
        if request_origin and _is_origin_allowed(request_origin, allowed_origin):
            response.headers["Access-Control-Allow-Origin"] = request_origin
            response.headers["Vary"] = "Origin"
        elif allowed_origin == "*":
            response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Key, X-Admin-Session"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.before_request
    def record_request_started_at():
        g.request_started_at = time.perf_counter()

    @app.after_request
    def log_request(response):
        started_at = getattr(g, "request_started_at", None)
        duration_ms = 0 if started_at is None else int((time.perf_counter() - started_at) * 1000)
        access_logger.info(
            '%s "%s %s" %s %sms',
            request.remote_addr or "-",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response

    def ensure_admin() -> None:
        if admin_sessions.verify(request.headers.get("X-Admin-Session", "").strip()):
            return
        admin_key = os.getenv("BACKEND_ADMIN_KEY", "").strip()
        if not admin_key:
            if not _is_direct_local_request():
                raise PermissionError("当前仅允许本机调用管理接口")
            return
        if request.headers.get("X-Admin-Key") != admin_key:
            raise PermissionError("管理密钥无效")

    def cached_json(cache_key: str, ttl_seconds: int, loader: Callable[[], Any]) -> Any:
        return response_cache.get_or_set(cache_key, ttl_seconds, loader)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "service": "oilquant-api", "time": backend_core.iso_now()})

    @app.get("/api/v1/market/ticker")
    def market_ticker():
        return jsonify(cached_json("market:ticker", 15, queries.get_market_ticker))

    @app.get("/api/v1/market/chart")
    def market_chart():
        symbol = request.args.get("symbol", "WTI_Close")
        range_key = request.args.get("range", "1M")
        chart_kind = request.args.get("kind", "main")
        width_arg = request.args.get("width")
        viewport_width = None
        if width_arg not in {None, ""}:
            viewport_width = max(1, int(width_arg))
        target_points = backend_core.resolve_main_chart_target_points(viewport_width) if chart_kind == "main" else "default"
        return jsonify(
            cached_json(
                f"market:chart:{symbol}:{range_key}:{chart_kind}:{target_points}",
                15,
                lambda: queries.get_market_chart(symbol, range_key, chart_kind=chart_kind, viewport_width=viewport_width),
            )
        )

    @app.get("/api/v1/market/charts/batch")
    def market_charts_batch():
        symbols = [item.strip() for item in request.args.get("symbols", "").split(",") if item.strip()]
        range_key = request.args.get("range", "1M")
        chart_kind = request.args.get("kind", "sparkline")
        cache_key = f"market:charts:batch:{','.join(symbols)}:{range_key}:{chart_kind}"
        return jsonify(
            cached_json(
                cache_key,
                15,
                lambda: queries.get_market_charts_batch(symbols, range_key, chart_kind=chart_kind),
            )
        )

    @app.get("/api/v1/dashboard/overview")
    def dashboard_overview():
        return jsonify(cached_json("dashboard:overview", 15, queries.get_dashboard_overview))

    @app.get("/api/v1/prediction/latest")
    def prediction_latest():
        return jsonify(queries.get_prediction_summary())

    @app.get("/api/v1/prediction/chart")
    def prediction_chart():
        range_key = request.args.get("range", "1M")
        return jsonify(
            cached_json(
                f"prediction:chart:{range_key}",
                15,
                lambda: queries.get_prediction_chart(range_key),
            )
        )

    @app.get("/api/v1/prediction/ai-analysis")
    def prediction_ai_analysis():
        return jsonify(queries.get_prediction_ai_analysis())

    @app.get("/api/v1/factors/table")
    def factors_table():
        limit = min(int(request.args.get("limit", "80")), 200)
        return jsonify(queries.get_factor_table(query=request.args.get("query", ""), limit=limit))

    @app.get("/api/v1/news/list")
    def news_list():
        limit = min(int(request.args.get("limit", "80")), 200)
        start = request.args.get("start") or None
        end = request.args.get("end") or None
        query = request.args.get("query", "")
        timezone_name = request.args.get("timezone") or "UTC"
        return jsonify(
            cached_json(
                f"news:list:{start}:{end}:{query}:{limit}:{timezone_name}",
                30,
                lambda: queries.get_news_list(
                    start=start,
                    end=end,
                    query=query,
                    limit=limit,
                    timezone_name=timezone_name,
                ),
            )
        )

    @app.get("/api/v1/news/date-bounds")
    def news_date_bounds():
        timezone_name = request.args.get("timezone") or "UTC"
        return jsonify(
            cached_json(
                f"news:date-bounds:{timezone_name}",
                300,
                lambda: queries.get_news_date_bounds(timezone_name=timezone_name),
            )
        )

    @app.get("/api/v1/news/overview")
    def news_overview():
        limit = min(int(request.args.get("limit", "120")), 200)
        start = request.args.get("start") or None
        end = request.args.get("end") or None
        query = request.args.get("query", "")
        timezone_name = request.args.get("timezone") or "UTC"
        return jsonify(
            cached_json(
                f"news:overview:{start}:{end}:{query}:{limit}:{timezone_name}",
                30,
                lambda: queries.get_news_overview(
                    start=start,
                    end=end,
                    query=query,
                    limit=limit,
                    timezone_name=timezone_name,
                ),
            )
        )

    @app.get("/api/v1/news/feed")
    def news_feed():
        list_limit = min(int(request.args.get("listLimit", "80")), 200)
        overview_limit = min(int(request.args.get("overviewLimit", "120")), 200)
        start = request.args.get("start") or None
        end = request.args.get("end") or None
        query = request.args.get("query", "")
        timezone_name = request.args.get("timezone") or "UTC"
        return jsonify(
            cached_json(
                f"news:feed:{start}:{end}:{query}:{list_limit}:{overview_limit}:{timezone_name}",
                30,
                lambda: queries.get_news_feed(
                    start=start,
                    end=end,
                    query=query,
                    list_limit=list_limit,
                    overview_limit=overview_limit,
                    timezone_name=timezone_name,
                ),
            )
        )

    @app.get("/api/v1/news/<article_id>")
    def news_detail(article_id: str):
        return jsonify(queries.get_news_detail(article_id))

    @app.get("/api/v1/status/sources")
    def status_sources():
        return jsonify(cached_json("status:sources", 15, queries.get_status))

    @app.get("/api/v1/chat/bootstrap")
    def chat_bootstrap():
        return jsonify(chat.get_bootstrap())

    @app.post("/api/v1/chat/ask")
    def chat_ask():
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question", "")).strip()
        session = payload.get("session") or {}
        options = payload.get("options") or {}
        context = payload.get("context") or {}
        return jsonify(
            chat.ask(
                question=question,
                audience=str(options.get("audience", "enterprise")),
                session_id=session.get("sessionId"),
                history=session.get("history") or [],
                context=context if isinstance(context, dict) else {},
            )
        )

    @app.post("/api/v1/admin/auth/login")
    def admin_auth_login():
        payload = request.get_json(silent=True) or {}
        password = str(payload.get("password", ""))
        if not validate_admin_password(password):
            raise PermissionError("管理页密码无效")
        session = admin_sessions.create()
        return jsonify(
            {
                "token": session["token"],
                "expiresAt": session["expiresAt"],
            }
        )

    @app.get("/api/v1/admin/console/overview")
    def admin_console_overview():
        ensure_admin()
        return jsonify(build_overview_payload(database, runtime_store))

    @app.get("/api/v1/admin/console/config")
    def admin_console_config():
        ensure_admin()
        return jsonify(build_config_payload())

    @app.get("/api/v1/admin/console/programs")
    def admin_console_programs():
        ensure_admin()
        return jsonify(build_program_payload())

    @app.get("/api/v1/admin/console/logs")
    def admin_console_logs():
        ensure_admin()
        limit = max(1, min(int(request.args.get("limit", "50")), 200))
        return jsonify(
            build_logs_payload(
                database,
                runtime_store,
                limit=limit,
                task_name=request.args.get("task", "").strip(),
                status=request.args.get("status", "").strip(),
                source_key=request.args.get("source", "").strip(),
            )
        )

    @app.get("/api/v1/admin/console/logs/<run_id>")
    def admin_console_log_detail(run_id: str):
        ensure_admin()
        return jsonify(build_run_detail_payload(runtime_store, run_id))

    @app.post("/api/v1/admin/sync-market")
    def admin_sync_market():
        ensure_admin()
        payload = _run_worker_module("backend.workers.price_snapshot_worker", ["--once", "--trigger", "admin"])
        response_cache.invalidate_prefix("market:")
        response_cache.invalidate_prefix("prediction:chart:")
        response_cache.invalidate_prefix("dashboard:")
        response_cache.invalidate_prefix("status:")
        return jsonify(payload)

    @app.post("/api/v1/admin/backfill-market-minute-history")
    def admin_backfill_market_minute_history():
        ensure_admin()
        payload = _run_worker_module(
            "backend.workers.price_snapshot_worker",
            ["--once", "--trigger", "admin_backfill", "--full-minute-history"],
        )
        response_cache.invalidate_prefix("market:")
        response_cache.invalidate_prefix("prediction:chart:")
        response_cache.invalidate_prefix("dashboard:")
        response_cache.invalidate_prefix("status:")
        return jsonify(payload)

    @app.post("/api/v1/admin/sync-factors")
    def admin_sync_factors():
        ensure_admin()
        payload = _run_worker_module("backend.workers.factor_worker", ["--trigger", "admin"])
        response_cache.invalidate_prefix("prediction:chart:")
        response_cache.invalidate_prefix("dashboard:")
        response_cache.invalidate_prefix("status:")
        return jsonify(payload)

    @app.post("/api/v1/admin/run-model")
    def admin_run_model():
        ensure_admin()
        payload = _run_worker_module("backend.workers.model_worker", ["--trigger", "admin"])
        response_cache.invalidate_prefix("prediction:chart:")
        response_cache.invalidate_prefix("dashboard:")
        response_cache.invalidate_prefix("status:")
        return jsonify(payload)

    @app.post("/api/v1/admin/sync-news")
    def admin_sync_news():
        ensure_admin()
        payload = _run_worker_module("backend.workers.news_worker", ["--once", "--trigger", "admin"])
        response_cache.invalidate_prefix("news:")
        response_cache.invalidate_prefix("status:")
        return jsonify(payload)

    @app.post("/api/v1/admin/prediction/ai-analysis/regenerate")
    def admin_regenerate_prediction_ai():
        ensure_admin()
        payload = _run_worker_module("backend.workers.ai_analysis_worker", ["--trigger", "admin"])
        response_cache.invalidate_prefix("status:")
        return jsonify(payload)

    @app.post("/api/v1/admin/import-news-history")
    def admin_import_news_history():
        ensure_admin()
        service = backend_core.create_backend_service()
        batch_size = max(1, min(int(request.args.get("batch_size", "200")), 1000))
        limit_arg = request.args.get("limit")
        limit = max(1, int(limit_arg)) if limit_arg else None
        resume = request.args.get("resume", "1") != "0"
        workers = max(1, int(request.args.get("workers", "1")))
        executor_kind = request.args.get("executor", "auto")
        return jsonify(
            service.import_historical_news(
                batch_size=batch_size,
                limit=limit,
                resume=resume,
                workers=workers,
                executor_kind=executor_kind,
            ).__dict__
        )

    @app.post("/api/v1/admin/reanalyze-news")
    def admin_reanalyze_news():
        ensure_admin()
        service = backend_core.create_backend_service()
        batch_size = max(1, min(int(request.args.get("batch_size", "200")), 1000))
        limit_arg = request.args.get("limit")
        limit = max(1, int(limit_arg)) if limit_arg else None
        return jsonify(service.reanalyze_news(batch_size=batch_size, limit=limit).__dict__)

    @app.errorhandler(Exception)
    def handle_error(error):
        status_code = 500
        if isinstance(error, ValueError):
            status_code = 400
        elif isinstance(error, PermissionError):
            status_code = 403
        error_logger.exception(
            "未处理异常 method=%s path=%s query=%s",
            request.method,
            request.path,
            request.query_string.decode("utf-8", errors="ignore"),
        )
        return jsonify({"error": str(error)}), status_code

    return app


app = create_app()


def main() -> None:
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "5001"))
    debug = os.getenv("BACKEND_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
