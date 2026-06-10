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


def run_once(trigger_type: str = "manual", interval_seconds: int = 60) -> dict:
    runtime_store = bootstrap_runtime()
    database = get_database()
    service = create_backend_service(database)
    run_id = runtime_store.start_task_run(
        task_name="news_worker",
        task_mode="oneshot",
        trigger_type=trigger_type,
        config={
            "intervalSeconds": interval_seconds,
            "syncMode": "recent_pages",
            "pageLimit": max(1, int(os.getenv("NEWS_SYNC_PAGE_LIMIT", "2"))),
            "workers": max(1, int(os.getenv("NEWS_SYNC_WORKERS", "1"))),
        },
        worker_pid=os.getpid(),
    )
    log_task_event(
        "news_worker",
        "oneshot_started",
        runId=run_id,
        triggerType=trigger_type,
        intervalSeconds=interval_seconds,
    )
    try:
        page_limit_raw = os.getenv("NEWS_SYNC_PAGE_LIMIT", "").strip()
        page_limit = int(page_limit_raw) if page_limit_raw else None
        workers = max(1, int(os.getenv("NEWS_SYNC_WORKERS", "1")))
        result = service.sync_news(sync_mode="recent_pages", page_limit=page_limit or 2, workers=workers)
        article_count = database.count_news_articles()
        data_as_of = database.get_latest_news_published_at()
        batch_id = runtime_store.create_batch(
            producer_task="news_worker",
            entity_type="news_dataset",
            run_id=run_id,
            data_as_of=data_as_of,
            row_count=article_count,
            summary=result.details,
        )
        runtime_store.publish_view(TASK_VIEW_KEYS["news_worker"], batch_id)
        mark_source_success(database, "news", batch_id, data_as_of, run_id, result.details)
        runtime_store.finish_task_run(run_id, "success")
        log_task_event(
            "news_worker",
            "oneshot_succeeded",
            runId=run_id,
            batchId=batch_id,
            dataAsOf=data_as_of,
            rowCount=article_count,
        )
        return build_success_payload(
            "news_worker",
            run_id,
            batch_id,
            {"dataAsOf": data_as_of, "rowCount": article_count},
        )
    except Exception as error:
        mark_source_failure(database, runtime_store, "news_worker", run_id, error)
        runtime_store.finish_task_run(run_id, "failed", str(error))
        log_task_event("news_worker", "oneshot_failed", runId=run_id, error=str(error))
        raise


def _daemon_iteration(run_id, runtime_store, database) -> None:
    service = create_backend_service(database)
    page_limit_raw = os.getenv("NEWS_SYNC_PAGE_LIMIT", "").strip()
    page_limit = int(page_limit_raw) if page_limit_raw else None
    workers = max(1, int(os.getenv("NEWS_SYNC_WORKERS", "1")))
    result = service.sync_news(sync_mode="recent_pages", page_limit=page_limit or 2, workers=workers)
    article_count = database.count_news_articles()
    data_as_of = database.get_latest_news_published_at()
    batch_id = runtime_store.create_batch(
        producer_task="news_worker",
        entity_type="news_dataset",
        run_id=run_id,
        data_as_of=data_as_of,
        row_count=article_count,
        summary=result.details,
    )
    runtime_store.publish_view(TASK_VIEW_KEYS["news_worker"], batch_id)
    mark_source_success(database, "news", batch_id, data_as_of, run_id, result.details)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--trigger", default="supervisor")
    args = parser.parse_args()
    if args.once:
        print_payload(run_once(trigger_type=args.trigger, interval_seconds=args.interval))
        return
    run_daemon("news_worker", args.interval, _daemon_iteration, trigger_type=args.trigger)


if __name__ == "__main__":
    main()
