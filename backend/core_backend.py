from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / ".vendor"

if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import pandas as pd

try:
    from .factor_update import FactorUpdatePipeline, expected_factor_latest_date, normalize_factor_frame
    from .market_data import (
        MARKET_SERIES_DEFINITIONS,
        MARKET_SERIES_IDS,
        build_market_data_provider,
        get_market_series_definition,
        resolve_provider_symbol,
    )
    from .news_pipeline import (
        ANALYZER_VERSION,
        NEWS_SOURCE_KEY,
        OilPriceNewsPipeline,
        parse_flexible_datetime,
        standardize_published_at,
    )
    from .ai_advisory import create_pipeline, normalize_prediction_payload
except ImportError:
    from factor_update import FactorUpdatePipeline, expected_factor_latest_date, normalize_factor_frame
    from market_data import (
        MARKET_SERIES_DEFINITIONS,
        MARKET_SERIES_IDS,
        build_market_data_provider,
        get_market_series_definition,
        resolve_provider_symbol,
    )
    from news_pipeline import (
        ANALYZER_VERSION,
        NEWS_SOURCE_KEY,
        OilPriceNewsPipeline,
        parse_flexible_datetime,
        standardize_published_at,
    )
    from ai_advisory import create_pipeline, normalize_prediction_payload

ROOT_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
GENERATED_DIR = DATA_DIR / "generated"
FACTOR_DIR = DATA_DIR / "factors"
NEWS_DIR = DATA_DIR / "news"
DB_PATH = DATA_DIR / "platform.sqlite3"
SOURCE_FACTORS_CSV = ROOT_DIR / "modules" / "core_model" / "factors_WTI_cleaned_v2.csv"
WORKING_FACTORS_CSV = FACTOR_DIR / "factors_WTI_cleaned_v2.csv"
MODEL_SOURCE_DIR = ROOT_DIR / "modules" / "price_prediction"
HISTORICAL_NEWS_DIR = ROOT_DIR / "modules" / "news_scraping" / "scraper" / "OilPrice_Project" / "Articles_FullText"
HISTORICAL_NEWS_SUMMARY_CSV = ROOT_DIR / "modules" / "news_scraping" / "scraper" / "OilPrice_Project" / "news_summary.csv"

RANGE_TO_GRANULARITY = {
    "1D": "1m",
    "1W": "1m",
    "1M": "1m",
    "3M": "1d",
    "1Y": "1d",
}

DISPLAY_GRANULARITY_TO_SOURCE = {}

DISPLAY_GRANULARITY_MINUTES = {}

RAW_GRANULARITY_MINUTES = {
    "1m": 1,
    "1d": 24 * 60,
}

PREVIEW_SUMMARY_MAX_LENGTH = 160
FORECAST_PRICE_COL = "WTI_Close"
PREVIEW_TITLE_LIKE_PATTERNS = (
    re.compile(r"^\s{0,3}#{1,6}\s*"),
    re.compile(r"^\s*[\*\-_=`#>\s]+\s*$"),
    re.compile(r"^\s*(石油市场.*报告|.*分析报告|.*建议报告)(\s*\|.*)?\s*$"),
)


def _normalize_preview_text(value: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~`]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_title_like_preview_line(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if any(pattern.match(stripped) for pattern in PREVIEW_TITLE_LIKE_PATTERNS):
        return True
    if len(stripped) <= 28 and not re.search(r"[。；，,.!?！？]", stripped):
        return True
    return False


def build_ai_preview_summary(body: str, fallback: str = "") -> str:
    raw_segments = re.split(r"\n\s*\n|\r\n\s*\r\n", body or "")
    candidates: list[str] = []
    for segment in raw_segments:
        for line in segment.splitlines():
            normalized = _normalize_preview_text(line)
            if not normalized or _is_title_like_preview_line(normalized):
                continue
            candidates.append(normalized)

    if not candidates:
        fallback_text = _normalize_preview_text(fallback)
        return fallback_text[:PREVIEW_SUMMARY_MAX_LENGTH].strip(" ,;，；")

    summary_parts: list[str] = []
    total_length = 0
    for item in candidates:
        summary_parts.append(item)
        total_length += len(item)
        if total_length >= 90 or len(summary_parts) >= 2:
            break

    summary = " ".join(summary_parts)
    summary = re.sub(r"\s+", " ", summary).strip(" ,;，；")
    if len(summary) > PREVIEW_SUMMARY_MAX_LENGTH:
        summary = summary[:PREVIEW_SUMMARY_MAX_LENGTH].rstrip(" ,;，；")
    return summary


def _apply_quantile_prediction_guardrails(model_module):
    if getattr(model_module, "_quantile_guardrails_applied", False):
        return model_module
    original_predictor = getattr(model_module, "train_quantile_forward_predict", None)
    if original_predictor is None:
        return model_module

    def guarded_predictor(X_train, y_train, X_test, quantiles=None, alpha=None):
        kwargs = {}
        if quantiles is not None:
            kwargs["quantiles"] = quantiles
        if alpha is not None:
            kwargs["alpha"] = alpha
        q10, q50, q90 = original_predictor(X_train, y_train, X_test, **kwargs)

        train_target = pd.to_numeric(pd.Series(y_train), errors="coerce").dropna()
        if len(train_target) < 40:
            return q10, q50, q90

        lower_bound = max(float(train_target.quantile(0.01)), -0.95)
        upper_bound = min(float(train_target.quantile(0.99)), 3.0)
        if lower_bound > upper_bound:
            lower_bound, upper_bound = upper_bound, lower_bound

        low = pd.Series(q10, dtype="float64").clip(lower=lower_bound, upper=upper_bound)
        mid = pd.Series(q50, dtype="float64").clip(lower=lower_bound, upper=upper_bound)
        high = pd.Series(q90, dtype="float64").clip(lower=lower_bound, upper=upper_bound)
        band = pd.concat([low, mid, high], axis=1)
        floor = band.min(axis=1)
        ceil = band.max(axis=1)
        center = mid.clip(lower=floor, upper=ceil)
        return floor.to_numpy(), center.to_numpy(), ceil.to_numpy()

    model_module.train_quantile_forward_predict = guarded_predictor
    model_module._quantile_guardrails_applied = True
    return model_module


def _normalize_model_return_targets(
    frame: pd.DataFrame,
    primary_target: str,
    targets: list[str],
    regression_target_col: str,
    horizon: int,
) -> pd.DataFrame:
    normalized = frame.copy()
    target_series = pd.to_numeric(normalized.get(primary_target), errors="coerce")
    if target_series.dropna().abs().quantile(0.95) <= 1.0:
        return normalized

    for column in targets:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce") / 100.0

    primary_series = pd.to_numeric(normalized[primary_target], errors="coerce")
    fc = [math.nan] * len(primary_series)
    for index in range(len(primary_series) - horizon + 1):
        window = primary_series.iloc[index : index + horizon]
        if window.isna().any():
            continue
        fc[index] = float((1.0 + window).prod() - 1.0)
    normalized[regression_target_col] = fc
    return normalized

RANGE_TO_LIMIT = {
    "1D": 24 * 60,
    "1W": 7 * 24 * 12,
    "1M": 30 * 24,
    "3M": 92,
    "1Y": 366,
}

MARKET_STORAGE_LIMIT = {
    "1m": 30 * 24 * 60,
    "1d": RANGE_TO_LIMIT["1Y"],
}

FULL_MINUTE_HISTORY_DAYS = 30
FULL_MINUTE_HISTORY_LIMIT = FULL_MINUTE_HISTORY_DAYS * 24 * 60

RAW_MARKET_RETENTION_DAYS = {
    "1m": 30,
}

RAW_MARKET_RETENTION_LIMITS = {
    "1m": RAW_MARKET_RETENTION_DAYS["1m"] * 24 * 60,
    "1d": 366,
}

MAIN_CHART_TARGET_POINTS = max(120, int(os.getenv("MAIN_CHART_TARGET_POINTS", "960")))
MAIN_CHART_MIN_TARGET_POINTS = max(120, int(os.getenv("MAIN_CHART_MIN_TARGET_POINTS", "240")))
MAIN_CHART_WIDTH_POINT_RATIO = max(0.1, float(os.getenv("MAIN_CHART_WIDTH_POINT_RATIO", "0.5")))

MARKET_CHART_QUERY_PROFILES = {
    "main": {
        "1D": {"layer": "raw", "granularity": "1m", "limit": 24 * 60, "fallback_granularity": "1m"},
        "1W": {"layer": "raw", "granularity": "1m", "limit": 7 * 24 * 60, "fallback_granularity": "1m"},
        "1M": {"layer": "raw", "granularity": "1m", "limit": 30 * 24 * 60, "fallback_granularity": "1m"},
        "3M": {"layer": "raw", "granularity": "1d", "limit": 92, "fallback_granularity": "1d"},
        "1Y": {"layer": "raw", "granularity": "1d", "limit": 366, "fallback_granularity": "1d"},
    },
    "sparkline": {
        "1D": {"layer": "raw", "granularity": "1m", "limit": 24 * 60, "fallback_granularity": "1m"},
        "1W": {"layer": "raw", "granularity": "1m", "limit": 7 * 24 * 60, "fallback_granularity": "1m"},
        "1M": {"layer": "raw", "granularity": "1m", "limit": 30 * 24 * 60, "fallback_granularity": "1m"},
        "3M": {"layer": "raw", "granularity": "1d", "limit": 92, "fallback_granularity": "1d"},
        "1Y": {"layer": "raw", "granularity": "1d", "limit": 366, "fallback_granularity": "1d"},
    },
}

MARKET_SYMBOLS = {series_id: series_id for series_id in MARKET_SERIES_IDS}

FACTOR_COLUMNS = [
    "Date",
    "Price",
    "WTI_Open",
    "WTI_High",
    "WTI_Low",
    "WTI_Close",
    "WTI_Return_1d",
    "WTI_Volatility_20d",
    "VIX_Price",
    "DXY_Price",
    "OPEC_supply",
    "US_stock_strategy",
    "conflict_intensity_mean",
    "GPR",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def resolve_timezone(timezone_name: str | None = None) -> ZoneInfo:
    candidate = str(timezone_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(candidate)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"无效时区: {candidate}") from error


def to_timezone_date_key(value: str | None, timezone_name: str | None = None) -> str | None:
    parsed = parse_flexible_datetime(value)
    if parsed is None or parsed.year < 2000:
        return None
    return parsed.astimezone(resolve_timezone(timezone_name)).date().isoformat()


def resolve_date_range_utc_bounds(
    start: str | None = None,
    end: str | None = None,
    timezone_name: str | None = None,
) -> tuple[str | None, str | None]:
    timezone_info = resolve_timezone(timezone_name)
    start_bound = None
    end_bound = None

    if start:
        start_local = datetime.fromisoformat(f"{start}T00:00:00").replace(tzinfo=timezone_info)
        start_bound = start_local.astimezone(timezone.utc).isoformat()

    if end:
        end_local = datetime.fromisoformat(f"{end}T00:00:00").replace(tzinfo=timezone_info) + timedelta(days=1)
        end_bound = end_local.astimezone(timezone.utc).isoformat()

    return start_bound, end_bound


def resolve_effective_published_at(
    published_at: str | None,
    ingested_at: str | None,
) -> str | None:
    normalized_published_at = standardize_published_at(published_at)
    if normalized_published_at:
        return normalized_published_at
    normalized_ingested_at = standardize_published_at(ingested_at)
    return normalized_ingested_at or None


def ensure_dirs() -> None:
    for directory in (DATA_DIR, GENERATED_DIR, FACTOR_DIR, NEWS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def resolve_market_chart_profile(range_key: str, chart_kind: str = "main") -> dict[str, Any]:
    normalized_kind = str(chart_kind or "main").strip().lower() or "main"
    profiles = MARKET_CHART_QUERY_PROFILES.get(normalized_kind)
    if not profiles:
        raise ValueError(f"不支持的 chart kind: {chart_kind}")
    profile = profiles.get(range_key)
    if not profile:
        raise ValueError(f"不支持的 range: {range_key}")
    return dict(profile)


def resolve_main_chart_target_points(viewport_width: int | None = None) -> int:
    if viewport_width is None:
        return MAIN_CHART_TARGET_POINTS
    if viewport_width <= 0:
        return MAIN_CHART_TARGET_POINTS
    width_budget_points = int(round(viewport_width * MAIN_CHART_WIDTH_POINT_RATIO))
    return max(MAIN_CHART_MIN_TARGET_POINTS, min(MAIN_CHART_TARGET_POINTS, width_budget_points))


def bucket_market_observed_at(observed_at: str, target_granularity: str) -> str:
    timestamp = pd.Timestamp(observed_at).tz_convert("UTC")
    if target_granularity == "1w":
        bucket = timestamp.normalize() - pd.Timedelta(days=timestamp.weekday())
        return bucket.isoformat()
    bucket_minutes = DISPLAY_GRANULARITY_MINUTES[target_granularity]
    total_minutes = int(timestamp.timestamp() // 60)
    bucket_total_minutes = (total_minutes // bucket_minutes) * bucket_minutes
    bucket = pd.Timestamp(bucket_total_minutes * 60, unit="s", tz="UTC")
    return bucket.isoformat()


def aggregate_market_bars(
    bars: list[dict[str, Any]],
    target_granularity: str,
) -> list[dict[str, Any]]:
    if not bars:
        return []
    aggregated: dict[str, dict[str, Any]] = {}
    ordered_rows = sorted(bars, key=lambda item: item["observed_at"])
    for bar in ordered_rows:
        bucket_key = bucket_market_observed_at(str(bar["observed_at"]), target_granularity)
        open_value = float(bar["open"])
        high_value = float(bar["high"])
        low_value = float(bar["low"])
        close_value = float(bar["close"])
        if bucket_key not in aggregated:
            aggregated[bucket_key] = {
                "observed_at": bucket_key,
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "source_updated_at": str(bar.get("source_updated_at") or ""),
            }
            continue
        bucket = aggregated[bucket_key]
        bucket["high"] = max(float(bucket["high"]), high_value)
        bucket["low"] = min(float(bucket["low"]), low_value)
        bucket["close"] = close_value
        if bar.get("source_updated_at"):
            bucket["source_updated_at"] = str(bar["source_updated_at"])
    return list(aggregated.values())


def downsample_market_bars_by_time(
    bars: list[dict[str, Any]],
    target_points: int,
) -> list[dict[str, Any]]:
    if not bars or target_points <= 0 or len(bars) <= target_points:
        return bars

    ordered_rows = sorted(bars, key=lambda item: item["observed_at"])
    if len(ordered_rows) <= 1:
        return ordered_rows

    start_ts = pd.Timestamp(ordered_rows[0]["observed_at"]).timestamp()
    end_ts = pd.Timestamp(ordered_rows[-1]["observed_at"]).timestamp()
    total_span_seconds = max(end_ts - start_ts, 1.0)
    bucket_span_seconds = max(total_span_seconds / target_points, 1.0)

    buckets: list[list[dict[str, Any]]] = []
    current_bucket: list[dict[str, Any]] = []
    current_bucket_index = 0

    for bar in ordered_rows:
        bar_ts = pd.Timestamp(bar["observed_at"]).timestamp()
        bucket_index = min(int((bar_ts - start_ts) / bucket_span_seconds), target_points - 1)
        if bucket_index != current_bucket_index and current_bucket:
            buckets.append(current_bucket)
            current_bucket = []
            current_bucket_index = bucket_index
        current_bucket.append(bar)

    if current_bucket:
        buckets.append(current_bucket)

    downsampled: list[dict[str, Any]] = []
    for bucket in buckets:
        first = bucket[0]
        last = bucket[-1]
        downsampled.append(
            {
                "observed_at": first["observed_at"],
                "open": float(first["open"]),
                "high": max(float(item["high"]) for item in bucket),
                "low": min(float(item["low"]) for item in bucket),
                "close": float(last["close"]),
                "source_updated_at": str(last.get("source_updated_at") or first.get("source_updated_at") or ""),
            }
        )
    return downsampled


def resolve_display_source_limit(profile: dict[str, Any]) -> int:
    source_granularity = profile["fallback_granularity"]
    target_granularity = profile["granularity"]
    source_minutes = RAW_GRANULARITY_MINUTES[source_granularity]
    target_minutes = DISPLAY_GRANULARITY_MINUTES[target_granularity]
    required_points = int(profile["limit"]) * max(target_minutes // source_minutes, 1)
    return min(RAW_MARKET_RETENTION_LIMITS[source_granularity], required_points)


def sanitize_json_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: sanitize_json_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [sanitize_json_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [sanitize_json_payload(item) for item in payload]
    if isinstance(payload, float):
        if math.isnan(payload) or math.isinf(payload):
            return None
        return payload
    return payload


def json_dumps(payload: Any) -> str:
    return json.dumps(sanitize_json_payload(payload), ensure_ascii=False, allow_nan=False)


def json_loads(payload: str | None, default: Any = None) -> Any:
    if not payload:
        return default
    return sanitize_json_payload(json.loads(payload))


@dataclass
class JobResult:
    source: str
    success: bool
    updated_at: str
    details: dict[str, Any]


_HISTORICAL_IMPORT_PIPELINE = None
_HISTORICAL_IMPORT_SUMMARY_INDEX = None


def _historical_import_worker_init(summary_csv_path: str) -> None:
    global _HISTORICAL_IMPORT_PIPELINE, _HISTORICAL_IMPORT_SUMMARY_INDEX
    _HISTORICAL_IMPORT_PIPELINE = OilPriceNewsPipeline()
    _HISTORICAL_IMPORT_SUMMARY_INDEX = _HISTORICAL_IMPORT_PIPELINE.load_summary_index(Path(summary_csv_path))


def _historical_import_worker_process(file_path_str: str) -> dict[str, Any]:
    file_path = Path(file_path_str)
    try:
        article = _HISTORICAL_IMPORT_PIPELINE.build_historical_article(file_path, _HISTORICAL_IMPORT_SUMMARY_INDEX)
        analysis = _HISTORICAL_IMPORT_PIPELINE.analyze_article(article)
        return {
            "ok": True,
            "file_name": file_path.name,
            "article": article,
            "analysis": analysis,
        }
    except Exception as error:
        return {
            "ok": False,
            "file_name": file_path.name,
            "error": str(error),
        }


class Database:
    def __init__(self, path: Path):
        self.path = path
        ensure_dirs()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS factor_rows (
                    date TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_bars (
                    symbol TEXT NOT NULL,
                    granularity TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, granularity, observed_at)
                );

                CREATE TABLE IF NOT EXISTS market_bar_aggregates (
                    symbol TEXT NOT NULL,
                    granularity TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, granularity, observed_at)
                );

                CREATE TABLE IF NOT EXISTS model_runs (
                    run_id TEXT PRIMARY KEY,
                    trigger_source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    factor_as_of TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    output_dir TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS model_outputs (
                    output_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_artifacts (
                    run_id TEXT NOT NULL,
                    artifact_key TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, artifact_key)
                );

                CREATE TABLE IF NOT EXISTS source_status (
                    source_key TEXT PRIMARY KEY,
                    last_success_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news_articles (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    published_at TEXT,
                    effective_published_at TEXT,
                    author TEXT,
                    summary TEXT,
                    content_text TEXT NOT NULL,
                    content_html TEXT,
                    cover_image_url TEXT,
                    source_category TEXT,
                    language TEXT NOT NULL,
                    hash_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news_analysis (
                    article_id TEXT PRIMARY KEY,
                    sentiment_score REAL NOT NULL,
                    sentiment_label TEXT NOT NULL,
                    tone_score REAL NOT NULL,
                    geo_entities_json TEXT NOT NULL,
                    macro_entities_json TEXT NOT NULL,
                    topic_tags_json TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    keywords_json TEXT NOT NULL,
                    mention_count INTEGER NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    analyzer_version TEXT NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES news_articles(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_news_articles_published_at
                ON news_articles (published_at DESC);

                CREATE INDEX IF NOT EXISTS idx_news_articles_ingested_at
                ON news_articles (ingested_at DESC);

                CREATE INDEX IF NOT EXISTS idx_job_logs_source_created_at
                ON job_logs (source_key, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_model_runs_started_at
                ON model_runs (started_at DESC);
                """
            )
        self.ensure_news_article_schema()
        self.normalize_news_published_at_values()

    def ensure_news_article_schema(self) -> None:
        with self.connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(news_articles)").fetchall()
            }
            if "effective_published_at" not in columns:
                connection.execute("ALTER TABLE news_articles ADD COLUMN effective_published_at TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_news_articles_effective_published_at
                ON news_articles (effective_published_at DESC)
                """
            )
            connection.execute(
                """
                UPDATE news_articles
                SET effective_published_at = COALESCE(NULLIF(published_at, ''), ingested_at)
                WHERE effective_published_at IS NULL OR effective_published_at = ''
                """
            )

    def normalize_news_published_at_values(self) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, published_at, ingested_at, effective_published_at
                FROM news_articles
                """
            ).fetchall()
            updates: list[tuple[str | None, str | None, str]] = []
            for row in rows:
                normalized = standardize_published_at(row["published_at"])
                effective_published_at = resolve_effective_published_at(normalized, row["ingested_at"])
                if normalized != row["published_at"] or effective_published_at != row["effective_published_at"]:
                    updates.append((normalized, effective_published_at, row["id"]))
            if updates:
                connection.executemany(
                    """
                    UPDATE news_articles
                    SET published_at = ?, effective_published_at = ?
                    WHERE id = ?
                    """,
                    updates,
                )
        return len(updates)

    def replace_factor_rows(self, rows: list[dict[str, Any]], updated_at: str) -> None:
        deduped = {}
        for row in rows:
            deduped[str(row["Date"])] = row
        payloads = [(date_key, json_dumps(row), updated_at) for date_key, row in deduped.items()]
        with self.connect() as connection:
            connection.execute("DELETE FROM factor_rows")
            connection.executemany(
                "INSERT INTO factor_rows (date, payload_json, updated_at) VALUES (?, ?, ?)",
                payloads,
            )

    def upsert_factor_rows(self, rows: list[dict[str, Any]], updated_at: str) -> None:
        deduped = {}
        for row in rows:
            deduped[str(row["Date"])] = row
        payloads = [(date_key, json_dumps(row), updated_at) for date_key, row in deduped.items()]
        if not payloads:
            return
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO factor_rows (date, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                payloads,
            )

    def list_factor_rows(self, descending: bool = False) -> list[dict[str, Any]]:
        direction = "DESC" if descending else "ASC"
        with self.connect() as connection:
            result = connection.execute(
                f"SELECT payload_json FROM factor_rows ORDER BY date {direction}"
            ).fetchall()
        return [json_loads(item["payload_json"], {}) for item in result]

    def get_factor_rows(self, limit: int = 50, query: str = "") -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clause = ""
        if query.strip():
            where_clause = "WHERE lower(payload_json) LIKE ?"
            params.append(f"%{query.strip().lower()}%")
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json
                FROM factor_rows
                {where_clause}
                ORDER BY date DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [json_loads(row["payload_json"], {}) for row in rows]

    def get_factor_history_rows(self, limit: int, end_date: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clause = ""
        if end_date:
            where_clause = "WHERE date <= ?"
            params.append(end_date)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json
                FROM factor_rows
                {where_clause}
                ORDER BY date DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        ordered_rows = list(reversed(rows))
        return [json_loads(row["payload_json"], {}) for row in ordered_rows]

    def _build_news_filters(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        timezone_name: str | None = "UTC",
        table_alias: str = "",
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        prefix = f"{table_alias}." if table_alias else ""

        if query.strip():
            like = f"%{query.strip().lower()}%"
            conditions.append(
                "("
                f"lower({prefix}title) LIKE ? OR lower(COALESCE({prefix}summary, '')) LIKE ? OR "
                f"lower(COALESCE({prefix}content_text, '')) LIKE ? OR lower(COALESCE({prefix}source_category, '')) LIKE ?"
                ")"
            )
            params.extend([like, like, like, like])

        start_bound, end_bound = resolve_date_range_utc_bounds(start, end, timezone_name)
        if start_bound:
            conditions.append(f"{prefix}effective_published_at >= ?")
            params.append(start_bound)
        if end_bound:
            conditions.append(f"{prefix}effective_published_at < ?")
            params.append(end_bound)

        return conditions, params

    def replace_market_bars(
        self,
        symbol: str,
        granularity: str,
        bars: list[dict[str, Any]],
        source_updated_at: str,
    ) -> None:
        deduped = {}
        for bar in bars:
            deduped[bar["observed_at"]] = bar
        records = [
            (
                symbol,
                granularity,
                observed_at,
                float(bar["open"]),
                float(bar["high"]),
                float(bar["low"]),
                float(bar["close"]),
                source_updated_at,
            )
            for observed_at, bar in deduped.items()
        ]
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM market_bars WHERE symbol = ? AND granularity = ?",
                (symbol, granularity),
            )
            connection.executemany(
                """
                INSERT INTO market_bars
                (symbol, granularity, observed_at, open, high, low, close, source_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    def get_market_bars(
        self,
        symbol: str,
        granularity: str,
        limit: int,
        observed_at_lte: str | None = None,
    ) -> list[dict[str, Any]]:
        where_suffix = ""
        params: list[Any] = [symbol, granularity]
        if observed_at_lte:
            where_suffix = " AND observed_at <= ?"
            params.append(observed_at_lte)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT observed_at, open, high, low, close, source_updated_at
                FROM market_bars
                WHERE symbol = ? AND granularity = ?{where_suffix}
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        ordered = list(reversed(rows))
        return [
            {
                "observed_at": row["observed_at"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "source_updated_at": row["source_updated_at"],
            }
            for row in ordered
        ]

    def replace_market_aggregate_bars(
        self,
        symbol: str,
        granularity: str,
        bars: list[dict[str, Any]],
        source_updated_at: str,
    ) -> None:
        deduped = {}
        for bar in bars:
            deduped[bar["observed_at"]] = bar
        records = [
            (
                symbol,
                granularity,
                observed_at,
                float(bar["open"]),
                float(bar["high"]),
                float(bar["low"]),
                float(bar["close"]),
                source_updated_at,
            )
            for observed_at, bar in deduped.items()
        ]
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM market_bar_aggregates WHERE symbol = ? AND granularity = ?",
                (symbol, granularity),
            )
            connection.executemany(
                """
                INSERT INTO market_bar_aggregates
                (symbol, granularity, observed_at, open, high, low, close, source_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    def get_market_aggregate_bars(self, symbol: str, granularity: str, limit: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT observed_at, open, high, low, close, source_updated_at
                FROM market_bar_aggregates
                WHERE symbol = ? AND granularity = ?
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                (symbol, granularity, limit),
            ).fetchall()
        ordered = list(reversed(rows))
        return [
            {
                "observed_at": row["observed_at"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "source_updated_at": row["source_updated_at"],
            }
            for row in ordered
        ]

    def clear_market_aggregate_bars(self, symbol: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM market_bar_aggregates WHERE symbol = ?",
                (symbol,),
            )
        return int(cursor.rowcount or 0)

    def prune_market_bars_before(self, symbol: str, granularity: str, observed_at_cutoff: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM market_bars
                WHERE symbol = ? AND granularity = ? AND observed_at < ?
                """,
                (symbol, granularity, observed_at_cutoff),
            )
        return int(cursor.rowcount or 0)

    def insert_model_run(self, run_id: str, trigger_source: str, factor_as_of: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO model_runs (run_id, trigger_source, status, factor_as_of, started_at)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, trigger_source, factor_as_of, iso_now()),
            )

    def finish_model_run(
        self,
        run_id: str,
        status: str,
        output_dir: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE model_runs
                SET status = ?, completed_at = ?, output_dir = ?, error_message = ?
                WHERE run_id = ?
                """,
                (status, iso_now(), output_dir, error_message, run_id),
            )

    def upsert_model_output(self, output_key: str, run_id: str, as_of: str, payload: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO model_outputs (output_key, run_id, as_of, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(output_key) DO UPDATE SET
                    run_id = excluded.run_id,
                    as_of = excluded.as_of,
                    payload_json = excluded.payload_json
                """,
                (output_key, run_id, as_of, json_dumps(payload)),
            )

    def get_model_output(self, output_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT run_id, as_of, payload_json FROM model_outputs WHERE output_key = ?",
                (output_key,),
            ).fetchone()
        if not row:
            return None
        return {
            "run_id": row["run_id"],
            "as_of": row["as_of"],
            "payload": json_loads(row["payload_json"], {}),
        }

    def upsert_artifact(self, run_id: str, artifact_key: str, artifact_path: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO model_artifacts (run_id, artifact_key, artifact_path, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, artifact_key) DO UPDATE SET
                    artifact_path = excluded.artifact_path,
                    created_at = excluded.created_at
                """,
                (run_id, artifact_key, artifact_path, iso_now()),
            )

    def upsert_source_status(self, source_key: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_status (source_key, last_success_at, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    last_success_at = excluded.last_success_at,
                    payload_json = excluded.payload_json
                """,
                (source_key, iso_now(), json_dumps(payload)),
            )

    def patch_source_status(self, source_key: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT last_success_at, payload_json FROM source_status WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if not row:
                connection.execute(
                    """
                    INSERT INTO source_status (source_key, last_success_at, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (source_key, "", json_dumps(payload)),
                )
                return
            merged = json_loads(row["payload_json"], {})
            merged.update(payload)
            connection.execute(
                """
                UPDATE source_status
                SET payload_json = ?
                WHERE source_key = ?
                """,
                (json_dumps(merged), source_key),
            )

    def get_source_status(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT source_key, last_success_at, payload_json FROM source_status"
            ).fetchall()
        return {
            row["source_key"]: {
                "last_success_at": row["last_success_at"],
                "payload": json_loads(row["payload_json"], {}),
            }
            for row in rows
        }

    def get_source_last_success_at(self, source_key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT last_success_at FROM source_status WHERE source_key = ?",
                (source_key,),
            ).fetchone()
        return row["last_success_at"] if row else None

    def upsert_news_article(
        self,
        article: dict[str, Any],
        analysis: dict[str, Any],
        ingested_at: str,
    ) -> None:
        normalized_published_at = standardize_published_at(article.get("published_at"))
        effective_published_at = resolve_effective_published_at(normalized_published_at, ingested_at)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO news_articles
                (
                    id, source, url, title, published_at, effective_published_at, author, summary, content_text,
                    content_html, cover_image_url, source_category, language, hash_digest,
                    status, ingested_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    published_at = excluded.published_at,
                    effective_published_at = excluded.effective_published_at,
                    author = excluded.author,
                    summary = excluded.summary,
                    content_text = excluded.content_text,
                    content_html = excluded.content_html,
                    cover_image_url = excluded.cover_image_url,
                    source_category = excluded.source_category,
                    language = excluded.language,
                    hash_digest = excluded.hash_digest,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    article["id"],
                    article["source"],
                    article["url"],
                    article["title"],
                    normalized_published_at,
                    effective_published_at,
                    article.get("author"),
                    article.get("summary"),
                    article["content_text"],
                    article.get("content_html"),
                    article.get("cover_image_url"),
                    article.get("source_category"),
                    article.get("language", "en"),
                    article["hash_digest"],
                    article.get("status", "ready"),
                    ingested_at,
                    ingested_at,
                ),
            )
            article_id_row = connection.execute(
                "SELECT id FROM news_articles WHERE url = ?",
                (article["url"],),
            ).fetchone()
            article_id = article_id_row["id"] if article_id_row else article["id"]
            connection.execute(
                """
                INSERT INTO news_analysis
                (
                    article_id, sentiment_score, sentiment_label, tone_score, geo_entities_json,
                    macro_entities_json, topic_tags_json, risk_score, risk_level, keywords_json,
                    mention_count, analyzed_at, analyzer_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    sentiment_score = excluded.sentiment_score,
                    sentiment_label = excluded.sentiment_label,
                    tone_score = excluded.tone_score,
                    geo_entities_json = excluded.geo_entities_json,
                    macro_entities_json = excluded.macro_entities_json,
                    topic_tags_json = excluded.topic_tags_json,
                    risk_score = excluded.risk_score,
                    risk_level = excluded.risk_level,
                    keywords_json = excluded.keywords_json,
                    mention_count = excluded.mention_count,
                    analyzed_at = excluded.analyzed_at,
                    analyzer_version = excluded.analyzer_version
                """,
                (
                    article_id,
                    analysis["sentiment_score"],
                    analysis["sentiment_label"],
                    analysis["tone_score"],
                    json_dumps(analysis.get("geo_entities", [])),
                    json_dumps(analysis.get("macro_entities", [])),
                    json_dumps(analysis.get("topic_tags", [])),
                    analysis["risk_score"],
                    analysis["risk_level"],
                    json_dumps(analysis.get("keywords", [])),
                    analysis.get("mention_count", 0),
                    ingested_at,
                    analysis.get("analyzer_version", ""),
                ),
            )

    def get_news_articles(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        limit: int = 50,
        timezone_name: str | None = "UTC",
    ) -> list[dict[str, Any]]:
        conditions, params = self._build_news_filters(
            start=start,
            end=end,
            query=query,
            timezone_name=timezone_name,
            table_alias="n",
        )
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT
                n.id,
                n.source,
                n.url,
                n.title,
                n.published_at,
                n.ingested_at,
                n.author,
                n.summary,
                n.cover_image_url,
                n.source_category,
                a.sentiment_score,
                a.sentiment_label,
                a.tone_score,
                a.risk_score,
                a.risk_level,
                a.mention_count,
                a.geo_entities_json,
                a.macro_entities_json,
                a.topic_tags_json,
                a.keywords_json
            FROM news_articles n
            LEFT JOIN news_analysis a ON a.article_id = n.id
            {where_clause}
            ORDER BY n.effective_published_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row_to_news_item(row) for row in rows]

    def count_news_articles(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        timezone_name: str | None = "UTC",
    ) -> int:
        conditions, params = self._build_news_filters(
            start=start,
            end=end,
            query=query,
            timezone_name=timezone_name,
        )
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM news_articles {where_clause}",
                params,
            ).fetchone()
        return int(row["count"] or 0) if row else 0

    def get_news_date_bounds(self, timezone_name: str | None = "UTC") -> dict[str, str | None]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    MIN(effective_published_at) AS min_timestamp,
                    MAX(effective_published_at) AS max_timestamp
                FROM news_articles
                """
            ).fetchone()

        min_date = to_timezone_date_key(row["min_timestamp"], timezone_name) if row else None
        max_date = to_timezone_date_key(row["max_timestamp"], timezone_name) if row else None

        return {
            "minDate": min_date,
            "maxDate": max_date,
        }

    def get_news_article_detail(self, article_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    n.id,
                    n.source,
                    n.url,
                    n.title,
                    n.published_at,
                    n.author,
                    n.summary,
                    n.content_text,
                    n.cover_image_url,
                    n.source_category,
                    a.sentiment_score,
                    a.sentiment_label,
                    a.tone_score,
                    a.risk_score,
                    a.risk_level,
                    a.mention_count,
                    a.geo_entities_json,
                    a.macro_entities_json,
                    a.topic_tags_json,
                    a.keywords_json,
                    a.analyzer_version,
                    a.analyzed_at
                FROM news_articles n
                LEFT JOIN news_analysis a ON a.article_id = n.id
                WHERE n.id = ?
                """,
                (article_id,),
            ).fetchone()
        if not row:
            return None
        item = self._row_to_news_item(row)
        item["contentText"] = row["content_text"]
        item["analysis"] = {
            "sentimentScore": row["sentiment_score"] or 0.0,
            "sentimentLabel": row["sentiment_label"] or "neutral",
            "toneMean": row["tone_score"] or 0.0,
            "riskScore": row["risk_score"] or 0,
            "riskLevel": row["risk_level"] or "Low",
            "mentionCount": row["mention_count"] or 0,
            "geoEntities": json_loads(row["geo_entities_json"], []),
            "macroEntities": json_loads(row["macro_entities_json"], []),
            "topicTags": json_loads(row["topic_tags_json"], []),
            "keywords": json_loads(row["keywords_json"], []),
            "analyzerVersion": row["analyzer_version"],
            "analyzedAt": row["analyzed_at"],
        }
        return item

    def get_news_reanalysis_batch(self, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    n.id,
                    n.source,
                    n.url,
                    n.title,
                    n.published_at,
                    n.author,
                    n.summary,
                    n.content_text,
                    n.content_html,
                    n.cover_image_url,
                    n.source_category,
                    n.language,
                    n.hash_digest,
                    n.status
                FROM news_articles n
                ORDER BY COALESCE(n.published_at, n.ingested_at) ASC, n.id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_all_news_urls(self) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT url FROM news_articles").fetchall()
        return {str(row["url"]) for row in rows if row["url"]}

    def get_latest_news_published_at(self) -> str | None:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT published_at FROM news_articles WHERE published_at IS NOT NULL AND published_at <> ''"
            ).fetchall()
        latest_value = None
        latest_dt = None
        for row in rows:
            value = standardize_published_at(row["published_at"])
            parsed = parse_flexible_datetime(value)
            if parsed is None:
                continue
            if latest_dt is None or parsed > latest_dt:
                latest_dt = parsed
                latest_value = value
        return latest_value

    def get_latest_news_url(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT url
                FROM news_articles
                WHERE url IS NOT NULL AND url <> ''
                ORDER BY COALESCE(published_at, ingested_at) DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return str(row["url"]) if row["url"] else None

    def update_news_analysis(self, article_id: str, analysis: dict[str, Any], analyzed_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO news_analysis
                (
                    article_id, sentiment_score, sentiment_label, tone_score, geo_entities_json,
                    macro_entities_json, topic_tags_json, risk_score, risk_level, keywords_json,
                    mention_count, analyzed_at, analyzer_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    sentiment_score = excluded.sentiment_score,
                    sentiment_label = excluded.sentiment_label,
                    tone_score = excluded.tone_score,
                    geo_entities_json = excluded.geo_entities_json,
                    macro_entities_json = excluded.macro_entities_json,
                    topic_tags_json = excluded.topic_tags_json,
                    risk_score = excluded.risk_score,
                    risk_level = excluded.risk_level,
                    keywords_json = excluded.keywords_json,
                    mention_count = excluded.mention_count,
                    analyzed_at = excluded.analyzed_at,
                    analyzer_version = excluded.analyzer_version
                """,
                (
                    article_id,
                    analysis["sentiment_score"],
                    analysis["sentiment_label"],
                    analysis["tone_score"],
                    json_dumps(analysis.get("geo_entities", [])),
                    json_dumps(analysis.get("macro_entities", [])),
                    json_dumps(analysis.get("topic_tags", [])),
                    analysis["risk_score"],
                    analysis["risk_level"],
                    json_dumps(analysis.get("keywords", [])),
                    analysis.get("mention_count", 0),
                    analyzed_at,
                    analysis.get("analyzer_version", ""),
                ),
            )

    def _row_to_news_item(self, row: sqlite3.Row) -> dict[str, Any]:
        published_at = row["published_at"]
        date_value = parse_flexible_datetime(str(published_at)) if published_at else None
        date_str = date_value.strftime("%Y-%m-%d") if date_value else ""
        impact = row["risk_level"] or "Low"
        topic_tags = json_loads(row["topic_tags_json"], [])
        primary_category = topic_tags[0]["label"] if topic_tags else (row["source_category"] or "World News")
        return {
            "id": row["id"],
            "source": row["source"],
            "url": row["url"],
            "title": row["title"],
            "publishedAt": published_at,
            "publishedDate": date_str,
            "year": date_value.year if date_value else None,
            "month": date_value.month if date_value else None,
            "day": date_value.day if date_value else None,
            "author": row["author"],
            "summary": row["summary"] or "",
            "coverImageUrl": row["cover_image_url"],
            "category": primary_category,
            "sentiment": round(float(row["sentiment_score"] or 0.0), 2),
            "sentimentLabel": row["sentiment_label"] or "neutral",
            "toneMean": round(float(row["tone_score"] or 0.0), 2),
            "risk": int(round(float(row["risk_score"] or 0))),
            "impact": impact,
            "mentionCount": int(row["mention_count"] or 0),
            "geoEntities": json_loads(row["geo_entities_json"], []),
            "macroEntities": json_loads(row["macro_entities_json"], []),
            "topicTags": topic_tags,
            "keywords": json_loads(row["keywords_json"], []),
        }

    def insert_job_log(self, source_key: str, status: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO job_logs (source_key, status, message, created_at) VALUES (?, ?, ?, ?)",
                (source_key, status, message, iso_now()),
            )

    def get_job_logs(self, limit: int = 50, source_key: str = "", status: str = "") -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if source_key:
            clauses.append("source_key = ?")
            params.append(source_key)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, source_key, status, message, created_at
                FROM job_logs
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "sourceKey": row["source_key"],
                "status": row["status"],
                "message": row["message"] or "",
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


class BackendService:
    def __init__(self, database: Database, factor_update_pipeline: FactorUpdatePipeline | None = None):
        self.database = database
        self._model_lock = threading.Lock()
        self._news_lock = threading.Lock()
        self._last_factor_df: pd.DataFrame | None = None
        self.news_pipeline = OilPriceNewsPipeline()
        self._ai_lock = threading.Lock()
        self._ai_pipeline = None
        self.factor_update_pipeline = factor_update_pipeline or FactorUpdatePipeline()

    def _build_analysis_source_contract(
        self,
        *,
        primary_source: str,
        required_published_view: str,
        output_key: str,
        analysis_context_source: str | None = None,
    ) -> dict[str, Any]:
        # 非仪表盘分析链路只能消费因子链路或模型链路产物，不能回读实时行情视图。
        contract = {
            "primarySource": primary_source,
            "requiredPublishedView": required_published_view,
            "outputKey": output_key,
            "excludedViews": ["latest_prices"],
            "marketMinuteDataDisallowed": True,
        }
        if analysis_context_source:
            contract["analysisContextSource"] = analysis_context_source
        return contract

    def _attach_analysis_source_contract(
        self,
        payload: dict[str, Any],
        *,
        primary_source: str,
        required_published_view: str,
        output_key: str,
        analysis_context_source: str | None = None,
    ) -> dict[str, Any]:
        enriched = dict(payload)
        enriched["sourceContract"] = self._build_analysis_source_contract(
            primary_source=primary_source,
            required_published_view=required_published_view,
            output_key=output_key,
            analysis_context_source=analysis_context_source,
        )
        return enriched

    def _load_reference_factor_frame(self) -> pd.DataFrame:
        if not SOURCE_FACTORS_CSV.exists():
            raise FileNotFoundError(f"缺少基线因子文件：{SOURCE_FACTORS_CSV}")
        return normalize_factor_frame(pd.read_csv(SOURCE_FACTORS_CSV))

    def _load_database_factor_frame(self) -> pd.DataFrame:
        rows = self.database.list_factor_rows()
        if not rows:
            return pd.DataFrame(columns=["Date"])
        return normalize_factor_frame(pd.DataFrame(rows))

    def _export_factor_rows_to_working_csv(self) -> pd.DataFrame:
        ensure_dirs()
        frame = self._load_database_factor_frame()
        if frame.empty:
            raise RuntimeError("因子表为空，无法导出模型工作 CSV")
        frame.to_csv(WORKING_FACTORS_CSV, index=False)
        return frame

    def load_factor_frame(self) -> pd.DataFrame:
        if self._last_factor_df is None:
            self._last_factor_df = pd.read_csv(WORKING_FACTORS_CSV)
        frame = self._last_factor_df.copy()
        frame["Date"] = pd.to_datetime(frame["Date"])
        frame = frame.sort_values("Date").reset_index(drop=True)
        return frame

    def _validate_factor_sync_result(self, update_result) -> None:
        expected_latest = expected_factor_latest_date(getattr(self.factor_update_pipeline, "timezone_name", None))
        latest_date = (update_result.latest_date or "").strip()
        if latest_date and latest_date >= expected_latest:
            return

        reasons = []
        if latest_date:
            reasons.append(f"因子快照最新日期仍为 {latest_date}，未达到预期 {expected_latest}")
        else:
            reasons.append(f"因子快照为空，未达到预期 {expected_latest}")
        if update_result.failed_sources:
            reasons.append("失败数据源: " + ", ".join(update_result.failed_sources))
        if update_result.warnings:
            reasons.append("警告: " + "；".join(update_result.warnings))
        raise RuntimeError("；".join(reasons))

    def sync_factors(self) -> JobResult:
        ensure_dirs()
        reference_frame = self._load_reference_factor_frame()
        existing_frame = self._load_database_factor_frame()
        update_result = self.factor_update_pipeline.run(existing_frame, reference_frame)
        self._validate_factor_sync_result(update_result)
        updated_at = iso_now()
        self.database.upsert_factor_rows(update_result.rows, updated_at)
        frame = self._export_factor_rows_to_working_csv()
        rows = frame.to_dict(orient="records")
        self.database.upsert_source_status(
            "factors",
            {
                "row_count": len(rows),
                "path": str(WORKING_FACTORS_CSV),
                "latest_date": update_result.latest_date,
                "updated_dates": update_result.updated_dates,
                "warning_count": len(update_result.warnings),
                "warnings": update_result.warnings,
                "failed_sources": update_result.failed_sources,
            },
        )
        self.database.insert_job_log(
            "factors",
            "success",
            f"已同步 {len(rows)} 行因子数据，最新日期 {update_result.latest_date or '未知'}，警告 {len(update_result.warnings)} 条",
        )
        self._last_factor_df = None
        return JobResult(
            "factors",
            True,
            updated_at,
            {
                "row_count": len(rows),
                "latest_date": update_result.latest_date,
                "updated_dates": update_result.updated_dates,
                "warning_count": len(update_result.warnings),
                "failed_sources": update_result.failed_sources,
            },
        )

    def _align_market_bars(
        self,
        left_bars: list[dict[str, Any]],
        right_bars: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        right_lookup = {bar["observed_at"]: bar for bar in right_bars}
        aligned = []
        for left in left_bars:
            right = right_lookup.get(left["observed_at"])
            if right:
                aligned.append((left, right))
        return aligned

    def _build_spread_bars(
        self,
        left_bars: list[dict[str, Any]],
        right_bars: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        spread_bars = []
        for left, right in self._align_market_bars(left_bars, right_bars):
            spread_open = round(float(left["open"]) - float(right["open"]), 4)
            spread_close = round(float(left["close"]) - float(right["close"]), 4)
            spread_bars.append(
                {
                    "observed_at": left["observed_at"],
                    "open": spread_open,
                    "high": max(spread_open, spread_close),
                    "low": min(spread_open, spread_close),
                    "close": spread_close,
                }
            )
        return spread_bars

    def _record_market_fetch_failure(
        self,
        failures: dict[str, dict[str, str]],
        series_id: str,
        granularity: str,
        error: Exception,
    ) -> None:
        series_failures = failures.setdefault(series_id, {})
        series_failures[granularity] = str(error)

    def _fetch_provider_market_bars(
        self,
        storage_limits: dict[str, int] | None = None,
    ) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], str, dict[str, dict[str, str]]]:
        provider = build_market_data_provider()
        output_sizes = dict(storage_limits or MARKET_STORAGE_LIMIT)
        fetched_at = iso_now()
        raw_bars: dict[str, dict[str, list[dict[str, Any]]]] = {}
        failures: dict[str, dict[str, str]] = {}
        provider_series_ids = [
            definition.series_id
            for definition in MARKET_SERIES_DEFINITIONS.values()
            if definition.source_kind == "provider"
        ]
        symbol_lookup = {series_id: resolve_provider_symbol(series_id) for series_id in provider_series_ids}
        for series_id in provider_series_ids:
            raw_bars[series_id] = {}
        for granularity, outputsize in output_sizes.items():
            batch_results: dict[str, list[dict[str, Any]]] = {}
            missing_series_ids = list(provider_series_ids)
            if hasattr(provider, "fetch_batch_bars"):
                try:
                    batch_results = provider.fetch_batch_bars(provider_series_ids, symbol_lookup, granularity, outputsize)
                except Exception as error:
                    for series_id in provider_series_ids:
                        self._record_market_fetch_failure(failures, series_id, granularity, error)
                    batch_results = {}
                else:
                    missing_series_ids = [series_id for series_id in provider_series_ids if series_id not in batch_results]
                    for series_id, bars in batch_results.items():
                        raw_bars[series_id][granularity] = bars
            for series_id in missing_series_ids:
                try:
                    raw_bars[series_id][granularity] = provider.fetch_bars(
                        symbol_lookup[series_id],
                        granularity,
                        outputsize,
                        series_id,
                    )
                    failures.get(series_id, {}).pop(granularity, None)
                except Exception as error:
                    self._record_market_fetch_failure(failures, series_id, granularity, error)

        raw_bars["WTI_Brent_Spread"] = {}
        for granularity in output_sizes:
            left_bars = raw_bars["WTI_Close"].get(granularity)
            right_bars = raw_bars["Brent_Close"].get(granularity)
            if not left_bars or not right_bars:
                continue
            raw_bars["WTI_Brent_Spread"][granularity] = self._build_spread_bars(left_bars, right_bars)

        filtered_raw_bars = {
            series_id: bars_by_granularity
            for series_id, bars_by_granularity in raw_bars.items()
            if bars_by_granularity
        }
        filtered_failures = {
            series_id: series_failures
            for series_id, series_failures in failures.items()
            if series_failures
        }
        return filtered_raw_bars, fetched_at, filtered_failures

    def _merge_market_history_window(
        self,
        symbol: str,
        granularity: str,
        incoming_bars: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        existing_bars = self.database.get_market_bars(symbol, granularity, limit)
        merged_by_observed_at: dict[str, dict[str, Any]] = {}
        for bar in existing_bars:
            merged_by_observed_at[str(bar["observed_at"])] = {
                "observed_at": str(bar["observed_at"]),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            }
        for bar in incoming_bars:
            merged_by_observed_at[str(bar["observed_at"])] = {
                "observed_at": str(bar["observed_at"]),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            }
        merged_rows = list(merged_by_observed_at.values())
        merged_rows.sort(key=lambda item: item["observed_at"])
        return merged_rows[-limit:]

    def _refresh_market_aggregates(self, symbol: str, updated_at: str) -> dict[str, int]:
        aggregate_counts: dict[str, int] = {}
        for aggregate_granularity, source_granularity in DISPLAY_GRANULARITY_TO_SOURCE.items():
            source_limit = RAW_MARKET_RETENTION_LIMITS[source_granularity]
            source_rows = self.database.get_market_bars(symbol, source_granularity, source_limit)
            aggregated_rows = aggregate_market_bars(source_rows, aggregate_granularity)
            self.database.replace_market_aggregate_bars(symbol, aggregate_granularity, aggregated_rows, updated_at)
            aggregate_counts[aggregate_granularity] = len(aggregated_rows)
        return aggregate_counts

    def _purge_legacy_market_layers(self, symbol: str, updated_at: str) -> None:
        for granularity in ("5m", "1h"):
            self.database.replace_market_bars(symbol, granularity, [], updated_at)
        self.database.clear_market_aggregate_bars(symbol)

    def _prune_expired_market_history(self, symbol: str, updated_at: str) -> dict[str, int]:
        pruned_counts: dict[str, int] = {}
        updated_timestamp = pd.Timestamp(updated_at).tz_convert("UTC")
        for granularity, retention_days in RAW_MARKET_RETENTION_DAYS.items():
            cutoff = (updated_timestamp - pd.Timedelta(days=retention_days)).isoformat()
            pruned_counts[granularity] = self.database.prune_market_bars_before(symbol, granularity, cutoff)
        return pruned_counts

    def sync_market(self, full_minute_history: bool = False) -> JobResult:
        storage_limits = dict(MARKET_STORAGE_LIMIT)
        if full_minute_history:
            storage_limits["1m"] = FULL_MINUTE_HISTORY_LIMIT
        bars_by_symbol, updated_at, fetch_failures = self._fetch_provider_market_bars(storage_limits=storage_limits)
        if not bars_by_symbol:
            failure_details = [
                f"{series_id}:{granularity}={message}"
                for series_id, series_failures in sorted(fetch_failures.items())
                for granularity, message in sorted(series_failures.items())
            ]
            raise RuntimeError("市场数据抓取全部失败: " + "; ".join(failure_details[:8]))
        aggregate_summary: dict[str, dict[str, int]] = {}
        pruned_summary: dict[str, dict[str, int]] = {}
        for symbol, bars_by_granularity in bars_by_symbol.items():
            for granularity, bars in bars_by_granularity.items():
                if granularity == "1m" and not full_minute_history:
                    bars = self._merge_market_history_window(
                        symbol,
                        granularity,
                        bars,
                        FULL_MINUTE_HISTORY_LIMIT,
                    )
                self.database.replace_market_bars(symbol, granularity, bars, updated_at)
            self._purge_legacy_market_layers(symbol, updated_at)
            pruned_summary[symbol] = self._prune_expired_market_history(symbol, updated_at)
            aggregate_summary[symbol] = self._refresh_market_aggregates(symbol, updated_at)
        failed_series = [
            {
                "seriesId": series_id,
                "granularities": dict(sorted(series_failures.items())),
            }
            for series_id, series_failures in sorted(fetch_failures.items())
        ]
        warning_count = len(failed_series)
        status = "degraded" if warning_count else "success"
        last_error = ""
        if failed_series:
            first_failure = failed_series[0]
            first_granularity, first_message = next(iter(first_failure["granularities"].items()))
            last_error = f"{first_failure['seriesId']}[{first_granularity}] {first_message}"
        self.database.upsert_source_status(
            "market",
            {
                "status": status,
                "symbols": list(MARKET_SYMBOLS.keys()),
                "updatedSymbols": sorted(bars_by_symbol.keys()),
                "granularities": list(dict.fromkeys(RANGE_TO_GRANULARITY.values())),
                "displayGranularities": list(DISPLAY_GRANULARITY_TO_SOURCE.keys()),
                "provider": os.getenv("MARKET_DATA_PROVIDER", "hybrid").strip().lower(),
                "minuteBarLimit": FULL_MINUTE_HISTORY_LIMIT,
                "minuteHistoryDays": FULL_MINUTE_HISTORY_DAYS,
                "rawRetentionDays": RAW_MARKET_RETENTION_DAYS,
                "warning_count": warning_count,
                "failed_series": failed_series,
                "last_error": last_error,
            },
        )
        job_message = (
            f"已刷新真实行情快照，并回补最近 {FULL_MINUTE_HISTORY_DAYS} 天分钟级数据"
            if full_minute_history
            else "已刷新真实行情快照"
        )
        if failed_series:
            failed_series_summary = ", ".join(
                f"{item['seriesId']}[{','.join(item['granularities'].keys())}]"
                for item in failed_series[:5]
            )
            if len(failed_series) > 5:
                failed_series_summary += f" 等 {len(failed_series)} 个序列"
            job_message = f"{job_message}，部分序列回退或跳过：{failed_series_summary}"
            self.database.insert_job_log("market", "warning", job_message)
        else:
            self.database.insert_job_log("market", "success", job_message)
        return JobResult(
            "market",
            True,
            updated_at,
            {
                "status": status,
                "symbols": len(MARKET_SYMBOLS),
                "updatedSymbols": sorted(bars_by_symbol.keys()),
                "minuteBarLimit": FULL_MINUTE_HISTORY_LIMIT,
                "minuteHistoryDays": FULL_MINUTE_HISTORY_DAYS,
                "fullMinuteHistory": full_minute_history,
                "aggregateSummary": aggregate_summary,
                "prunedSummary": pruned_summary,
                "warning_count": warning_count,
                "failed_series": failed_series,
                "last_error": last_error,
            },
        )

    def sync_news(
        self,
        catch_up: bool = False,
        sync_mode: str | None = None,
        page_limit: int | None = None,
        article_limit: int | None = None,
        stale_page_limit: int = 1,
        workers: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> JobResult:
        if not self._news_lock.acquire(blocking=False):
            raise RuntimeError("新闻同步任务正在运行中")
        requested_page_limit = page_limit
        normalized_sync_mode = (sync_mode or "").strip().lower()
        if normalized_sync_mode not in {"", "catch_up", "recent_pages"}:
            raise ValueError(f"未知新闻同步模式：{sync_mode}")
        effective_sync_mode = "catch_up" if catch_up else (normalized_sync_mode or "latest_sync")
        page_limit = max(1, page_limit or int(os.getenv("NEWS_SYNC_PAGE_LIMIT", "2")))
        article_limit = max(1, article_limit or int(os.getenv("NEWS_SYNC_ARTICLE_LIMIT", "24")))
        stale_page_limit = max(1, stale_page_limit)
        workers = max(1, workers)
        updated_at = iso_now()
        try:
            def emit(message: str) -> None:
                if progress_callback:
                    progress_callback(message)

            def load_entry_bundle(entry: dict[str, str]) -> dict[str, Any]:
                try:
                    article, analysis = self.news_pipeline.build_article_bundle(entry)
                    return {"ok": True, "entry": entry, "article": article, "analysis": analysis}
                except Exception as error:
                    return {"ok": False, "entry": entry, "error": str(error)}

            def load_page_results(candidate_entries: list[dict[str, str]]) -> list[dict[str, Any]]:
                if not candidate_entries:
                    return []
                if workers == 1:
                    return [load_entry_bundle(entry) for entry in candidate_entries]
                with ThreadPoolExecutor(max_workers=min(workers, len(candidate_entries))) as executor:
                    return list(executor.map(load_entry_bundle, candidate_entries))

            def format_progress_date(value: str | None) -> str:
                return value[:10] if value else "unknown"

            existing_urls = self.database.get_all_news_urls()
            latest_db_published_at = self.database.get_latest_news_published_at()
            latest_db_url = self.database.get_latest_news_url()
            latest_db_dt = parse_flexible_datetime(str(latest_db_published_at)) if latest_db_published_at else None

            entries = []
            stored = 0
            skipped_existing = 0
            scanned_pages = 0
            scanned_entries = 0
            processed_candidates = 0
            latest_published_at = None
            current_crawled_published_at = None
            if effective_sync_mode == "catch_up":
                effective_page_limit = (
                    requested_page_limit
                    if requested_page_limit is not None
                    else max(page_limit, int(os.getenv("NEWS_CATCHUP_MAX_PAGES", "200")))
                )
                emit(
                    f"开始新闻增量补抓：db_latest={latest_db_published_at or 'none'}，db_latest_url={latest_db_url or 'none'}，max_pages={effective_page_limit}，workers={workers}"
                )
                reached_db_latest = False
                for page in range(1, effective_page_limit + 1):
                    scanned_pages = page
                    page_entries = self.news_pipeline.fetch_listing_entries_for_page(page)
                    if not page_entries:
                        break

                    page_newer = 0
                    page_old = 0
                    page_skipped_existing = 0
                    candidate_entries = []
                    for entry in page_entries:
                        if latest_db_url and entry["url"] == latest_db_url:
                            reached_db_latest = True
                            emit(f"[sync-news] page={page} 命中库内最新文章，停止继续翻页")
                            break
                        if entry["url"] in existing_urls:
                            page_skipped_existing += 1
                            continue
                        candidate_entries.append(entry)

                    page_results = load_page_results(candidate_entries)

                    for result in page_results:
                        entry = result["entry"]
                        if not result["ok"]:
                            self.database.insert_job_log(
                                NEWS_SOURCE_KEY,
                                "failed",
                                f"新闻同步跳过：{entry['url']} -> {result['error']}",
                            )
                            emit(f"[sync-news] 跳过坏文章：{entry['url']} -> {result['error']}")
                            continue

                        article = result["article"]
                        analysis = result["analysis"]
                        article_dt = parse_flexible_datetime(str(article["published_at"])) if article.get("published_at") else None
                        if article.get("published_at"):
                            current_crawled_published_at = article["published_at"]

                        if latest_db_dt and article_dt and article_dt <= latest_db_dt:
                            page_old += 1
                            continue

                        self.database.upsert_news_article(article, analysis, updated_at)
                        existing_urls.add(article["url"])
                        entries.append(entry)
                        processed_candidates += 1
                        stored += 1
                        page_newer += 1
                        if article.get("published_at") and (
                            latest_published_at is None or article["published_at"] > latest_published_at
                        ):
                            latest_published_at = article["published_at"]

                    skipped_existing += page_skipped_existing
                    emit(
                        f"[sync-news] page={page} 新增 {page_newer} 篇，已存在跳过 {page_skipped_existing} 篇，旧数据命中 {page_old} 篇，当前处理到 {format_progress_date(current_crawled_published_at)}"
                    )
                    if reached_db_latest:
                        break
            else:
                emit(
                    f"开始新闻同步：按最近页扫描，mode={effective_sync_mode}，page_limit={page_limit}，article_limit={article_limit}，workers={workers}"
                )
                for page in range(1, page_limit + 1):
                    if article_limit is not None and processed_candidates >= article_limit:
                        emit(f"[sync-news] 已达到 article_limit={article_limit}，停止同步")
                        break

                    scanned_pages = page
                    page_entries = self.news_pipeline.fetch_listing_entries_for_page(page)
                    if not page_entries:
                        emit(f"[sync-news] page={page} 未返回列表数据，停止同步")
                        break

                    scanned_entries += len(page_entries)
                    page_skipped_existing = 0
                    candidate_entries = []
                    for entry in page_entries:
                        if entry["url"] in existing_urls:
                            page_skipped_existing += 1
                            continue
                        candidate_entries.append(entry)

                    remaining_capacity = None
                    if article_limit is not None:
                        remaining_capacity = max(0, article_limit - processed_candidates)
                        candidate_entries = candidate_entries[:remaining_capacity]

                    page_candidate_count = len(candidate_entries)
                    emit(
                        f"[sync-news] page={page} 列表 {len(page_entries)} 篇，已存在跳过 {page_skipped_existing} 篇，待抓取缺失 {page_candidate_count} 篇"
                    )

                    page_results = load_page_results(candidate_entries)
                    page_stored = 0
                    page_failed = 0
                    for result in page_results:
                        entry = result["entry"]
                        processed_candidates += 1
                        if not result["ok"]:
                            page_failed += 1
                            self.database.insert_job_log(
                                NEWS_SOURCE_KEY,
                                "failed",
                                f"新闻同步跳过：{entry['url']} -> {result['error']}",
                            )
                            emit(f"[sync-news] 跳过坏文章：{entry['url']} -> {result['error']}")
                            continue
                        article = result["article"]
                        analysis = result["analysis"]
                        if article.get("published_at"):
                            current_crawled_published_at = article["published_at"]
                        self.database.upsert_news_article(article, analysis, updated_at)
                        existing_urls.add(article["url"])
                        entries.append(entry)
                        stored += 1
                        page_stored += 1
                        if article.get("published_at") and (
                            latest_published_at is None or article["published_at"] > latest_published_at
                        ):
                            latest_published_at = article["published_at"]

                    skipped_existing += page_skipped_existing
                    emit(
                        f"[sync-news] page={page} 完成：本页新增 {page_stored} 篇，失败 {page_failed} 篇，累计新增 {stored} 篇，累计已存在跳过 {skipped_existing} 篇，当前处理到 {format_progress_date(current_crawled_published_at)}"
                    )

            total_count = self.database.count_news_articles()
            self.database.upsert_source_status(
                NEWS_SOURCE_KEY,
                {
                    "source": "OilPrice",
                    "mode": effective_sync_mode,
                    "page_limit": page_limit,
                    "article_limit": article_limit,
                    "workers": workers,
                    "fetched_count": len(entries),
                    "processed_candidate_count": processed_candidates,
                    "stored_count": stored,
                    "skipped_existing_count": skipped_existing,
                    "scanned_pages": scanned_pages,
                    "scanned_entries": scanned_entries,
                    "total_count": total_count,
                    "latest_published_at": latest_published_at,
                    "db_latest_before_sync": latest_db_published_at,
                },
            )
            self.database.insert_job_log(
                NEWS_SOURCE_KEY,
                "success",
                (
                    f"{'增量补抓' if effective_sync_mode == 'catch_up' else '最近页同步'}完成：新增 {stored} 篇，"
                    f"已存在跳过 {skipped_existing} 篇，库内累计 {total_count} 篇"
                ),
            )
            return JobResult(
                NEWS_SOURCE_KEY,
                True,
                updated_at,
                {
                    "mode": effective_sync_mode,
                    "fetched_count": len(entries),
                    "processed_candidate_count": processed_candidates,
                    "stored_count": stored,
                    "workers": workers,
                    "skipped_existing_count": skipped_existing,
                    "scanned_pages": scanned_pages,
                    "scanned_entries": scanned_entries,
                    "total_count": total_count,
                    "db_latest_before_sync": latest_db_published_at,
                },
            )
        except Exception as error:
            self.database.insert_job_log(NEWS_SOURCE_KEY, "failed", str(error))
            if progress_callback:
                progress_callback(f"[sync-news] 失败：{error}")
            raise
        finally:
            self._news_lock.release()

    def import_historical_news(
        self,
        batch_size: int = 200,
        limit: int | None = None,
        resume: bool = True,
        workers: int = 1,
        executor_kind: str = "auto",
        progress_callback: Callable[[str], None] | None = None,
    ) -> JobResult:
        if not self._news_lock.acquire(blocking=False):
            raise RuntimeError("新闻任务正在运行中")
        if not HISTORICAL_NEWS_DIR.exists():
            raise FileNotFoundError(f"历史新闻目录不存在：{HISTORICAL_NEWS_DIR}")

        updated_at = iso_now()
        try:
            def emit(message: str) -> None:
                if progress_callback:
                    progress_callback(message)

            status_payload = self.database.get_source_status().get(NEWS_SOURCE_KEY, {}).get("payload", {})
            start_after_name = status_payload.get("last_imported_file") if resume else None
            summary_index = self.news_pipeline.load_summary_index(HISTORICAL_NEWS_SUMMARY_CSV)
            all_files = sorted(HISTORICAL_NEWS_DIR.glob("*.txt"))
            if start_after_name:
                all_files = [path for path in all_files if path.name > start_after_name]
            if limit is not None:
                all_files = all_files[:limit]
            workers = max(1, workers)
            existing_urls = self.database.get_all_news_urls()
            skipped_existing = 0
            pending_files: list[Path] = []
            last_file = start_after_name
            for file_path in all_files:
                try:
                    metadata = self.news_pipeline.resolve_historical_metadata(file_path, summary_index)
                except Exception:
                    pending_files.append(file_path)
                    continue
                if metadata["url"] in existing_urls:
                    skipped_existing += 1
                    last_file = file_path.name
                    continue
                pending_files.append(file_path)

            emit(
                f"开始导入历史新闻：原始候选 {len(all_files)} 篇，已存在跳过 {skipped_existing} 篇，待处理 {len(pending_files)} 篇，batch_size={batch_size}，workers={workers}，executor={executor_kind}，resume={'on' if resume else 'off'}"
            )

            imported = 0
            processed = 0
            failed = 0
            scanned = 0
            matched_urls = 0
            latest_published_at = None
            def flush_progress() -> None:
                total_count = self.database.count_news_articles()
                self.database.upsert_source_status(
                    NEWS_SOURCE_KEY,
                    {
                        "source": "OilPrice",
                        "mode": "historical_import",
                        "scanned_count": scanned,
                        "processed_count": processed,
                        "imported_count": imported,
                        "failed_count": failed,
                        "skipped_existing_count": skipped_existing,
                        "matched_url_count": matched_urls,
                        "total_count": total_count,
                        "last_imported_file": last_file,
                        "latest_published_at": latest_published_at,
                        "historical_dir": str(HISTORICAL_NEWS_DIR),
                        "workers": workers,
                    },
                )
                self.database.insert_job_log(
                    NEWS_SOURCE_KEY,
                    "progress",
                    f"历史新闻已扫描 {scanned} 篇，成功 {processed} 篇，失败 {failed} 篇，跳过已存在 {skipped_existing} 篇，当前文件 {last_file}",
                )
                emit(
                    f"[import] 本次已扫描 {scanned} 篇，成功 {processed} 篇，失败 {failed} 篇，跳过已存在 {skipped_existing} 篇，库内累计 {total_count} 篇，summary 匹配 {matched_urls} 篇，当前文件 {last_file}"
                )

            def handle_result(result: dict[str, Any]) -> None:
                nonlocal imported, processed, failed, scanned, matched_urls, last_file, latest_published_at
                last_file = result["file_name"]
                scanned += 1
                if result["ok"]:
                    article = result["article"]
                    analysis = result["analysis"]
                    self.database.upsert_news_article(article, analysis, updated_at)
                    processed += 1
                    imported += 1
                    if article.get("summary_matched"):
                        matched_urls += 1
                    if article.get("published_at") and (
                        latest_published_at is None or article["published_at"] > latest_published_at
                    ):
                        latest_published_at = article["published_at"]
                else:
                    failed += 1
                    self.database.insert_job_log(
                        NEWS_SOURCE_KEY,
                        "failed",
                        f"历史新闻跳过：{result['file_name']} -> {result['error']}",
                    )
                    emit(f"[import] 跳过坏文件：{result['file_name']} -> {result['error']}")

                if scanned % batch_size == 0:
                    flush_progress()

            def process_file_local(file_path: Path) -> dict[str, Any]:
                try:
                    article = self.news_pipeline.build_historical_article(file_path, summary_index)
                    analysis = self.news_pipeline.analyze_article(article)
                    return {
                        "ok": True,
                        "file_name": file_path.name,
                        "article": article,
                        "analysis": analysis,
                    }
                except Exception as file_error:
                    return {
                        "ok": False,
                        "file_name": file_path.name,
                        "error": str(file_error),
                    }

            if workers == 1:
                for file_path in pending_files:
                    handle_result(process_file_local(file_path))
            else:
                chunksize = max(1, min(32, batch_size // max(1, workers)))
                used_executor = executor_kind
                if executor_kind in {"auto", "process"}:
                    try:
                        with ProcessPoolExecutor(
                            max_workers=workers,
                            initializer=_historical_import_worker_init,
                            initargs=(str(HISTORICAL_NEWS_SUMMARY_CSV),),
                        ) as executor:
                            for result in executor.map(
                                _historical_import_worker_process,
                                [str(path) for path in pending_files],
                                chunksize=chunksize,
                            ):
                                handle_result(result)
                        used_executor = "process"
                    except PermissionError as process_error:
                        if executor_kind == "process":
                            raise
                        used_executor = "thread"
                        emit(f"[import] 进程池不可用，自动回退到线程池：{process_error}")

                if used_executor == "thread":
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        for result in executor.map(process_file_local, pending_files):
                            handle_result(result)

            if scanned % batch_size != 0 and scanned > 0:
                flush_progress()

            total_count = self.database.count_news_articles()
            self.database.upsert_source_status(
                NEWS_SOURCE_KEY,
                {
                    "source": "OilPrice",
                    "mode": "historical_import",
                    "scanned_count": scanned,
                    "processed_count": processed,
                    "imported_count": imported,
                    "failed_count": failed,
                    "skipped_existing_count": skipped_existing,
                    "matched_url_count": matched_urls,
                    "total_count": total_count,
                    "last_imported_file": last_file,
                    "latest_published_at": latest_published_at,
                    "historical_dir": str(HISTORICAL_NEWS_DIR),
                    "resume_enabled": resume,
                    "workers": workers,
                },
            )
            self.database.insert_job_log(
                NEWS_SOURCE_KEY,
                "success",
                f"历史新闻导入完成：扫描 {scanned} 篇，成功 {processed} 篇，失败 {failed} 篇，跳过已存在 {skipped_existing} 篇，库内累计 {total_count} 篇",
            )
            emit(
                f"[import] 完成：扫描 {scanned} 篇，成功 {processed} 篇，失败 {failed} 篇，跳过已存在 {skipped_existing} 篇，库内累计 {total_count} 篇，summary 匹配 {matched_urls} 篇，最后文件 {last_file}"
            )
            return JobResult(
                NEWS_SOURCE_KEY,
                True,
                updated_at,
                {
                    "scanned_count": scanned,
                    "processed_count": processed,
                    "imported_count": imported,
                    "failed_count": failed,
                    "skipped_existing_count": skipped_existing,
                    "matched_url_count": matched_urls,
                    "total_count": total_count,
                    "last_imported_file": last_file,
                },
            )
        except Exception as error:
            self.database.insert_job_log(NEWS_SOURCE_KEY, "failed", f"历史导入失败：{error}")
            emit(f"[import] 失败：{error}")
            raise
        finally:
            self._news_lock.release()

    def reanalyze_news(
        self,
        batch_size: int = 200,
        limit: int | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> JobResult:
        if not self._news_lock.acquire(blocking=False):
            raise RuntimeError("新闻任务正在运行中")
        updated_at = iso_now()
        try:
            def emit(message: str) -> None:
                if progress_callback:
                    progress_callback(message)

            total_count = self.database.count_news_articles()
            target_count = min(total_count, limit) if limit is not None else total_count
            emit(f"开始重分析新闻：目标 {target_count} 篇，batch_size={batch_size}")
            processed = 0
            offset = 0
            while processed < target_count:
                current_limit = min(batch_size, target_count - processed)
                batch = self.database.get_news_reanalysis_batch(limit=current_limit, offset=offset)
                if not batch:
                    break
                for article in batch:
                    analysis = self.news_pipeline.analyze_article(article)
                    self.database.update_news_analysis(article["id"], analysis, updated_at)
                    processed += 1
                offset += len(batch)
                self.database.upsert_source_status(
                    NEWS_SOURCE_KEY,
                    {
                        "source": "OilPrice",
                        "mode": "reanalyze",
                        "processed_count": processed,
                        "total_count": total_count,
                        "analyzer_version": ANALYZER_VERSION,
                    },
                )
                emit(f"[reanalyze] 已处理 {processed}/{target_count} 篇")
            self.database.insert_job_log(
                NEWS_SOURCE_KEY,
                "success",
                f"新闻重分析完成：{processed} 篇",
            )
            emit(f"[reanalyze] 完成：共处理 {processed} 篇")
            return JobResult(
                NEWS_SOURCE_KEY,
                True,
                updated_at,
                {"processed_count": processed, "total_count": total_count},
            )
        except Exception as error:
            self.database.insert_job_log(NEWS_SOURCE_KEY, "failed", f"重分析失败：{error}")
            emit(f"[reanalyze] 失败：{error}")
            raise
        finally:
            self._news_lock.release()

    def get_news_list(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        limit: int = 80,
    ) -> dict[str, Any]:
        items = self.database.get_news_articles(start=start, end=end, query=query, limit=limit)
        return {
            "items": items,
            "total": self.database.count_news_articles(start=start, end=end, query=query),
            "updatedAt": iso_now(),
        }

    def get_news_overview(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        limit: int = 120,
    ) -> dict[str, Any]:
        items = self.database.get_news_articles(start=start, end=end, query=query, limit=limit)
        source_status = self.database.get_source_status().get(NEWS_SOURCE_KEY, {})
        if not items:
            return {
                "summary": {
                    "articleCount": 0,
                    "averageSentiment": "0.00",
                    "positiveCount": 0,
                    "negativeCount": 0,
                    "averageRisk": 0,
                    "averageMentions": 0,
                },
                "sentimentSeries": [],
                "regionalRiskData": [],
                "entityTags": [],
                "topicDistribution": [],
                "sourceStatus": source_status,
                "updatedAt": iso_now(),
            }

        average_sentiment = sum(item["sentiment"] for item in items) / len(items)
        average_risk = sum(item["risk"] for item in items) / len(items)
        average_mentions = sum(item["mentionCount"] for item in items) / len(items)
        positive_count = len([item for item in items if item["sentiment"] > 0.05])
        negative_count = len([item for item in items if item["sentiment"] < -0.05])

        sentiment_series = [
            {
                "label": f"{item['month']}/{item['day']}" if item["month"] and item["day"] else item["publishedDate"],
                "sentiment": item["sentiment"],
                "title": item["title"],
                "date": item["publishedDate"],
            }
            for item in reversed(items[:10])
        ]

        regional_counter: dict[str, int] = {}
        entity_counter: dict[str, int] = {}
        topic_counter: dict[str, int] = {}
        for item in items:
            for geo in item.get("geoEntities", []):
                regional_counter[geo["label"]] = regional_counter.get(geo["label"], 0) + int(geo.get("count", 0))
            for entity in item.get("macroEntities", []):
                entity_counter[entity["label"]] = entity_counter.get(entity["label"], 0) + int(entity.get("count", 0))
            for topic in item.get("topicTags", []):
                topic_counter[topic["label"]] = topic_counter.get(topic["label"], 0) + int(topic.get("count", 0))

        top_regional = sorted(regional_counter.items(), key=lambda pair: pair[1], reverse=True)[:6]
        max_regional = max((value for _, value in top_regional), default=1)
        regional_risk_data = [
            {
                "label": label,
                "count": value,
                "value": int(round((value / max_regional) * 100)) if max_regional else 0,
            }
            for label, value in top_regional
        ]
        entity_tags = [label for label, _ in sorted(entity_counter.items(), key=lambda pair: pair[1], reverse=True)[:12]]
        topic_distribution = [
            {"label": label, "count": value}
            for label, value in sorted(topic_counter.items(), key=lambda pair: pair[1], reverse=True)[:5]
        ]

        return {
            "summary": {
                "articleCount": len(items),
                "averageSentiment": f"{average_sentiment:.2f}",
                "positiveCount": positive_count,
                "negativeCount": negative_count,
                "averageRisk": int(round(average_risk)),
                "averageMentions": int(round(average_mentions)),
            },
            "sentimentSeries": sentiment_series,
            "regionalRiskData": regional_risk_data,
            "entityTags": entity_tags,
            "topicDistribution": topic_distribution,
            "sourceStatus": source_status,
            "updatedAt": iso_now(),
        }

    def get_news_detail(self, article_id: str) -> dict[str, Any]:
        item = self.database.get_news_article_detail(article_id)
        if not item:
            raise ValueError("新闻不存在")
        return item

    def _load_model_module(self):
        sys.path.insert(0, str(MODEL_SOURCE_DIR))
        import final_solution
        from sklearn.linear_model import LogisticRegression as SklearnLogisticRegression

        original_loader = final_solution.load_and_prepare_data

        def safe_logistic_regression(*args, **kwargs):
            kwargs["n_jobs"] = 1
            return SklearnLogisticRegression(*args, **kwargs)

        def normalized_load_and_prepare_data(file_path):
            df, primary_target, targets, factor_cols = original_loader(file_path)
            df = _normalize_model_return_targets(
                df,
                primary_target=primary_target,
                targets=targets,
                regression_target_col=final_solution.REGRESSION_TARGET_COL,
                horizon=int(final_solution.REGRESSION_HORIZON),
            )
            return df, primary_target, targets, factor_cols

        final_solution.load_and_prepare_data = normalized_load_and_prepare_data
        final_solution.LogisticRegression = safe_logistic_regression
        _apply_quantile_prediction_guardrails(final_solution)

        return final_solution

    def _compute_top_movers(self, frame: pd.DataFrame, selected_factors: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        numeric_frame = frame.select_dtypes(include=["number"]).tail(90)
        if numeric_frame.empty:
            return [], {
                "selectedFactorCount": len(selected_factors),
                "validFactorCount": 0,
                "skippedFactorCount": len(selected_factors),
                "computedFrom": "model_prepared_frame",
            }

        latest = numeric_frame.iloc[-1]
        previous = numeric_frame.iloc[:-1]
        movers = []
        skipped_count = 0

        for factor in selected_factors:
            if factor not in numeric_frame.columns:
                skipped_count += 1
                continue

            latest_value = pd.to_numeric(pd.Series([latest[factor]]), errors="coerce").iloc[0]
            history = pd.to_numeric(previous[factor], errors="coerce").dropna()
            if pd.isna(latest_value) or history.empty:
                skipped_count += 1
                continue

            mean = float(history.mean())
            std = float(history.std()) if len(history) > 1 else 0.0
            if not math.isfinite(mean) or not math.isfinite(std):
                skipped_count += 1
                continue

            if std == 0:
                z_score = 0.0
            else:
                z_score = float((float(latest_value) - mean) / std)

            if not math.isfinite(z_score):
                skipped_count += 1
                continue

            movers.append(
                {
                    "factor": factor,
                    "value": f"{float(latest_value):.4f}",
                    "zScore": round(z_score, 2),
                    "direction": "up" if z_score >= 0 else "down",
                    "description": "最近一期相对历史均值偏离显著",
                }
            )

        movers.sort(key=lambda item: abs(item["zScore"]), reverse=True)
        return movers[:8], {
            "selectedFactorCount": len(selected_factors),
            "validFactorCount": len(movers),
            "skippedFactorCount": skipped_count,
            "computedFrom": "model_prepared_frame",
        }

    def _compute_regime(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        if frame.empty:
            return [
                {"subject": "Supply", "value": 50, "fullMark": 100},
                {"subject": "Demand", "value": 50, "fullMark": 100},
                {"subject": "Geo-Risk", "value": 50, "fullMark": 100},
                {"subject": "Macro", "value": 50, "fullMark": 100},
                {"subject": "Trend", "value": 50, "fullMark": 100},
                {"subject": "Vol", "value": 50, "fullMark": 100},
            ]

        regime_window = frame.tail(252).reset_index(drop=True)

        def clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
            return max(lower, min(upper, value))

        def to_numeric_series(column: str) -> pd.Series:
            if column not in regime_window.columns:
                return pd.Series(dtype=float)
            return pd.to_numeric(regime_window[column], errors="coerce").dropna().reset_index(drop=True)

        def stable_percentile_signal(series: pd.Series) -> float:
            if series.empty:
                return 0.0
            current = float(series.iloc[-1])
            lower = int((series < current).sum())
            equal = int((series == current).sum())
            percentile = (lower + equal * 0.5) / len(series)
            return clamp((percentile - 0.5) * 2.0)

        def pct_change_signal(series: pd.Series, periods: int) -> float:
            if len(series) <= periods:
                return 0.0
            base_value = float(series.iloc[-periods - 1])
            current = float(series.iloc[-1])
            if math.isclose(base_value, 0.0, abs_tol=1e-12):
                return 0.0
            return clamp(((current / base_value) - 1.0) / 0.2)

        def freshness_weight(series: pd.Series) -> float:
            if len(series) < 2:
                return 0.35
            current = float(series.iloc[-1])
            stagnant_steps = 0
            for index in range(len(series) - 2, -1, -1):
                candidate = float(series.iloc[index])
                if math.isclose(candidate, current, rel_tol=1e-9, abs_tol=1e-9):
                    stagnant_steps += 1
                    continue
                break
            if stagnant_steps <= 20:
                return 1.0
            if stagnant_steps >= 90:
                return 0.35
            progress = (stagnant_steps - 20) / 70
            return 1.0 - progress * 0.65

        def score_from_signal(raw_signal: float, weight: float = 1.0) -> int:
            scaled = 50 + clamp(raw_signal) * max(0.35, min(1.0, weight)) * 35
            return int(round(max(0, min(100, scaled))))

        opec_supply = to_numeric_series("OPEC_supply")
        total_consumption = to_numeric_series("Total_con")
        geo_risk = to_numeric_series("GPR")
        dxy_price = to_numeric_series("DXY_Price")
        wti_close = to_numeric_series("WTI_Close")
        wti_ma20 = to_numeric_series("WTI_MA_20")
        wti_ma5 = to_numeric_series("WTI_MA_5")
        wti_ma60 = to_numeric_series("WTI_MA_60")
        wti_volatility = to_numeric_series("WTI_Volatility_20d")

        trend_gap = (wti_close / wti_ma20.replace(0, pd.NA) - 1.0).replace([pd.NA, math.inf, -math.inf], pd.NA).dropna().reset_index(drop=True)
        ma_stack = (wti_ma5 / wti_ma60.replace(0, pd.NA) - 1.0).replace([pd.NA, math.inf, -math.inf], pd.NA).dropna().reset_index(drop=True)

        supply_signal = -0.6 * stable_percentile_signal(opec_supply) - 0.4 * pct_change_signal(opec_supply, 20)
        demand_signal = 0.5 * stable_percentile_signal(total_consumption) + 0.5 * pct_change_signal(total_consumption, 60)
        geo_risk_signal = 0.7 * stable_percentile_signal(geo_risk) + 0.3 * pct_change_signal(geo_risk, 20)
        macro_signal = -0.7 * stable_percentile_signal(dxy_price) - 0.3 * pct_change_signal(dxy_price, 20)
        trend_signal = 0.55 * stable_percentile_signal(trend_gap) + 0.45 * stable_percentile_signal(ma_stack)
        volatility_signal = 0.8 * stable_percentile_signal(wti_volatility) + 0.2 * pct_change_signal(wti_volatility, 20)

        return [
            {"subject": "Supply", "value": score_from_signal(supply_signal, freshness_weight(opec_supply)), "fullMark": 100},
            {"subject": "Demand", "value": score_from_signal(demand_signal, freshness_weight(total_consumption)), "fullMark": 100},
            {"subject": "Geo-Risk", "value": score_from_signal(geo_risk_signal, freshness_weight(geo_risk)), "fullMark": 100},
            {"subject": "Macro", "value": score_from_signal(macro_signal, freshness_weight(dxy_price)), "fullMark": 100},
            {"subject": "Trend", "value": score_from_signal(trend_signal), "fullMark": 100},
            {"subject": "Vol", "value": score_from_signal(volatility_signal, freshness_weight(wti_volatility)), "fullMark": 100},
        ]

    def _compute_country_risk(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        latest = frame.iloc[-1]
        country_columns = [column for column in frame.columns if column.startswith("GPRC_")]
        selected = []
        for column in country_columns:
            value = float(pd.to_numeric(latest[column], errors="coerce") or 0.0)
            selected.append((column, value))
        selected.sort(key=lambda item: item[1], reverse=True)
        items = []
        max_value = max([value for _, value in selected[:6]] or [1.0])
        for column, value in selected[:6]:
            items.append(
                {
                    "country": column,
                    "value": round(value, 2),
                    "max": round(max_value, 2),
                    "color": "var(--status-danger)" if value >= max_value * 0.8 else "var(--status-warning)",
                }
            )
        return items

    def _compute_signal_blocks(
        self,
        latest_factor_row: pd.Series,
        latest_prediction: pd.Series,
    ) -> list[dict[str, Any]]:
        cross_value = "WTI_Golden_Cross" if float(latest_factor_row.get("WTI_Golden_Cross", 0)) == 1 else "WTI_Death_Cross"
        cross_badge = "TRUE" if float(latest_factor_row.get("WTI_Golden_Cross", 0)) == 1 or float(latest_factor_row.get("WTI_Death_Cross", 0)) == 1 else "FALSE"
        tone = float(latest_factor_row.get("tone_mean", 0.0))
        risk_level = str(latest_prediction.get("Risk_Level", "中等风险"))
        risk_text = "LONG" if float(latest_prediction.get("Predicted_1d", 0.0)) >= 0 else "SHORT"
        return [
            {
                "title": "Golden/Death Cross Status",
                "value": cross_value,
                "badge": cross_badge,
                "badgeClass": "dashboard-signal-card__badge--positive" if cross_value == "WTI_Golden_Cross" else "dashboard-signal-card__badge--danger",
                "note": "基于最新因子快照生成。",
            },
            {
                "title": "NLP Tone (tone_mean)",
                "value": f"{tone:.2f}",
                "badge": "OPTIMISTIC" if tone >= 0 else "PESSIMISTIC",
                "badgeClass": "dashboard-signal-card__badge--positive" if tone >= 0 else "dashboard-signal-card__badge--warning",
                "note": "来源于 factors_WTI 中的文本情绪因子。",
                "progress": max(0, min(100, int(abs(tone) * 100))),
                "progressDirection": "positive" if tone >= 0 else "negative",
            },
            {
                "title": "Model Inference Output",
                "value": f"Predicted_1d: {float(latest_prediction.get('Predicted_1d', 0.0)):.3f}",
                "badge": risk_text,
                "badgeClass": "dashboard-signal-card__badge--positive" if risk_text == "LONG" else "dashboard-signal-card__badge--danger",
                "note": f"最新风险等级：{risk_level}",
            },
        ]

    def _extract_native_price_columns(self, predictions: pd.DataFrame) -> dict[str, str]:
        horizon_days = None
        q50_column = None
        for column in predictions.columns:
            match = re.fullmatch(r"Pred_Fwd_(\d+)d_Close_Q50", str(column))
            if match:
                horizon_days = int(match.group(1))
                q50_column = str(column)
                break
        if horizon_days is None or q50_column is None:
            raise RuntimeError("正确价格预测算法未产出远期中位价格列，无法构建价格区间预测")
        return {
            "horizon_days": str(horizon_days),
            "q10": f"Pred_Fwd_{horizon_days}d_Close_Q10",
            "q50": q50_column,
            "q90": f"Pred_Fwd_{horizon_days}d_Close_Q90",
            "base_close": f"Fwd_Base_{FORECAST_PRICE_COL}",
            "actual_close": f"Actual_Fwd_{horizon_days}d_Close",
            "actual_return": f"Actual_Fwd{horizon_days}d_Cum",
        }

    def _resolve_native_forecast_base_close(
        self,
        frame: pd.DataFrame,
        latest_projection_row: pd.Series,
        columns: dict[str, str],
        latest_factor_row: pd.Series,
    ) -> float:
        base_close_column = columns.get("base_close", "")
        if base_close_column and base_close_column in latest_projection_row.index:
            base_close = float(pd.to_numeric(latest_projection_row.get(base_close_column), errors="coerce") or 0.0)
            if base_close > 0:
                return base_close

        projection_date = pd.to_datetime(latest_projection_row.get("Date"), errors="coerce")
        dated_frame = frame.copy()
        dated_frame["Date"] = pd.to_datetime(dated_frame["Date"], errors="coerce")
        if pd.notna(projection_date):
            matched_rows = dated_frame.index[dated_frame["Date"] == projection_date].tolist()
            if matched_rows:
                matched_index = matched_rows[-1]
                if matched_index > 0:
                    inferred_base_close = float(
                        pd.to_numeric(
                            dated_frame.iloc[matched_index - 1].get(FORECAST_PRICE_COL, dated_frame.iloc[matched_index - 1].get("Price", 0.0)),
                            errors="coerce",
                        )
                        or 0.0
                    )
                    if inferred_base_close > 0:
                        return inferred_base_close

        fallback_close = float(pd.to_numeric(latest_factor_row.get(FORECAST_PRICE_COL, latest_factor_row.get("Price", 0.0)), errors="coerce") or 0.0)
        return fallback_close

    def _build_native_price_forecast(
        self,
        frame: pd.DataFrame,
        predictions: pd.DataFrame,
        latest_prediction: pd.Series,
        latest_factor_row: pd.Series,
    ) -> dict[str, Any]:
        columns = self._extract_native_price_columns(predictions)
        horizon_days = int(columns["horizon_days"])
        missing_columns = [key for key in ("q10", "q50", "q90") if columns[key] not in predictions.columns]
        if missing_columns:
            raise RuntimeError("正确价格预测算法缺少必要的分位数价格列，无法构建价格区间预测")

        price_predictions = predictions.copy()
        price_predictions["Date"] = pd.to_datetime(price_predictions["Date"])
        for column in (columns["q10"], columns["q50"], columns["q90"]):
            price_predictions[column] = pd.to_numeric(price_predictions[column], errors="coerce")
        valid_predictions = price_predictions.dropna(subset=[columns["q10"], columns["q50"], columns["q90"]]).reset_index(drop=True)
        if valid_predictions.empty:
            raise RuntimeError("正确价格预测算法未产出有效的价格区间结果")

        latest_projection_row = valid_predictions.iloc[-1]
        base_close = self._resolve_native_forecast_base_close(frame, latest_projection_row, columns, latest_factor_row)
        lower_price = float(latest_projection_row[columns["q10"]])
        median_price = float(latest_projection_row[columns["q50"]])
        upper_price = float(latest_projection_row[columns["q90"]])
        expected_return = 0.0 if base_close == 0 else (median_price / base_close) - 1.0
        lower_return = 0.0 if base_close == 0 else (lower_price / base_close) - 1.0
        upper_return = 0.0 if base_close == 0 else (upper_price / base_close) - 1.0

        recent_projection_rows = valid_predictions.tail(horizon_days).reset_index(drop=True)
        latest_history_date = pd.to_datetime(frame["Date"]).max()
        future_dates = pd.bdate_range(latest_history_date + pd.offsets.BDay(1), periods=len(recent_projection_rows))
        projection = []
        for index, row in recent_projection_rows.iterrows():
            projection.append(
                {
                    "date": future_dates[index].strftime("%Y-%m-%d"),
                    "prediction": round(float(row[columns["q50"]]), 2),
                    "lowerBound": round(min(float(row[columns["q10"]]), float(row[columns["q90"]])), 2),
                    "upperBound": round(max(float(row[columns["q10"]]), float(row[columns["q90"]])), 2),
                }
            )

        return {
            "horizonDays": horizon_days,
            "asOf": pd.Timestamp(latest_projection_row["Date"]).strftime("%Y-%m-%d"),
            "latestClose": round(base_close, 2),
            "baseClose": round(base_close, 2),
            "expectedPrice": round(median_price, 2),
            "priceInterval": {
                "lower": round(min(lower_price, upper_price), 2),
                "median": round(median_price, 2),
                "upper": round(max(lower_price, upper_price), 2),
            },
            "returnInterval": {
                "lower": round(min(lower_return, upper_return), 6),
                "median": round(expected_return, 6),
                "upper": round(max(lower_return, upper_return), 6),
            },
            "expectedReturn": round(expected_return, 6),
            "intervalWidth": round(abs(upper_price - lower_price), 2),
            "projection": projection,
            "method": f"native_{horizon_days}d_quantile_price_projection",
            "signal": {
                "predicted1d": round(float(pd.to_numeric(latest_prediction.get("Predicted_1d", 0.0), errors="coerce") or 0.0), 6),
                "predicted5d": round(float(pd.to_numeric(latest_prediction.get("Predicted_5d", 0.0), errors="coerce") or 0.0), 6),
                "predicted20d": round(float(pd.to_numeric(latest_prediction.get("Predicted_20d", 0.0), errors="coerce") or 0.0), 6),
                "consensus": str(latest_prediction.get("Consensus", "不一致")),
                "riskLevel": str(latest_prediction.get("Risk_Level", "中等风险")),
                "riskIndex": round(float(pd.to_numeric(latest_prediction.get("Risk_Index", 0.0), errors="coerce") or 0.0), 2),
                "confidence": str(latest_prediction.get("Confidence", "中等置信度")),
            },
        }

    def get_market_chart(self, symbol: str, range_key: str, chart_kind: str = "main") -> dict[str, Any]:
        profile = resolve_market_chart_profile(range_key, chart_kind=chart_kind)
        if profile["layer"] == "aggregate":
            rows = self.database.get_market_aggregate_bars(symbol, profile["granularity"], profile["limit"])
            source_layer = "aggregate"
            if not rows:
                source_limit = resolve_display_source_limit(profile)
                source_rows = self.database.get_market_bars(symbol, profile["fallback_granularity"], source_limit)
                rows = aggregate_market_bars(source_rows, profile["granularity"])[-profile["limit"] :]
                source_layer = "aggregate_fallback"
        else:
            rows = self.database.get_market_bars(symbol, profile["granularity"], profile["limit"])
            source_layer = "raw"
        if symbol == "WTI_Close" and rows:
            closes: list[float] = []
            enriched_rows = []
            for row in rows:
                close_value = float(row["close"])
                closes.append(close_value)
                item = dict(row)
                item["price"] = round(close_value, 4)
                item["ma5"] = round(sum(closes[-5:]) / 5, 4) if len(closes) >= 5 else None
                item["ma20"] = round(sum(closes[-20:]) / 20, 4) if len(closes) >= 20 else None
                item["ma60"] = round(sum(closes[-60:]) / 60, 4) if len(closes) >= 60 else None
                enriched_rows.append(item)
            rows = enriched_rows
        return {
            "symbol": symbol,
            "range": range_key,
            "chartKind": chart_kind,
            "granularity": profile["granularity"],
            "sourceLayer": source_layer,
            "points": rows,
            "updatedAt": rows[-1]["source_updated_at"] if rows else None,
        }

    def _build_prediction_projection(
        self,
        native_forecast: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "projection": native_forecast["projection"],
            "method": native_forecast["method"],
            "horizonDays": int(native_forecast["horizonDays"]),
            "priceInterval": native_forecast["priceInterval"],
        }

    def _get_ai_pipeline(self):
        if self._ai_pipeline is None:
            self._ai_pipeline = create_pipeline(GENERATED_DIR)
        return self._ai_pipeline

    def _build_ai_prediction_input(
        self,
        latest_factor_row: pd.Series,
        native_forecast: dict[str, Any],
        top_movers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        latest_close = float(native_forecast.get("baseClose", native_forecast.get("latestClose", 0.0)) or 0.0)
        if latest_close == 0:
            latest_close = float(latest_factor_row.get("WTI_Close", latest_factor_row.get("Price", 0.0)))
        expected_return = float(native_forecast["expectedReturn"])
        predicted_price = float(native_forecast["expectedPrice"])
        lower_price = float(native_forecast["priceInterval"]["lower"])
        upper_price = float(native_forecast["priceInterval"]["upper"])
        interval_ratio = 0.0 if latest_close == 0 else abs(upper_price - lower_price) / latest_close
        downside_ratio = 0.0 if latest_close == 0 else max((latest_close - lower_price) / latest_close, 0.0)
        trend = "上涨" if expected_return > 0.01 else "下跌" if expected_return < -0.01 else "震荡"
        key_drivers = [item["factor"] for item in top_movers[:5]] or ["WTI_Close", "DXY_Price"]
        return {
            "date": str(native_forecast["asOf"])[:10],
            "horizon_days": int(native_forecast["horizonDays"]),
            "latest_close": round(latest_close, 2),
            "base_close": round(latest_close, 2),
            "wti_price": round(predicted_price, 2),
            "brent_price": round(predicted_price * 1.045, 2),
            "forecast_change_pct": round(expected_return * 100, 2),
            "forecast_band_pct": round(interval_ratio * 100, 2),
            "downside_risk_pct": round(downside_ratio * 100, 2),
            "trend": trend,
            "risk_level": str(native_forecast["signal"].get("riskLevel", "中等风险")),
            "key_drivers": key_drivers,
        }

    def _generate_ai_analysis(
        self,
        run_id: str,
        factor_as_of: str,
        output_dir: Path,
        ai_context: dict[str, Any],
        trigger_source: str,
    ) -> dict[str, Any]:
        if not self._ai_lock.acquire(blocking=False):
            raise RuntimeError("AI 分析任务正在运行中")
        try:
            def log_ai_debug(stage: str, details: dict[str, Any] | None = None) -> None:
                fields = details or {}
                message = stage if not fields else f"{stage} | " + " ".join(f"{key}={value}" for key, value in fields.items())
                self.database.insert_job_log("ai_analysis", "debug", f"{run_id} {message}")

            log_ai_debug("normalize_prediction_start", {"factorAsOf": factor_as_of, "triggerSource": trigger_source})
            prediction = normalize_prediction_payload(ai_context["prediction"], ai_context)
            log_ai_debug(
                "normalize_prediction_done",
                {
                    "date": prediction.date,
                    "horizonDays": prediction.horizon_days,
                    "riskLevel": prediction.risk_level,
                },
            )
            log_ai_debug("get_pipeline_start")
            pipeline = self._get_ai_pipeline()
            pipeline.debug_hook = log_ai_debug
            pipeline.advisor.debug_hook = log_ai_debug
            pipeline.kb._embedding_function.debug_hook = log_ai_debug
            log_ai_debug("get_pipeline_done")
            log_ai_debug("kb_ensure_loaded_start")
            pipeline.kb.ensure_loaded()
            log_ai_debug("kb_ensure_loaded_done")
            log_ai_debug("pipeline_run_start")
            report = pipeline.run(prediction)
            log_ai_debug("pipeline_run_done", {"predictionSummary": report.prediction_summary})
            log_ai_debug("save_report_start", {"outputDir": str(output_dir)})
            report_paths = pipeline.save_report(report, output_dir)
            log_ai_debug("save_report_done", {"jsonPath": report_paths["json"], "mdPath": report_paths["md"]})
            payload = {
                "headline": "AI 分析报告",
                "predictionSummary": report.prediction_summary,
                "previewSummary": report.preview_summary,
                "predictionDate": report.date,
                "defaultView": "corporate",
                "drivers": prediction.key_drivers,
                "views": {
                    "corporate": {
                        "title": "企业侧视角",
                        "body": report.corporate_advice,
                    },
                    "bank": {
                        "title": "银行侧视角",
                        "body": report.bank_advice,
                    },
                },
                "references": report.retrieved_references,
                "generatedAt": iso_now(),
                "modelRunId": run_id,
                "stale": False,
                "lastError": "",
                "triggerSource": trigger_source,
            }
            payload = self._attach_analysis_source_contract(
                payload,
                primary_source="prediction_ai_context",
                required_published_view="latest_model",
                output_key="prediction_ai_analysis",
                analysis_context_source="prediction_ai_context",
            )
            log_ai_debug("persist_output_start")
            self.database.upsert_model_output("prediction_ai_analysis", run_id, factor_as_of, payload)
            self.database.upsert_source_status(
                "ai_analysis",
                {
                    "run_id": run_id,
                    "factor_as_of": factor_as_of,
                    "prediction_date": report.date,
                    "generated_at": payload["generatedAt"],
                    "trigger_source": trigger_source,
                    "status": "success",
                    "last_error": "",
                },
            )
            log_ai_debug("persist_output_done")
            self.database.insert_job_log("ai_analysis", "success", f"AI 分析生成成功：{run_id}")
            self.database.upsert_artifact(run_id, "ai_advisory_report.json", report_paths["json"])
            self.database.upsert_artifact(run_id, "ai_advisory_report.md", report_paths["md"])
            return payload
        finally:
            self._ai_lock.release()

    def run_model(self, trigger_source: str = "manual", include_ai: bool = True) -> JobResult:
        if not self._model_lock.acquire(blocking=False):
            raise RuntimeError("模型任务正在运行中")
        run_id = uuid4().hex[:12]
        output_dir = GENERATED_DIR / "model_runs" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            frame = self.load_factor_frame()
            factor_as_of = pd.to_datetime(frame["Date"]).max().strftime("%Y-%m-%d")
            self.database.insert_model_run(run_id, trigger_source, factor_as_of)
            model = self._load_model_module()
            df, primary_target, targets, base_cols = model.load_and_prepare_data(str(WORKING_FACTORS_CSV))
            results = model.rolling_prediction(df, primary_target, targets, base_cols, train_window=756)
            model.run_strategy_grid_search(results)
            model.evaluate_and_save(results, str(output_dir))

            predictions = pd.read_csv(output_dir / "predictions.csv")
            latest_prediction = predictions.iloc[-1]
            latest_factor_row = frame.iloc[-1]
            selected_factors = results["selected_factors"][-1]["factors"]

            top_movers, top_movers_meta = self._compute_top_movers(df, selected_factors)
            regime = self._compute_regime(frame)
            country_risk = self._compute_country_risk(frame)
            signal_blocks = self._compute_signal_blocks(latest_factor_row, latest_prediction)
            native_forecast = self._build_native_price_forecast(frame, predictions, latest_prediction, latest_factor_row)
            prediction_chart = self._build_prediction_projection(native_forecast)

            prediction_summary = {
                "headline": "WTI 原油价格多因子量化预测",
                "description": "以原生分位数价格输出未来 10 个交易日价格区间与风险提示",
                "latestDate": factor_as_of,
                "forecastWindowLabel": f"未来{int(native_forecast['horizonDays'])}个交易日价格区间",
                "next10DayForecast": f"${native_forecast['priceInterval']['lower']:.2f} - ${native_forecast['priceInterval']['upper']:.2f}",
                "riskSignal": str(native_forecast["signal"]["riskLevel"]),
                "riskConfidence": str(native_forecast["signal"]["confidence"]),
                "insight": (
                    f"原模型方向信号显示 1 日 {float(latest_prediction['Predicted_1d']):+.3f}、"
                    f"5 日 {float(latest_prediction['Predicted_5d']):+.3f}，"
                    f"未来 {int(native_forecast['horizonDays'])} 个交易日中位价格预计为 "
                    f"${native_forecast['priceInterval']['median']:.2f}，"
                    f"Q10-Q90 区间为 ${native_forecast['priceInterval']['lower']:.2f} - "
                    f"${native_forecast['priceInterval']['upper']:.2f}。"
                ),
                "featureImportance": [
                    {
                        "feature": item["factor"],
                        "value": round(max(5, 100 - index * 12), 1),
                    }
                    for index, item in enumerate(top_movers[:5])
                ],
                "topMovers": top_movers,
                "priceForecast": native_forecast,
            }
            prediction_summary = self._attach_analysis_source_contract(
                prediction_summary,
                primary_source="factor_rows",
                required_published_view="latest_factors",
                output_key="prediction_summary",
                analysis_context_source="prediction_ai_context",
            )
            ai_context = {
                "prediction": self._build_ai_prediction_input(latest_factor_row, native_forecast, top_movers),
                "factorAsOf": factor_as_of,
                "topMovers": top_movers,
                "priceForecast": native_forecast,
            }
            ai_context = self._attach_analysis_source_contract(
                ai_context,
                primary_source="factor_rows",
                required_published_view="latest_factors",
                output_key="prediction_ai_context",
                analysis_context_source="prediction_ai_context",
            )

            price_ribbon = []
            ribbon_source = frame[["Date", "WTI_Close", "WTI_MA_5", "WTI_MA_20", "WTI_MA_60"]].tail(30)
            for row in ribbon_source.itertuples(index=False):
                price_ribbon.append(
                    {
                        "date": pd.Timestamp(row.Date).strftime("%Y-%m-%d"),
                        "price": round(float(row.WTI_Close), 2),
                        "ma5": round(float(row.WTI_MA_5), 2),
                        "ma20": round(float(row.WTI_MA_20), 2),
                        "ma60": round(float(row.WTI_MA_60), 2),
                    }
                )

            dashboard_overview = {
                "topMovers": top_movers,
                "topMoversMeta": top_movers_meta,
                "regime": regime,
                "countryRisk": country_risk,
                "signalBlocks": signal_blocks,
                "priceRibbon": price_ribbon,
                "modelRun": {
                    "runId": run_id,
                    "factorAsOf": factor_as_of,
                    "predictionsAsOf": str(native_forecast["asOf"])[:10],
                },
                "priceForecast": native_forecast,
            }
            dashboard_overview = self._attach_analysis_source_contract(
                dashboard_overview,
                primary_source="factor_rows",
                required_published_view="latest_factors",
                output_key="dashboard_overview",
                analysis_context_source="prediction_ai_context",
            )
            prediction_chart = self._attach_analysis_source_contract(
                prediction_chart,
                primary_source="factor_rows",
                required_published_view="latest_factors",
                output_key="prediction_chart",
                analysis_context_source="prediction_ai_context",
            )

            for key, payload in {
                "prediction_summary": prediction_summary,
                "prediction_chart": prediction_chart,
                "dashboard_overview": dashboard_overview,
                "prediction_ai_context": ai_context,
            }.items():
                self.database.upsert_model_output(key, run_id, factor_as_of, payload)

            ai_payload = None
            if include_ai:
                try:
                    ai_payload = self._generate_ai_analysis(
                        run_id=run_id,
                        factor_as_of=factor_as_of,
                        output_dir=output_dir,
                        ai_context=ai_context,
                        trigger_source=trigger_source,
                    )
                except Exception as error:
                    self.database.patch_source_status(
                        "ai_analysis",
                        {
                            "status": "failed",
                            "last_error": str(error),
                            "last_failure_at": iso_now(),
                            "run_id": run_id,
                            "factor_as_of": factor_as_of,
                        },
                    )
                    self.database.insert_job_log("ai_analysis", "failed", str(error))

            prediction_summary["aiInsightSummary"] = (
                str(ai_payload.get("previewSummary", "")).strip()
                or build_ai_preview_summary(
                    ai_payload["views"]["corporate"]["body"],
                    ai_payload.get("predictionSummary", ""),
                )
                if ai_payload
                else "AI 分析尚未生成，请检查模型配置与知识库依赖。"
            )
            prediction_summary["aiInsightPreview"] = prediction_summary["aiInsightSummary"]
            prediction_summary["aiAnalysisAvailable"] = ai_payload is not None
            prediction_summary["aiAnalysisUpdatedAt"] = ai_payload["generatedAt"] if ai_payload else None
            prediction_summary = self._attach_analysis_source_contract(
                prediction_summary,
                primary_source="factor_rows",
                required_published_view="latest_factors",
                output_key="prediction_summary",
                analysis_context_source="prediction_ai_context",
            )
            self.database.upsert_model_output("prediction_summary", run_id, factor_as_of, prediction_summary)

            for artifact in ["predictions.csv", "risk_signals.csv", "performance_summary.csv", "period_factors.txt", "report.txt", "main_visualization.png", "analysis_charts.png"]:
                artifact_path = output_dir / artifact
                if artifact_path.exists():
                    self.database.upsert_artifact(run_id, artifact, str(artifact_path))

            self.database.finish_model_run(run_id, "success", str(output_dir))
            self.database.upsert_source_status(
                "model",
                {"run_id": run_id, "factor_as_of": factor_as_of, "output_dir": str(output_dir)},
            )
            self.database.insert_job_log("model", "success", f"模型运行成功：{run_id}")
            return JobResult("model", True, iso_now(), {"run_id": run_id, "factor_as_of": factor_as_of})
        except Exception as error:
            self.database.finish_model_run(run_id, "failed", str(output_dir), str(error))
            self.database.insert_job_log("model", "failed", str(error))
            raise
        finally:
            self._model_lock.release()

    def get_market_ticker(self) -> dict[str, Any]:
        items = []
        latest_update = None
        for symbol in MARKET_SYMBOLS:
            daily_bars = self.database.get_market_bars(symbol, "1d", 2)
            sparkline_source = self.database.get_market_bars(symbol, "1d", 30)
            if len(daily_bars) < 2:
                continue
            latest = daily_bars[-1]
            previous = daily_bars[-2]
            current = float(latest["close"])
            prev = float(previous["close"])
            change_value = current - prev
            change_percent = 0.0 if prev == 0 else (change_value / prev) * 100
            latest_update = latest_update or latest["source_updated_at"]
            sparkline = [{"value": round(float(bar["close"]), 4)} for bar in sparkline_source]
            items.append(
                {
                    "id": symbol,
                    "label": get_market_series_definition(symbol).label,
                    "value": round(current, 4),
                    "displayValue": f"{current:.2f}",
                    "changePercent": round(change_percent, 2),
                    "direction": "up" if change_percent >= 0 else "down",
                    "sparkline": sparkline,
                    "updatedAt": latest["source_updated_at"],
                }
            )
        return {"items": items, "updatedAt": latest_update or iso_now()}

    def get_dashboard_overview(self) -> dict[str, Any]:
        model_output = self.database.get_model_output("dashboard_overview")
        ticker = self.get_market_ticker()
        return {
            "metrics": ticker["items"],
            "updatedAt": ticker["updatedAt"],
            **(model_output["payload"] if model_output else {}),
        }

    def get_prediction_summary(self) -> dict[str, Any]:
        model_output = self.database.get_model_output("prediction_summary")
        if not model_output:
            raise RuntimeError("暂无模型结果，请先运行模型任务")
        payload = model_output["payload"]
        ai_output = self.database.get_model_output("prediction_ai_analysis")
        if ai_output:
            ai_payload = ai_output["payload"]
            corporate_view = ((ai_payload.get("views") or {}).get("corporate") or {})
            payload["aiInsightSummary"] = (
                str(ai_payload.get("previewSummary", "")).strip()
                or build_ai_preview_summary(
                    str(corporate_view.get("body", "")),
                    str(ai_payload.get("predictionSummary", payload.get("insight", ""))),
                )
            )
            payload["aiInsightPreview"] = payload["aiInsightSummary"]
            payload["aiAnalysisAvailable"] = True
            payload["aiAnalysisUpdatedAt"] = ai_payload.get("generatedAt", ai_output["as_of"])
        payload["updatedAt"] = model_output["as_of"]
        return payload

    def get_prediction_ai_analysis(self) -> dict[str, Any]:
        model_output = self.database.get_model_output("prediction_ai_analysis")
        if not model_output:
            raise RuntimeError("暂无 AI 分析结果，请先运行模型任务")
        payload = model_output["payload"]
        payload["updatedAt"] = model_output["as_of"]
        source_status = self.database.get_source_status().get("ai_analysis", {})
        source_payload = source_status.get("payload", {})
        if source_payload.get("status") == "failed":
            payload["stale"] = True
            payload["lastError"] = str(source_payload.get("last_error", ""))
        else:
            payload["stale"] = False
            payload["lastError"] = ""
        return payload

    def regenerate_prediction_ai_analysis(self, trigger_source: str = "admin_regenerate") -> JobResult:
        model_context = self.database.get_model_output("prediction_ai_context")
        if not model_context:
            raise RuntimeError("暂无可用模型上下文，无法重生成 AI 分析")
        run_id = model_context["run_id"]
        output_dir = GENERATED_DIR / "model_runs" / run_id
        payload = self._generate_ai_analysis(
            run_id=run_id,
            factor_as_of=model_context["as_of"],
            output_dir=output_dir,
            ai_context=model_context["payload"],
            trigger_source=trigger_source,
        )
        summary_output = self.database.get_model_output("prediction_summary")
        if summary_output:
            summary_payload = summary_output["payload"]
            summary_payload["aiInsightSummary"] = (
                str(payload.get("previewSummary", "")).strip()
                or build_ai_preview_summary(
                    payload["views"]["corporate"]["body"],
                    payload.get("predictionSummary", ""),
                )
            )
            summary_payload["aiInsightPreview"] = summary_payload["aiInsightSummary"]
            summary_payload["aiAnalysisAvailable"] = True
            summary_payload["aiAnalysisUpdatedAt"] = payload["generatedAt"]
            summary_payload = self._attach_analysis_source_contract(
                summary_payload,
                primary_source="factor_rows",
                required_published_view="latest_factors",
                output_key="prediction_summary",
                analysis_context_source="prediction_ai_context",
            )
            self.database.upsert_model_output("prediction_summary", run_id, model_context["as_of"], summary_payload)
        return JobResult("ai_analysis", True, payload["generatedAt"], {"run_id": run_id, "factor_as_of": model_context["as_of"]})

    def get_prediction_chart(self, range_key: str) -> dict[str, Any]:
        model_output = self.database.get_model_output("prediction_chart")
        if not model_output:
            raise RuntimeError("暂无模型图表结果，请先运行模型任务")
        history = self.get_market_chart("WTI_Close", range_key)
        return {
            "history": history["points"],
            "projection": model_output["payload"]["projection"],
            "method": model_output["payload"].get("method"),
            "horizonDays": model_output["payload"].get("horizonDays"),
            "priceInterval": model_output["payload"].get("priceInterval"),
            "range": range_key,
            "updatedAt": model_output["as_of"],
        }

    def get_factor_table(self, query: str = "", limit: int = 80) -> dict[str, Any]:
        rows = self.database.get_factor_rows(limit=limit, query=query)
        return {"columns": FACTOR_COLUMNS, "rows": rows, "updatedAt": iso_now()}

    def get_status(self) -> dict[str, Any]:
        return {"sources": self.database.get_source_status()}

    def bootstrap(self) -> None:
        statuses = self.database.get_source_status()
        if "factors" not in statuses:
            self.sync_factors()
        if "market" not in statuses:
            self.sync_market()
        if "model" not in statuses:
            self.run_model("bootstrap")


def create_database() -> Database:
    ensure_dirs()
    database = Database(DB_PATH)
    database.init()
    return database


def create_backend_service(database: Database | None = None) -> BackendService:
    service_database = database or create_database()
    return BackendService(service_database)
