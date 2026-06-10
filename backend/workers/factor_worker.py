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
)


def run_once(trigger_type: str = "manual") -> dict:
    runtime_store = bootstrap_runtime()
    database = get_database()
    service = create_backend_service(database)
    run_id = runtime_store.start_task_run(
        task_name="factor_worker",
        task_mode="oneshot",
        trigger_type=trigger_type,
        config={},
        worker_pid=os.getpid(),
    )
    log_task_event("factor_worker", "oneshot_started", runId=run_id, triggerType=trigger_type)
    try:
        result = service.sync_factors()
        with database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count, MAX(date) AS max_date FROM factor_rows"
            ).fetchone()
        batch_id = runtime_store.create_batch(
            producer_task="factor_worker",
            entity_type="factor_dataset",
            run_id=run_id,
            data_as_of=row["max_date"],
            row_count=int(row["count"] or 0),
            summary=result.details,
        )
        runtime_store.publish_view(TASK_VIEW_KEYS["factor_worker"], batch_id)
        mark_source_success(database, "factors", batch_id, row["max_date"], run_id, result.details)
        runtime_store.finish_task_run(run_id, "success")
        log_task_event(
            "factor_worker",
            "oneshot_succeeded",
            runId=run_id,
            batchId=batch_id,
            dataAsOf=row["max_date"],
            rowCount=int(row["count"] or 0),
        )
        return build_success_payload(
            "factor_worker",
            run_id,
            batch_id,
            {"dataAsOf": row["max_date"], "rowCount": int(row["count"] or 0)},
        )
    except Exception as error:
        mark_source_failure(database, runtime_store, "factor_worker", run_id, error)
        runtime_store.finish_task_run(run_id, "failed", str(error))
        log_task_event("factor_worker", "oneshot_failed", runId=run_id, error=str(error))
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="supervisor")
    args = parser.parse_args()
    print_payload(run_once(trigger_type=args.trigger))


if __name__ == "__main__":
    main()
