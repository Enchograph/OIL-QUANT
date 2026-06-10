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
    factor_view = runtime_store.get_published_view("latest_factors")
    if not factor_view:
        raise RuntimeError("缺少可用因子批次，无法运行模型任务")
    run_id = runtime_store.start_task_run(
        task_name="model_worker",
        task_mode="oneshot",
        trigger_type=trigger_type,
        config={"factorBatchId": factor_view["batchId"]},
        worker_pid=os.getpid(),
    )
    log_task_event(
        "model_worker",
        "oneshot_started",
        runId=run_id,
        triggerType=trigger_type,
        inputFactorBatchId=factor_view["batchId"],
    )
    try:
        result = service.run_model(trigger_source=trigger_type, include_ai=False)
        batch_id = runtime_store.create_batch(
            producer_task="model_worker",
            entity_type="model_dataset",
            run_id=run_id,
            data_as_of=result.details.get("factor_as_of"),
            row_count=1,
            summary=result.details,
        )
        runtime_store.set_batch_inputs(batch_id, {"factor_batch": factor_view["batchId"]})
        runtime_store.publish_view(TASK_VIEW_KEYS["model_worker"], batch_id)
        mark_source_success(
            database,
            "model",
            batch_id,
            result.details.get("factor_as_of"),
            run_id,
            result.details,
        )
        runtime_store.finish_task_run(run_id, "success")
        log_task_event(
            "model_worker",
            "oneshot_succeeded",
            runId=run_id,
            batchId=batch_id,
            dataAsOf=result.details.get("factor_as_of"),
            inputFactorBatchId=factor_view["batchId"],
        )
        return build_success_payload(
            "model_worker",
            run_id,
            batch_id,
            {"dataAsOf": result.details.get("factor_as_of"), "inputFactorBatchId": factor_view["batchId"]},
        )
    except Exception as error:
        mark_source_failure(database, runtime_store, "model_worker", run_id, error)
        runtime_store.finish_task_run(run_id, "failed", str(error))
        log_task_event("model_worker", "oneshot_failed", runId=run_id, error=str(error))
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="supervisor")
    args = parser.parse_args()
    print_payload(run_once(trigger_type=args.trigger))


if __name__ == "__main__":
    main()
