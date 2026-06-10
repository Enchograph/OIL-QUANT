from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

try:
    from .core_backend import DB_PATH, Database
    from .news_pipeline import NEWS_SOURCE_NAME, OilPriceNewsPipeline, standardize_published_at
except ImportError:
    from core_backend import DB_PATH, Database
    from news_pipeline import NEWS_SOURCE_NAME, OilPriceNewsPipeline, standardize_published_at


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_progress(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


@dataclass
class CandidateArticle:
    article_id: str
    url: str
    title: str
    published_at: str | None


@dataclass
class RepairResult:
    article_id: str
    url: str
    title: str
    old_published_at: str | None
    new_published_at: str | None
    changed: bool
    error: str | None = None


def load_candidates(
    db_path: Path,
    *,
    article_id: str | None,
    limit: int | None,
    include_healthy: bool,
) -> list[CandidateArticle]:
    database = Database(db_path)
    database.init()

    conditions = ["source = ?"]
    params: list[Any] = [NEWS_SOURCE_NAME]

    if article_id:
        conditions.append("id = ?")
        params.append(article_id)
    elif not include_healthy:
        conditions.append(
            "("
            "published_at IS NULL OR published_at = '' OR "
            "(published_at NOT LIKE '%+__:__' AND published_at NOT LIKE '%Z')"
            ")"
        )

    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT id, url, title, published_at
        FROM news_articles
        WHERE {where_clause}
        ORDER BY COALESCE(published_at, ingested_at) DESC, id DESC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    with database.connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    return [
        CandidateArticle(
            article_id=str(row["id"]),
            url=str(row["url"]),
            title=str(row["title"]),
            published_at=str(row["published_at"]) if row["published_at"] else None,
        )
        for row in rows
    ]


def fetch_and_extract_published_at(article: CandidateArticle, timeout_seconds: int) -> RepairResult:
    pipeline = OilPriceNewsPipeline()
    try:
        html = pipeline.fetch_text(article.url, timeout_seconds=timeout_seconds)
        soup = BeautifulSoup(html, "html.parser")
        extracted = pipeline._extract_published_at(soup)
        normalized = standardize_published_at(extracted)
        changed = normalized is not None and normalized != article.published_at
        return RepairResult(
            article_id=article.article_id,
            url=article.url,
            title=article.title,
            old_published_at=article.published_at,
            new_published_at=normalized,
            changed=changed,
        )
    except Exception as error:
        return RepairResult(
            article_id=article.article_id,
            url=article.url,
            title=article.title,
            old_published_at=article.published_at,
            new_published_at=None,
            changed=False,
            error=str(error),
        )


def apply_repairs(db_path: Path, repairs: list[RepairResult]) -> int:
    updates = [(item.new_published_at, utc_now_iso(), item.article_id) for item in repairs if item.changed and item.new_published_at]
    if not updates:
        return 0

    database = Database(db_path)
    database.init()
    with database.connect() as connection:
        connection.executemany(
            """
            UPDATE news_articles
            SET published_at = ?, updated_at = ?
            WHERE id = ?
            """,
            updates,
        )
    return len(updates)


def main() -> None:
    parser = argparse.ArgumentParser(description="回源抓取 OilPrice 原文并修复历史新闻发布时间")
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--article-id", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--include-healthy", action="store_true", default=False)
    args = parser.parse_args()

    candidates = load_candidates(
        args.db_path,
        article_id=args.article_id,
        limit=args.limit,
        include_healthy=args.include_healthy,
    )
    if not candidates:
        log_progress("没有找到待处理新闻。")
        return

    log_progress(
        f"开始扫描 {len(candidates)} 篇新闻，workers={max(1, args.workers)}，mode={'apply' if args.apply else 'dry-run'}"
    )

    repairs: list[RepairResult] = []
    changed_count = 0
    error_count = 0
    unchanged_count = 0

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(fetch_and_extract_published_at, article, max(1, args.timeout)): article
            for article in candidates
        }
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            repairs.append(result)
            if result.error:
                error_count += 1
                log_progress(f"[{index}/{len(candidates)}] 失败 {result.article_id} {result.url} error={result.error}")
                continue
            if result.changed:
                changed_count += 1
                log_progress(
                    f"[{index}/{len(candidates)}] 待修复 {result.article_id} {result.old_published_at} -> {result.new_published_at}"
                )
            else:
                unchanged_count += 1
                log_progress(f"[{index}/{len(candidates)}] 无变化 {result.article_id} {result.old_published_at}")

    applied_count = apply_repairs(args.db_path, repairs) if args.apply else 0
    print(
        {
            "mode": "apply" if args.apply else "dry-run",
            "scanned": len(candidates),
            "changed": changed_count,
            "unchanged": unchanged_count,
            "failed": error_count,
            "applied": applied_count,
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
