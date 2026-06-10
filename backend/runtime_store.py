from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _json_loads(payload: str | None, default: Any = None) -> Any:
    if not payload:
        return default
    return json.loads(payload)


class RuntimeStore:
    def __init__(self, db_path: Path, now_factory):
        self.db_path = db_path
        self.now_factory = now_factory

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    run_id TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    task_mode TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    worker_pid INTEGER,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    heartbeat_at TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS data_batches (
                    batch_id TEXT PRIMARY KEY,
                    producer_task TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    run_id TEXT,
                    data_as_of TEXT,
                    generated_at TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT NOT NULL,
                    stale INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS batch_inputs (
                    batch_id TEXT NOT NULL,
                    input_name TEXT NOT NULL,
                    input_batch_id TEXT NOT NULL,
                    PRIMARY KEY (batch_id, input_name)
                );

                CREATE TABLE IF NOT EXISTS published_views (
                    view_key TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    previous_batch_id TEXT,
                    stale INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS runtime_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    batch_id TEXT,
                    artifact_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    mime_type TEXT,
                    created_at TEXT NOT NULL,
                    meta_json TEXT NOT NULL
                );
                """
            )

    def start_task_run(
        self,
        task_name: str,
        task_mode: str,
        trigger_type: str,
        config: dict[str, Any] | None = None,
        worker_pid: int | None = None,
    ) -> str:
        run_id = uuid4().hex[:12]
        now = self.now_factory()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO task_runs (
                    run_id, task_name, task_mode, trigger_type, status,
                    config_json, worker_pid, started_at, heartbeat_at
                )
                VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_name,
                    task_mode,
                    trigger_type,
                    _json_dumps(config or {}),
                    worker_pid,
                    now,
                    now,
                ),
            )
        return run_id

    def heartbeat(self, run_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE task_runs SET heartbeat_at = ? WHERE run_id = ?",
                (self.now_factory(), run_id),
            )

    def finish_task_run(self, run_id: str, status: str, error_message: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE task_runs
                SET status = ?, finished_at = ?, heartbeat_at = ?, error_message = ?
                WHERE run_id = ?
                """,
                (status, self.now_factory(), self.now_factory(), error_message, run_id),
            )

    def _pid_is_alive(self, pid: int | None) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def finish_running_task_runs(
        self,
        task_names: list[str],
        *,
        task_mode: str = "",
        status: str = "stopped",
        error_message: str = "",
    ) -> int:
        if not task_names:
            return 0
        placeholders = ", ".join(["?"] * len(task_names))
        clauses = [f"task_name IN ({placeholders})", "status = 'running'"]
        where_params: list[Any] = [*task_names]
        if task_mode:
            clauses.append("task_mode = ?")
            where_params.append(task_mode)
        update_params = [status, self.now_factory(), self.now_factory(), error_message]
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE task_runs
                SET status = ?, finished_at = ?, heartbeat_at = ?, error_message = ?
                WHERE {' AND '.join(clauses)}
                """,
                [*update_params, *where_params],
            )
        return int(cursor.rowcount or 0)

    def finish_orphaned_task_runs(
        self,
        *,
        status: str = "stopped",
        error_message: str = "检测到进程不存在，自动收尾孤儿任务记录",
    ) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, worker_pid
                FROM task_runs
                WHERE status = 'running' AND worker_pid IS NOT NULL
                """
            ).fetchall()
            orphaned_run_ids = [row["run_id"] for row in rows if not self._pid_is_alive(row["worker_pid"])]
            if not orphaned_run_ids:
                return 0
            placeholders = ", ".join(["?"] * len(orphaned_run_ids))
            cursor = connection.execute(
                f"""
                UPDATE task_runs
                SET status = ?, finished_at = ?, heartbeat_at = ?, error_message = ?
                WHERE run_id IN ({placeholders})
                """,
                [status, self.now_factory(), self.now_factory(), error_message, *orphaned_run_ids],
            )
        return int(cursor.rowcount or 0)

    def create_batch(
        self,
        producer_task: str,
        entity_type: str,
        run_id: str | None,
        data_as_of: str | None,
        row_count: int,
        summary: dict[str, Any] | None = None,
    ) -> str:
        batch_id = uuid4().hex[:16]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO data_batches (
                    batch_id, producer_task, entity_type, run_id, data_as_of,
                    generated_at, row_count, summary_json, stale
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    batch_id,
                    producer_task,
                    entity_type,
                    run_id,
                    data_as_of,
                    self.now_factory(),
                    row_count,
                    _json_dumps(summary or {}),
                ),
            )
        return batch_id

    def set_batch_inputs(self, batch_id: str, inputs: dict[str, str]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM batch_inputs WHERE batch_id = ?", (batch_id,))
            connection.executemany(
                "INSERT INTO batch_inputs (batch_id, input_name, input_batch_id) VALUES (?, ?, ?)",
                [(batch_id, name, input_batch_id) for name, input_batch_id in inputs.items()],
            )

    def publish_view(self, view_key: str, batch_id: str, stale: bool = False) -> None:
        now = self.now_factory()
        with self.connect() as connection:
            previous = connection.execute(
                "SELECT batch_id FROM published_views WHERE view_key = ?",
                (view_key,),
            ).fetchone()
            previous_batch_id = previous["batch_id"] if previous else None
            connection.execute(
                """
                INSERT INTO published_views (view_key, batch_id, published_at, previous_batch_id, stale)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(view_key) DO UPDATE SET
                    batch_id = excluded.batch_id,
                    published_at = excluded.published_at,
                    previous_batch_id = excluded.previous_batch_id,
                    stale = excluded.stale
                """,
                (view_key, batch_id, now, previous_batch_id, 1 if stale else 0),
            )
            connection.execute(
                "UPDATE data_batches SET stale = ? WHERE batch_id = ?",
                (1 if stale else 0, batch_id),
            )

    def set_view_stale(self, view_key: str, stale: bool) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT batch_id FROM published_views WHERE view_key = ?",
                (view_key,),
            ).fetchone()
            if not row:
                return
            connection.execute(
                "UPDATE published_views SET stale = ? WHERE view_key = ?",
                (1 if stale else 0, view_key),
            )
            connection.execute(
                "UPDATE data_batches SET stale = ? WHERE batch_id = ?",
                (1 if stale else 0, row["batch_id"]),
            )

    def get_published_view(self, view_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    v.view_key,
                    v.batch_id,
                    v.published_at,
                    v.previous_batch_id,
                    v.stale,
                    b.producer_task,
                    b.entity_type,
                    b.run_id,
                    b.data_as_of,
                    b.generated_at,
                    b.row_count,
                    b.summary_json
                FROM published_views v
                JOIN data_batches b ON b.batch_id = v.batch_id
                WHERE v.view_key = ?
                """,
                (view_key,),
            ).fetchone()
        if not row:
            return None
        return {
            "viewKey": row["view_key"],
            "batchId": row["batch_id"],
            "publishedAt": row["published_at"],
            "previousBatchId": row["previous_batch_id"],
            "stale": bool(row["stale"]),
            "producerTask": row["producer_task"],
            "entityType": row["entity_type"],
            "runId": row["run_id"],
            "dataAsOf": row["data_as_of"],
            "generatedAt": row["generated_at"],
            "rowCount": int(row["row_count"] or 0),
            "summary": _json_loads(row["summary_json"], {}),
        }

    def list_batch_inputs(self, batch_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    i.input_name,
                    i.input_batch_id,
                    b.producer_task,
                    b.entity_type,
                    b.data_as_of,
                    b.generated_at,
                    b.row_count,
                    b.summary_json
                FROM batch_inputs i
                JOIN data_batches b ON b.batch_id = i.input_batch_id
                WHERE i.batch_id = ?
                ORDER BY i.input_name ASC
                """,
                (batch_id,),
            ).fetchall()
        return [
            {
                "inputName": row["input_name"],
                "batchId": row["input_batch_id"],
                "producerTask": row["producer_task"],
                "entityType": row["entity_type"],
                "dataAsOf": row["data_as_of"],
                "generatedAt": row["generated_at"],
                "rowCount": int(row["row_count"] or 0),
                "summary": _json_loads(row["summary_json"], {}),
            }
            for row in rows
        ]

    def list_views(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT view_key, batch_id, published_at, previous_batch_id, stale
                FROM published_views
                ORDER BY view_key ASC
                """
            ).fetchall()
        return [
            {
                "viewKey": row["view_key"],
                "batchId": row["batch_id"],
                "publishedAt": row["published_at"],
                "previousBatchId": row["previous_batch_id"],
                "stale": bool(row["stale"]),
            }
            for row in rows
        ]

    def list_recent_task_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    run_id, task_name, task_mode, trigger_type, status, config_json,
                    worker_pid, started_at, finished_at, heartbeat_at, error_message
                FROM task_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "runId": row["run_id"],
                "taskName": row["task_name"],
                "taskMode": row["task_mode"],
                "triggerType": row["trigger_type"],
                "status": row["status"],
                "config": _json_loads(row["config_json"], {}),
                "workerPid": row["worker_pid"],
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
                "heartbeatAt": row["heartbeat_at"],
                "errorMessage": row["error_message"] or "",
            }
            for row in rows
        ]

    def get_task_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    run_id, task_name, task_mode, trigger_type, status, config_json,
                    worker_pid, started_at, finished_at, heartbeat_at, error_message
                FROM task_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "runId": row["run_id"],
            "taskName": row["task_name"],
            "taskMode": row["task_mode"],
            "triggerType": row["trigger_type"],
            "status": row["status"],
            "config": _json_loads(row["config_json"], {}),
            "workerPid": row["worker_pid"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "heartbeatAt": row["heartbeat_at"],
            "errorMessage": row["error_message"] or "",
        }

    def list_recent_batches(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    batch_id, producer_task, entity_type, run_id, data_as_of,
                    generated_at, row_count, summary_json, stale
                FROM data_batches
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "batchId": row["batch_id"],
                "producerTask": row["producer_task"],
                "entityType": row["entity_type"],
                "runId": row["run_id"],
                "dataAsOf": row["data_as_of"],
                "generatedAt": row["generated_at"],
                "rowCount": int(row["row_count"] or 0),
                "summary": _json_loads(row["summary_json"], {}),
                "stale": bool(row["stale"]),
                "inputs": self.list_batch_inputs(row["batch_id"]),
            }
            for row in rows
        ]

    def list_batches_by_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    batch_id, producer_task, entity_type, run_id, data_as_of,
                    generated_at, row_count, summary_json, stale
                FROM data_batches
                WHERE run_id = ?
                ORDER BY generated_at DESC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "batchId": row["batch_id"],
                "producerTask": row["producer_task"],
                "entityType": row["entity_type"],
                "runId": row["run_id"],
                "dataAsOf": row["data_as_of"],
                "generatedAt": row["generated_at"],
                "rowCount": int(row["row_count"] or 0),
                "summary": _json_loads(row["summary_json"], {}),
                "stale": bool(row["stale"]),
                "inputs": self.list_batch_inputs(row["batch_id"]),
            }
            for row in rows
        ]

    def bootstrap_views_from_existing_data(self) -> None:
        with self.connect() as connection:
            existing = connection.execute("SELECT COUNT(*) AS count FROM published_views").fetchone()
            if existing and int(existing["count"]) > 0:
                return
        self._bootstrap_factor_view()
        self._bootstrap_market_view()
        self._bootstrap_news_view()
        self._bootstrap_model_view()
        self._bootstrap_ai_view()

    def _bootstrap_factor_view(self) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count, MAX(date) AS max_date FROM factor_rows"
            ).fetchone()
        if not row or int(row["count"] or 0) <= 0:
            return
        batch_id = self.create_batch(
            producer_task="bootstrap_factor_worker",
            entity_type="factor_dataset",
            run_id=None,
            data_as_of=row["max_date"],
            row_count=int(row["count"]),
            summary={"source": "legacy_tables"},
        )
        self.publish_view("latest_factors", batch_id)

    def _bootstrap_market_view(self) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count, MAX(source_updated_at) AS updated_at FROM market_bars"
            ).fetchone()
        if not row or int(row["count"] or 0) <= 0:
            return
        batch_id = self.create_batch(
            producer_task="bootstrap_price_snapshot_worker",
            entity_type="price_snapshot",
            run_id=None,
            data_as_of=row["updated_at"],
            row_count=int(row["count"]),
            summary={"source": "legacy_tables"},
        )
        self.publish_view("latest_prices", batch_id)

    def _bootstrap_news_view(self) -> None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS count,
                    MAX(COALESCE(published_at, ingested_at)) AS published_at
                FROM news_articles
                """
            ).fetchone()
        if not row or int(row["count"] or 0) <= 0:
            return
        batch_id = self.create_batch(
            producer_task="bootstrap_news_worker",
            entity_type="news_dataset",
            run_id=None,
            data_as_of=row["published_at"],
            row_count=int(row["count"]),
            summary={"source": "legacy_tables"},
        )
        self.publish_view("latest_news", batch_id)

    def _bootstrap_model_view(self) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT run_id, as_of FROM model_outputs WHERE output_key = 'prediction_summary'"
            ).fetchone()
        if not row:
            return
        batch_id = self.create_batch(
            producer_task="bootstrap_model_worker",
            entity_type="model_dataset",
            run_id=row["run_id"],
            data_as_of=row["as_of"],
            row_count=1,
            summary={"source": "legacy_tables", "runId": row["run_id"]},
        )
        factor_view = self.get_published_view("latest_factors")
        if factor_view:
            self.set_batch_inputs(batch_id, {"factor_batch": factor_view["batchId"]})
        self.publish_view("latest_model", batch_id)

    def _bootstrap_ai_view(self) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT run_id, as_of FROM model_outputs WHERE output_key = 'prediction_ai_analysis'"
            ).fetchone()
        if not row:
            return
        batch_id = self.create_batch(
            producer_task="bootstrap_ai_analysis_worker",
            entity_type="ai_dataset",
            run_id=row["run_id"],
            data_as_of=row["as_of"],
            row_count=2,
            summary={"source": "legacy_tables", "runId": row["run_id"]},
        )
        model_view = self.get_published_view("latest_model")
        if model_view:
            self.set_batch_inputs(batch_id, {"model_batch": model_view["batchId"]})
        self.publish_view("latest_ai_report", batch_id)
