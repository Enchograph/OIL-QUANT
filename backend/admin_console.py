from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import core_backend as backend_core


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mask_secret(value: str, visible_suffix: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= visible_suffix:
        return "*" * len(raw)
    return "*" * max(4, len(raw) - visible_suffix) + raw[-visible_suffix:]


@dataclass
class ConfigItem:
    key: str
    label: str
    group: str
    description: str
    sensitive: bool = False


class AdminSessionStore:
    def __init__(self, ttl_seconds: int = 8 * 60 * 60):
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, datetime] = {}

    def create(self) -> dict[str, str]:
        token = secrets.token_urlsafe(32)
        expires_at = _utc_now() + timedelta(seconds=self.ttl_seconds)
        self._sessions[token] = expires_at
        return {
            "token": token,
            "expiresAt": expires_at.isoformat(),
        }

    def verify(self, token: str | None) -> bool:
        if not token:
            return False
        expires_at = self._sessions.get(token)
        if expires_at is None:
            return False
        if expires_at <= _utc_now():
            self._sessions.pop(token, None)
            return False
        return True


CONFIG_ITEMS = [
    ConfigItem("ADMIN_PAGE_PASSWORD", "管理页密码", "Security", "控制 `/admin` 登录密码。", sensitive=True),
    ConfigItem("BACKEND_ADMIN_KEY", "管理接口密钥", "Security", "兼容现有管理接口的 `X-Admin-Key`。", sensitive=True),
    ConfigItem("BACKEND_HOST", "后端监听地址", "Backend", "Flask API 服务监听地址。"),
    ConfigItem("BACKEND_PORT", "后端监听端口", "Backend", "Flask API 服务监听端口。"),
    ConfigItem("BACKEND_DEBUG", "调试模式", "Backend", "是否以调试模式运行 Flask。"),
    ConfigItem("ORCHESTRATOR_TIMEZONE", "调度时区", "Scheduling", "后台调度器使用的时区。"),
    ConfigItem("MARKET_SYNC_INTERVAL_SECONDS", "行情同步间隔", "Scheduling", "行情 worker 常驻轮询间隔（秒）。"),
    ConfigItem("NEWS_SYNC_INTERVAL_SECONDS", "新闻同步间隔", "Scheduling", "新闻 worker 常驻轮询间隔（秒）。"),
    ConfigItem("FACTOR_DAILY_RUN_AT", "因子任务时间", "Scheduling", "因子日任务触发时间。"),
    ConfigItem("MODEL_DAILY_RUN_AT", "模型任务时间", "Scheduling", "模型日任务触发时间。"),
    ConfigItem("AI_ANALYSIS_DAILY_RUN_AT", "AI 分析时间", "Scheduling", "AI 分析日任务触发时间。"),
    ConfigItem("MARKET_DATA_PROVIDER", "行情提供方", "Market", "当前使用的行情数据源。"),
    ConfigItem("MARKET_DATA_API_KEY", "行情 API Key", "Market", "行情源鉴权密钥。", sensitive=True),
    ConfigItem("MARKET_DATA_BASE_URL", "行情基地址", "Market", "行情源接口基地址。"),
    ConfigItem("AI_CHAT_BASE_URL", "聊天模型地址", "AI", "聊天模型 API 基地址。"),
    ConfigItem("AI_CHAT_MODEL", "聊天模型", "AI", "问答与分析使用的聊天模型。"),
    ConfigItem("AI_CHAT_API_KEY", "聊天模型 API Key", "AI", "聊天模型密钥。", sensitive=True),
    ConfigItem("AI_EMBEDDING_BASE_URL", "Embedding 地址", "AI", "Embedding 模型 API 基地址。"),
    ConfigItem("AI_EMBEDDING_MODEL", "Embedding 模型", "AI", "Embedding 模型标识。"),
    ConfigItem("AI_EMBEDDING_API_KEY", "Embedding API Key", "AI", "Embedding 模型密钥。", sensitive=True),
    ConfigItem("EIA_API_KEY", "EIA API Key", "Factors", "因子更新使用的 EIA 密钥。", sensitive=True),
]


PROGRAMS = [
    {
        "id": "api_service",
        "title": "Flask API 服务",
        "category": "Core",
        "runMode": "daemon",
        "entryCommand": "python backend/run.py",
        "description": "负责向前端提供查询、预测、新闻、因子与管理接口。",
        "envKeys": ["BACKEND_HOST", "BACKEND_PORT", "BACKEND_DEBUG"],
    },
    {
        "id": "orchestrator_service",
        "title": "调度器",
        "category": "Core",
        "runMode": "daemon",
        "entryCommand": "python -m backend.orchestrator_service",
        "description": "统一监督常驻 worker，并按日拉起一次性任务。",
        "envKeys": [
            "MARKET_SYNC_INTERVAL_SECONDS",
            "NEWS_SYNC_INTERVAL_SECONDS",
            "FACTOR_DAILY_RUN_AT",
            "MODEL_DAILY_RUN_AT",
            "AI_ANALYSIS_DAILY_RUN_AT",
            "ORCHESTRATOR_TIMEZONE",
        ],
    },
    {
        "id": "price_snapshot_worker",
        "title": "行情 worker",
        "category": "Workers",
        "runMode": "daemon",
        "entryCommand": "python -m backend.workers.price_snapshot_worker --once --trigger admin",
        "description": "抓取并聚合行情快照，可手动刷新或执行分钟历史补采。",
        "actionId": "sync-market",
        "actionPath": "/api/v1/admin/sync-market",
        "envKeys": ["MARKET_DATA_PROVIDER", "MARKET_DATA_API_KEY", "MARKET_SYNC_INTERVAL_SECONDS"],
    },
    {
        "id": "factor_worker",
        "title": "因子 worker",
        "category": "Workers",
        "runMode": "oneshot",
        "entryCommand": "python -m backend.workers.factor_worker --trigger admin",
        "description": "按数据库增量补齐因子快照，并回导模型兼容 CSV。",
        "actionId": "sync-factors",
        "actionPath": "/api/v1/admin/sync-factors",
        "envKeys": ["FACTOR_DAILY_RUN_AT", "EIA_API_KEY"],
    },
    {
        "id": "model_worker",
        "title": "模型 worker",
        "category": "Workers",
        "runMode": "oneshot",
        "entryCommand": "python -m backend.workers.model_worker --trigger admin",
        "description": "读取数据库/CSV 的最新因子，执行量化预测并发布结果。",
        "actionId": "run-model",
        "actionPath": "/api/v1/admin/run-model",
        "envKeys": ["MODEL_DAILY_RUN_AT"],
    },
    {
        "id": "ai_analysis_worker",
        "title": "AI 分析 worker",
        "category": "Workers",
        "runMode": "oneshot",
        "entryCommand": "python -m backend.workers.ai_analysis_worker --trigger admin",
        "description": "基于模型结果生成企业侧与银行侧分析。",
        "actionId": "run-ai-analysis",
        "actionPath": "/api/v1/admin/prediction/ai-analysis/regenerate",
        "envKeys": ["AI_ANALYSIS_DAILY_RUN_AT", "AI_CHAT_BASE_URL", "AI_CHAT_MODEL"],
    },
    {
        "id": "news_worker",
        "title": "新闻 worker",
        "category": "Workers",
        "runMode": "daemon",
        "entryCommand": "python -m backend.workers.news_worker --once --trigger admin",
        "description": "抓取新闻、执行 NLP 分析并更新新闻源状态。",
        "actionId": "sync-news",
        "actionPath": "/api/v1/admin/sync-news",
        "envKeys": ["NEWS_SYNC_INTERVAL_SECONDS", "AI_CHAT_BASE_URL", "AI_CHAT_MODEL"],
    },
]


def get_admin_password() -> str:
    return os.getenv("ADMIN_PAGE_PASSWORD", "").strip()


def validate_admin_password(password: str) -> bool:
    configured = get_admin_password()
    return bool(configured) and secrets.compare_digest(password or "", configured)


def build_config_payload() -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in CONFIG_ITEMS:
        raw_value = os.getenv(item.key, "")
        value = mask_secret(raw_value) if item.sensitive else raw_value
        entry = {
            "key": item.key,
            "label": item.label,
            "group": item.group,
            "description": item.description,
            "sensitive": item.sensitive,
            "value": value,
            "configured": bool(raw_value.strip()),
        }
        groups.setdefault(item.group, []).append(entry)
    return {
        "items": [entry for entries in groups.values() for entry in entries],
        "groups": [{"name": group, "items": entries} for group, entries in groups.items()],
        "updatedAt": backend_core.iso_now(),
    }


def build_program_payload() -> dict[str, Any]:
    return {
        "programs": PROGRAMS,
        "updatedAt": backend_core.iso_now(),
    }


def build_overview_payload(database, runtime_store) -> dict[str, Any]:
    sources = database.get_source_status()
    views = runtime_store.list_views()
    recent_runs = runtime_store.list_recent_task_runs(limit=12)
    recent_batches = runtime_store.list_recent_batches(limit=12)
    return {
        "sources": sources,
        "views": views,
        "recentRuns": recent_runs,
        "recentBatches": recent_batches,
        "summary": {
            "sourceCount": len(sources),
            "viewCount": len(views),
            "runningCount": len([item for item in recent_runs if item["status"] == "running"]),
            "failedCount": len([item for item in recent_runs if item["status"] == "failed"]),
        },
        "updatedAt": backend_core.iso_now(),
    }


def build_logs_payload(database, runtime_store, *, limit: int = 50, task_name: str = "", status: str = "", source_key: str = "") -> dict[str, Any]:
    job_logs = database.get_job_logs(limit=limit, source_key=source_key, status=status)
    task_runs = runtime_store.list_recent_task_runs(limit=max(limit, 20))
    if task_name:
        task_runs = [item for item in task_runs if item["taskName"] == task_name]
    if status:
        task_runs = [item for item in task_runs if item["status"] == status]
    recent_batches = runtime_store.list_recent_batches(limit=max(limit, 20))
    if task_name:
        recent_batches = [item for item in recent_batches if item["producerTask"] == task_name]
    return {
        "jobLogs": job_logs[:limit],
        "taskRuns": task_runs[:limit],
        "batches": recent_batches[:limit],
        "views": runtime_store.list_views(),
        "updatedAt": backend_core.iso_now(),
    }


def build_run_detail_payload(runtime_store, run_id: str) -> dict[str, Any]:
    run = runtime_store.get_task_run(run_id)
    if not run:
        raise ValueError("运行记录不存在")
    batches = runtime_store.list_batches_by_run(run_id)
    return {
        "run": run,
        "batches": batches,
        "updatedAt": backend_core.iso_now(),
    }
