from __future__ import annotations

import os
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .workers.common import bootstrap_runtime
from .workers.common import log_task_event


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


def _build_worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(WORKER_SINGLE_THREAD_ENV)
    return env


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


def _is_heavy_worker_module(module: str) -> bool:
    return module in HEAVY_WORKER_MODULES


@dataclass
class ManagedProcess:
    name: str
    module: str
    interval: int
    process: subprocess.Popen | None = None


@dataclass
class DailyTaskSchedule:
    task_name: str
    module: str
    run_at: dt_time
    last_scheduled_date: str


def _parse_run_at(value: str, default_value: str) -> dt_time:
    raw = (value or default_value).strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"调度时间格式无效：{raw}，应为 HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"调度时间超出范围：{raw}")
    return dt_time(hour=hour, minute=minute)


class OrchestratorService:
    def __init__(self) -> None:
        self.runtime_store = bootstrap_runtime()
        self.timezone = ZoneInfo(os.getenv("ORCHESTRATOR_TIMEZONE", "Asia/Shanghai"))
        self.price_interval = int(os.getenv("MARKET_SYNC_INTERVAL_SECONDS", "300"))
        self.news_interval = int(os.getenv("NEWS_SYNC_INTERVAL_SECONDS", "300"))
        self.daemons = [
            ManagedProcess("price_snapshot_worker", "backend.workers.price_snapshot_worker", self.price_interval),
            ManagedProcess("news_worker", "backend.workers.news_worker", self.news_interval),
        ]
        self.runtime_store.finish_running_task_runs(
            [managed.name for managed in self.daemons],
            task_mode="daemon",
            status="stopped",
            error_message="调度器重启后自动收尾旧守护进程记录",
        )
        self.daily_tasks = self._build_daily_tasks()

    def _now_local(self) -> datetime:
        return datetime.now(self.timezone)

    def _initial_last_scheduled_date(self, run_at: dt_time) -> str:
        now = self._now_local()
        if now.time() >= run_at:
            return now.date().isoformat()
        return (now.date() - timedelta(days=1)).isoformat()

    def _build_daily_tasks(self) -> dict[str, DailyTaskSchedule]:
        factor_time = _parse_run_at(os.getenv("FACTOR_DAILY_RUN_AT", ""), "00:00")
        model_time = _parse_run_at(os.getenv("MODEL_DAILY_RUN_AT", ""), "01:00")
        ai_time = _parse_run_at(os.getenv("AI_ANALYSIS_DAILY_RUN_AT", ""), "02:00")
        tasks = [
            ("factor_worker", "backend.workers.factor_worker", factor_time),
            ("model_worker", "backend.workers.model_worker", model_time),
            ("ai_analysis_worker", "backend.workers.ai_analysis_worker", ai_time),
        ]
        return {
            task_name: DailyTaskSchedule(
                task_name=task_name,
                module=module,
                run_at=run_at,
                last_scheduled_date=self._initial_last_scheduled_date(run_at),
            )
            for task_name, module, run_at in tasks
        }

    def _spawn_daemon(self, managed: ManagedProcess) -> None:
        log_task_event(
            "orchestrator",
            "daemon_spawning",
            worker=managed.name,
            module=managed.module,
            intervalSeconds=managed.interval,
        )
        managed.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                managed.module,
                "--interval",
                str(managed.interval),
                "--trigger",
                "supervisor",
            ],
            cwd=str(REPO_ROOT),
            env=_build_worker_env() if _is_heavy_worker_module(managed.module) else None,
            preexec_fn=_apply_worker_priority if _is_heavy_worker_module(managed.module) else None,
        )

    def ensure_daemons(self) -> None:
        for managed in self.daemons:
            if managed.process is None or managed.process.poll() is not None:
                self._spawn_daemon(managed)

    def _run_oneshot(self, module: str) -> None:
        log_task_event("orchestrator", "oneshot_triggered", module=module)
        subprocess.run(
            [sys.executable, "-m", module, "--trigger", "supervisor"],
            cwd=str(REPO_ROOT),
            env=_build_worker_env() if _is_heavy_worker_module(module) else None,
            preexec_fn=_apply_worker_priority if _is_heavy_worker_module(module) else None,
            check=True,
        )
        log_task_event("orchestrator", "oneshot_completed", module=module)

    def _should_run_daily_task(self, schedule: DailyTaskSchedule, now: datetime) -> bool:
        today = now.date().isoformat()
        if today <= schedule.last_scheduled_date:
            return False
        return now.time() >= schedule.run_at

    def _run_due_daily_tasks(self) -> None:
        now = self._now_local()
        today = now.date().isoformat()
        for schedule in self.daily_tasks.values():
            if not self._should_run_daily_task(schedule, now):
                continue
            self._run_oneshot(schedule.module)
            schedule.last_scheduled_date = today

    def run_forever(self) -> None:
        while True:
            self.ensure_daemons()
            self._run_due_daily_tasks()
            time.sleep(5)


def main() -> None:
    OrchestratorService().run_forever()


if __name__ == "__main__":
    main()
