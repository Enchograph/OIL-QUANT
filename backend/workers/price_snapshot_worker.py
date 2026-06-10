from __future__ import annotations

import argparse
import os

from ..core_backend import create_backend_service
from .common import (
    TASK_VIEW_KEYS,
    bootstrap_runtime,
    build_success_payload,
    get_database,
    log_task_event,
    mark_source_failure,
    mark_source_success,
    print_payload,
    run_daemon,
)


def run_once(
    trigger_type: str = "manual",
    interval_seconds: int = 60,
    full_minute_history: bool = False,
) -> dict:
    runtime_store = bootstrap_runtime()
    database = get_database()
    service = create_backend_service(database)
    run_id = runtime_store.start_task_run(
        task_name="price_snapshot_worker",
        task_mode="oneshot",
        trigger_type=trigger_type,
        config={
            "intervalSeconds": interval_seconds,
            "fullMinuteHistory": full_minute_history,
        },
        worker_pid=os.getpid(),
    )
    log_task_event(
        "price_snapshot_worker",
        "oneshot_started",
        runId=run_id,
        triggerType=trigger_type,
        intervalSeconds=interval_seconds,
        fullMinuteHistory=full_minute_history,
    )
    try:
        result = service.sync_market(full_minute_history=full_minute_history)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count, MAX(source_updated_at) AS updated_at FROM market_bars"
            ).fetchone()
        batch_id = runtime_store.create_batch(
            producer_task="price_snapshot_worker",
            entity_type="price_snapshot",
            run_id=run_id,
            data_as_of=row["updated_at"],
            row_count=int(row["count"] or 0),
            summary=result.details,
        )
        runtime_store.publish_view(TASK_VIEW_KEYS["price_snapshot_worker"], batch_id)
        mark_source_success(database, "market", batch_id, row["updated_at"], run_id, result.details)
        runtime_store.finish_task_run(run_id, "success")
        log_task_event(
            "price_snapshot_worker",
            "oneshot_succeeded",
            runId=run_id,
            batchId=batch_id,
            dataAsOf=row["updated_at"],
            rowCount=int(row["count"] or 0),
            fullMinuteHistory=full_minute_history,
        )
        return build_success_payload(
            "price_snapshot_worker",
            run_id,
            batch_id,
            {
                "dataAsOf": row["updated_at"],
                "rowCount": int(row["count"] or 0),
                "fullMinuteHistory": full_minute_history,
            },
        )
    except Exception as error:
        mark_source_failure(database, runtime_store, "price_snapshot_worker", run_id, error)
        runtime_store.finish_task_run(run_id, "failed", str(error))
        log_task_event("price_snapshot_worker", "oneshot_failed", runId=run_id, error=str(error))
        raise


def _daemon_iteration(run_id, runtime_store, database, full_minute_history: bool = False) -> None:
    service = create_backend_service(database)
    result = service.sync_market(full_minute_history=full_minute_history)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count, MAX(source_updated_at) AS updated_at FROM market_bars"
        ).fetchone()
    batch_id = runtime_store.create_batch(
        producer_task="price_snapshot_worker",
        entity_type="price_snapshot",
        run_id=run_id,
        data_as_of=row["updated_at"],
        row_count=int(row["count"] or 0),
        summary=result.details,
    )
    runtime_store.publish_view(TASK_VIEW_KEYS["price_snapshot_worker"], batch_id)
    mark_source_success(database, "market", batch_id, row["updated_at"], run_id, result.details)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--trigger", default="supervisor")
    parser.add_argument("--full-minute-history", action="store_true")
    args = parser.parse_args()
    if args.once:
        print_payload(
            run_once(
                trigger_type=args.trigger,
                interval_seconds=args.interval,
                full_minute_history=args.full_minute_history,
            )
        )
        return
    run_daemon(
        "price_snapshot_worker",
        args.interval,
        _daemon_iteration,
        trigger_type=args.trigger,
        full_minute_history=args.full_minute_history,
    )


if __name__ == "__main__":
    main()
