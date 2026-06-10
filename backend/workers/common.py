from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Any

from .. import core_backend as backend_core
from ..runtime_store import RuntimeStore


TASK_VIEW_KEYS = {
    "price_snapshot_worker": "latest_prices",
    "news_worker": "latest_news",
    "factor_worker": "latest_factors",
    "model_worker": "latest_model",
    "ai_analysis_worker": "latest_ai_report",
}


@dataclass
class FailureState:
    signature: str
    count: int = 0


@dataclass
class LastRenderedLine:
    task_name: str
    replaceable: bool


class TaskLogEmitter:
    _LEVEL_COLORS = {
        "INFO": "\x1b[36m",
        "WARN": "\x1b[33m",
        "ERROR": "\x1b[31m",
        "RECOVERY": "\x1b[92m",
    }
    _RESET = "\x1b[0m"
    _HIGH_FREQUENCY_TASKS = {"price_snapshot_worker", "news_worker"}
    _EVENT_META = {
        "daemon_spawning": ("INFO", "拉起守护进程"),
        "daemon_started": ("INFO", "守护进程已启动"),
        "daemon_stopped": ("WARN", "守护进程已停止"),
        "oneshot_triggered": ("INFO", "触发一次性任务"),
        "oneshot_completed": ("INFO", "一次性任务完成"),
        "oneshot_started": ("INFO", "开始执行"),
        "oneshot_succeeded": ("INFO", "执行完成"),
        "oneshot_failed": ("ERROR", "执行失败"),
        "iteration_succeeded": ("INFO", "本轮同步完成"),
        "iteration_failed": ("ERROR", "执行失败"),
    }
    _FIELD_ORDER = [
        "module",
        "triggerType",
        "intervalSeconds",
        "batchId",
        "dataAsOf",
        "rowCount",
        "inputFactorBatchId",
        "inputModelBatchId",
        "nextRunInSeconds",
        "reason",
        "runId",
    ]

    def __init__(
        self,
        *,
        stream=None,
        is_tty: bool | None = None,
        color_mode: str | None = None,
        overwrite_mode: str | None = None,
        error_summary_initial_threshold: int | None = None,
        error_summary_repeat_every: int | None = None,
    ) -> None:
        self.stream = stream or sys.stdout
        self.is_tty = is_tty if is_tty is not None else bool(getattr(self.stream, "isatty", lambda: False)())
        self.color_mode = (color_mode or os.getenv("ORCHESTRATOR_LOG_COLOR", "auto")).strip().lower()
        self.overwrite_mode = (overwrite_mode or os.getenv("ORCHESTRATOR_LOG_OVERWRITE_SUCCESS", "auto")).strip().lower()
        self.error_summary_initial_threshold = max(
            1,
            int(os.getenv("ORCHESTRATOR_ERROR_SUMMARY_INITIAL_THRESHOLD", str(error_summary_initial_threshold or 5))),
        )
        self.error_summary_repeat_every = max(
            1,
            int(os.getenv("ORCHESTRATOR_ERROR_SUMMARY_REPEAT_EVERY", str(error_summary_repeat_every or 10))),
        )
        self._failures: dict[str, FailureState] = {}
        self._last_rendered_line: LastRenderedLine | None = None
        self.logger = logging.getLogger("backend.tasks")

    def emit(self, task_name: str, event: str, **fields: Any) -> None:
        payload = {
            "timestamp": backend_core.iso_now(),
            "task": task_name,
            "event": event,
            "pid": os.getpid(),
        }
        payload.update(fields)

        if event == "iteration_started":
            return

        if event in {"iteration_failed", "oneshot_failed"}:
            self._emit_failure(task_name, event, payload)
            return

        recovery_line = self._build_recovery_line(task_name)
        if recovery_line:
            self._write_line(task_name, recovery_line, replaceable=False)

        line = self._render_line(task_name, event, payload)
        replaceable = self._is_replaceable_success(task_name, event)
        self._write_line(task_name, line, replaceable=replaceable)

    def _emit_failure(self, task_name: str, event: str, payload: dict[str, Any]) -> None:
        signature = str(payload.get("error", "")).strip() or "未知错误"
        state = self._failures.get(task_name)
        if state is None or state.signature != signature:
            self._failures[task_name] = FailureState(signature=signature, count=1)
            self._write_line(task_name, self._render_line(task_name, event, payload), replaceable=False)
            return

        state.count += 1
        if state.count == self.error_summary_initial_threshold or (
            state.count > self.error_summary_initial_threshold
            and (state.count - self.error_summary_initial_threshold) % self.error_summary_repeat_every == 0
        ):
            summary_payload = {
                "timestamp": payload["timestamp"],
                "error": signature,
                "failureCount": state.count,
            }
            self._write_line(task_name, self._render_failure_summary(task_name, summary_payload), replaceable=False)

    def _build_recovery_line(self, task_name: str) -> str | None:
        state = self._failures.pop(task_name, None)
        if state is None:
            return None
        timestamp = self._format_timestamp(backend_core.iso_now())
        level = self._colorize("RECOVERY", "RECOVERY")
        message = "已恢复"
        details = [f"此前连续失败 {state.count} 次"]
        if state.signature:
            details.append(f"最近错误={state.signature}")
        return f"[{timestamp}] {level:<8} [{task_name}] {message} | {' '.join(details)}"

    def _render_failure_summary(self, task_name: str, payload: dict[str, Any]) -> str:
        timestamp = self._format_timestamp(payload["timestamp"])
        level = self._colorize("WARN", "WARN")
        details = [f"连续失败 {payload['failureCount']} 次", f"最近错误={payload['error']}"]
        return f"[{timestamp}] {level:<8} [{task_name}] 重复错误汇总 | {' '.join(details)}"

    def _render_line(self, task_name: str, event: str, payload: dict[str, Any]) -> str:
        level_name, message = self._EVENT_META.get(event, ("INFO", event))
        timestamp = self._format_timestamp(payload["timestamp"])
        level = self._colorize(level_name, level_name)
        details = self._format_fields(payload, event)
        suffix = f" | {details}" if details else ""
        return f"[{timestamp}] {level:<8} [{task_name}] {message}{suffix}"

    def _format_fields(self, payload: dict[str, Any], event: str) -> str:
        details = []
        for key in self._FIELD_ORDER:
            value = payload.get(key)
            if value in (None, "", []):
                continue
            details.append(f"{key}={value}")
        if event in {"iteration_failed", "oneshot_failed"}:
            error = str(payload.get("error", "")).strip()
            if error:
                details.append(f"error={error}")
        seen = set(self._FIELD_ORDER + ["timestamp", "task", "event", "pid", "error"])
        for key, value in payload.items():
            if key in seen or value in (None, "", []):
                continue
            details.append(f"{key}={value}")
        return " ".join(details)

    def _write_line(self, task_name: str, line: str, *, replaceable: bool) -> None:
        if self._should_overwrite(task_name, replaceable):
            self.stream.write("\x1b[1A\r\x1b[2K")
        self.stream.write(f"{line}\n")
        self.stream.flush()
        self.logger.info(line)
        self._last_rendered_line = LastRenderedLine(task_name=task_name, replaceable=replaceable)

    def _should_overwrite(self, task_name: str, replaceable: bool) -> bool:
        if not replaceable or not self._supports_overwrite():
            return False
        if not self._last_rendered_line or not self._last_rendered_line.replaceable:
            return False
        return self._last_rendered_line.task_name == task_name

    def _supports_color(self) -> bool:
        if self.color_mode == "always":
            return True
        if self.color_mode == "never":
            return False
        return self.is_tty

    def _supports_overwrite(self) -> bool:
        if self.overwrite_mode == "always":
            return True
        if self.overwrite_mode == "never":
            return False
        return self.is_tty

    def _colorize(self, level_name: str, text: str) -> str:
        if not self._supports_color():
            return text
        return f"{self._LEVEL_COLORS[level_name]}{text}{self._RESET}"

    def _format_timestamp(self, timestamp: str) -> str:
        return timestamp[11:19] if len(timestamp) >= 19 else timestamp

    def _is_replaceable_success(self, task_name: str, event: str) -> bool:
        return event == "iteration_succeeded" and task_name in self._HIGH_FREQUENCY_TASKS


_TASK_LOG_EMITTER = TaskLogEmitter()


def log_task_event(task_name: str, event: str, **fields: Any) -> None:
    _TASK_LOG_EMITTER.emit(task_name, event, **fields)


def get_runtime_store() -> RuntimeStore:
    return RuntimeStore(backend_core.DB_PATH, backend_core.iso_now)


def get_database():
    return backend_core.create_database()


def bootstrap_runtime() -> RuntimeStore:
    database = get_database()
    runtime_store = get_runtime_store()
    runtime_store.init()
    runtime_store.finish_orphaned_task_runs()
    runtime_store.bootstrap_views_from_existing_data()
    database.normalize_news_published_at_values()
    return runtime_store


def build_success_payload(task_name: str, run_id: str, batch_id: str, details: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "task": task_name,
        "runId": run_id,
        "batchId": batch_id,
        "status": "success",
        "timestamp": backend_core.iso_now(),
    }
    payload.update(details)
    return payload


def mark_source_success(
    database,
    source_key: str,
    batch_id: str,
    data_as_of: str | None,
    run_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "status": "success",
        "batch_id": batch_id,
        "data_as_of": data_as_of,
        "run_id": run_id,
        "generated_at": backend_core.iso_now(),
        "last_error": "",
    }
    if extra:
        payload.update(extra)
    database.upsert_source_status(source_key, payload)


def mark_source_failure(
    database,
    runtime_store: RuntimeStore,
    task_name: str,
    run_id: str,
    error: Exception,
) -> None:
    source_key = {
        "price_snapshot_worker": "market",
        "news_worker": backend_core.NEWS_SOURCE_KEY,
        "factor_worker": "factors",
        "model_worker": "model",
        "ai_analysis_worker": "ai_analysis",
    }[task_name]
    runtime_store.set_view_stale(TASK_VIEW_KEYS[task_name], True)
    database.patch_source_status(
        source_key,
        {
            "status": "failed",
            "last_error": str(error),
            "last_failure_at": backend_core.iso_now(),
            "run_id": run_id,
        },
    )
    database.insert_job_log(source_key, "failed", str(error))


def run_daemon(
    task_name: str,
    interval_seconds: int,
    iteration_fn,
    trigger_type: str = "supervisor",
    **config: Any,
) -> None:
    runtime_store = bootstrap_runtime()
    database = get_database()
    stop_signal: dict[str, str | None] = {"reason": None}
    run_config = {"intervalSeconds": interval_seconds}
    run_config.update(config)
    run_id = runtime_store.start_task_run(
        task_name=task_name,
        task_mode="daemon",
        trigger_type=trigger_type,
        config=run_config,
        worker_pid=os.getpid(),
    )

    def _request_stop(signum, _frame) -> None:
        signal_name = signal.Signals(signum).name.lower()
        stop_signal["reason"] = signal_name

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    log_task_event(
        task_name,
        "daemon_started",
        runId=run_id,
        triggerType=trigger_type,
        intervalSeconds=interval_seconds,
        **config,
    )
    try:
        while not stop_signal["reason"]:
            runtime_store.heartbeat(run_id)
            log_task_event(task_name, "iteration_started", runId=run_id)
            try:
                iteration_fn(run_id, runtime_store, database, **config)
                runtime_store.heartbeat(run_id)
                log_task_event(
                    task_name,
                    "iteration_succeeded",
                    runId=run_id,
                    nextRunInSeconds=interval_seconds,
                    **config,
                )
            except Exception as error:
                mark_source_failure(database, runtime_store, task_name, run_id, error)
                runtime_store.heartbeat(run_id)
                log_task_event(task_name, "iteration_failed", runId=run_id, error=str(error))
            if stop_signal["reason"]:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        stop_signal["reason"] = stop_signal["reason"] or "keyboard_interrupt"
    finally:
        runtime_store.finish_task_run(run_id, "success")
        log_task_event(task_name, "daemon_stopped", runId=run_id, reason=stop_signal["reason"] or "shutdown")
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


def print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))
