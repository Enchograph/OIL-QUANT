from __future__ import annotations

import argparse
import os
from datetime import datetime

from .core_backend import create_backend_service, create_database


def log_progress(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="执行历史新闻导入、增量补抓或新闻重分析")
    parser.add_argument("--mode", choices=["import", "reanalyze", "sync"], default="import")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    parser.add_argument("--executor", choices=["auto", "process", "thread"], default="auto")
    parser.add_argument("--page-limit", type=int, default=None)
    parser.add_argument("--article-limit", type=int, default=None)
    parser.add_argument("--catch-up", action="store_true", default=False)
    parser.add_argument("--stale-page-limit", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true", default=False)
    args = parser.parse_args()

    database = create_database()
    service = create_backend_service(database)

    if args.mode == "import":
        result = service.import_historical_news(
            batch_size=max(1, args.batch_size),
            limit=args.limit,
            resume=args.resume,
            workers=max(1, args.workers),
            executor_kind=args.executor,
            progress_callback=log_progress,
        )
    elif args.mode == "sync":
        result = service.sync_news(
            catch_up=args.catch_up,
            sync_mode="catch_up" if args.catch_up else "recent_pages",
            page_limit=args.page_limit,
            article_limit=args.article_limit,
            stale_page_limit=max(1, args.stale_page_limit),
            workers=max(1, args.workers),
            progress_callback=log_progress,
        )
    else:
        result = service.reanalyze_news(
            batch_size=max(1, args.batch_size),
            limit=args.limit,
            progress_callback=log_progress,
        )

    print(result, flush=True)


if __name__ == "__main__":
    main()
