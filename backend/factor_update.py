from __future__ import annotations

import importlib.util
import json
import logging
import os
import sqlite3
import sys
import types
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import runpy


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
REFERENCE_UPDATE_DIRNAME = "factor_update"
REFERENCE_UPDATE_SOURCE_DIR = ROOT_DIR / "modules" / REFERENCE_UPDATE_DIRNAME
REFERENCE_UPDATE_RUNTIME_ROOT = BASE_DIR / "data" / "generated" / "reference_factor_update"
REFERENCE_UPDATE_ARCHIVE = ROOT_DIR / "modules.zip"


@dataclass
class ProviderFetchResult:
    frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    failed_sources: list[str] = field(default_factory=list)


@dataclass
class FactorUpdateResult:
    rows: list[dict[str, Any]]
    latest_date: str | None
    updated_dates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failed_sources: list[str] = field(default_factory=list)


def normalize_factor_frame(frame: pd.DataFrame, reference_columns: list[str] | None = None) -> pd.DataFrame:
    columns = list(reference_columns or [])
    if frame is None or frame.empty:
        if columns:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(columns=["Date"])

    normalized = frame.copy()
    if "Date" not in normalized.columns:
        normalized = normalized.reset_index()
        first_column = normalized.columns[0]
        if first_column != "Date":
            normalized = normalized.rename(columns={first_column: "Date"})

    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
    normalized = normalized.dropna(subset=["Date"])
    normalized = normalized.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")

    if columns:
        for column in columns:
            if column not in normalized.columns:
                normalized[column] = pd.NA
        normalized = normalized[columns]

    normalized["Date"] = normalized["Date"].dt.strftime("%Y-%m-%d")
    return normalized.reset_index(drop=True)


def yesterday_date_key(timezone_name: str | None = None) -> str:
    timezone = ZoneInfo((timezone_name or os.getenv("ORCHESTRATOR_TIMEZONE", "Asia/Shanghai")).strip() or "Asia/Shanghai")
    return (datetime.now(timezone).date() - timedelta(days=1)).isoformat()


def expected_factor_latest_date(timezone_name: str | None = None) -> str:
    cursor = pd.Timestamp(yesterday_date_key(timezone_name))
    while cursor.weekday() >= 5:
        cursor -= pd.Timedelta(days=1)
    return cursor.strftime("%Y-%m-%d")


def detect_missing_dates(frame: pd.DataFrame) -> list[str]:
    normalized = normalize_factor_frame(frame)
    if normalized.empty:
        return []
    full_range = pd.date_range(normalized["Date"].min(), normalized["Date"].max(), freq="D")
    existing = set(normalized["Date"].tolist())
    return [value.strftime("%Y-%m-%d") for value in full_range if value.strftime("%Y-%m-%d") not in existing]


@contextmanager
def pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def restore_reference_update_dir(reference_update_dir: Path, archive_path: Path | None = None) -> Path:
    target_dir = Path(reference_update_dir)
    if target_dir.exists():
        return target_dir

    source_archive = Path(archive_path or REFERENCE_UPDATE_ARCHIVE)
    if not source_archive.exists():
        return target_dir

    directory_name = target_dir.name
    with zipfile.ZipFile(source_archive) as archive:
        members = [
            member
            for member in archive.infolist()
            if PurePosixPath(member.filename).parts
            and PurePosixPath(member.filename).parts[0] == directory_name
        ]
        if not members:
            return target_dir
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        archive.extractall(target_dir.parent, members)
    return target_dir


class ReferenceFactorScriptAdapter:
    PRICE_FACTOR_COLUMNS = (
        "Price",
        "WTI_Close",
        "WTI_Open",
        "WTI_High",
        "WTI_Low",
        "WTI_Return_1d",
        "WTI_Return_5d",
        "WTI_Return_20d",
        "WTI_Return_60d",
        "WTI_Volatility_20d",
        "WTI_Volatility_60d",
        "WTI_MA_5",
        "WTI_MA_20",
        "WTI_MA_60",
        "WTI_High_20d",
        "WTI_Low_20d",
        "WTI_Breakout_High",
        "WTI_Breakdown_Low",
        "WTI_Golden_Cross",
        "WTI_Death_Cross",
        "WTI_Month",
        "WTI_Weekday",
    )
    RELATED_WTI_PRICE_COLUMNS = (
        "WTI_Crude_Oil",
        "WTI_Fut_Price",
        "WTI_Basis",
    )
    FALLBACK_PRIORITY_COLUMNS = frozenset(PRICE_FACTOR_COLUMNS + RELATED_WTI_PRICE_COLUMNS)
    LOCAL_MARKET_DB = BASE_DIR / "data" / "platform.sqlite3"
    LOCAL_MARKET_LOOKBACK_DAYS = 120

    def __init__(self, script_path: Path | None = None, archive_path: Path | None = None):
        self.archive_path = Path(archive_path or REFERENCE_UPDATE_ARCHIVE)
        self.script_path = Path(script_path) if script_path else self._default_script_path()
        self.script_dir = self.script_path.parent
        self._module = None

    def _default_script_path(self) -> Path:
        if REFERENCE_UPDATE_SOURCE_DIR.exists():
            return REFERENCE_UPDATE_SOURCE_DIR / "run_all_updates.py"
        return REFERENCE_UPDATE_RUNTIME_ROOT / REFERENCE_UPDATE_DIRNAME / "run_all_updates.py"

    def _restore_reference_assets(self) -> None:
        if self.script_path.exists():
            return
        if self.script_path != self._default_script_path():
            return
        restore_reference_update_dir(self.script_dir, self.archive_path)

    def _load_module(self):
        if self._module is not None:
            return self._module
        self._restore_reference_assets()
        if not self.script_path.exists():
            raise FileNotFoundError(f"参考因子更新脚本不存在: {self.script_path}")

        module_name = "backend_reference_factor_update"
        spec = importlib.util.spec_from_file_location(module_name, self.script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载参考因子更新脚本: {self.script_path}")

        original_file_handler = logging.FileHandler

        def _null_file_handler(*args, **kwargs):
            return logging.NullHandler()

        logging.FileHandler = _null_file_handler
        try:
            module = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(self.script_dir))
            spec.loader.exec_module(module)
        finally:
            logging.FileHandler = original_file_handler
            if sys.path and sys.path[0] == str(self.script_dir):
                sys.path.pop(0)
        self._module = module
        return module

    def _ensure_fetchers_package(self) -> types.ModuleType:
        self._restore_reference_assets()
        package_name = "fetchers"
        existing = sys.modules.get(package_name)
        if existing is not None:
            return existing
        package = types.ModuleType(package_name)
        package.__path__ = [str(self.script_dir / "fetchers")]
        sys.modules[package_name] = package
        return package

    def _load_fetcher_module(self, module_name: str):
        self._ensure_fetchers_package()
        full_name = f"fetchers.{module_name}"
        existing = sys.modules.get(full_name)
        if existing is not None:
            return existing

        module_path = self.script_dir / "fetchers" / f"{module_name}.py"
        if not module_path.exists():
            raise FileNotFoundError(f"参考 fetcher 不存在: {module_path}")

        spec = importlib.util.spec_from_file_location(full_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载参考 fetcher: {module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
        return module

    def _read_reference_config_keys(self) -> dict[str, str | None]:
        self._restore_reference_assets()
        config_path = self.script_dir / "config.py"
        if not config_path.exists():
            return {"EIA_API_KEY": None, "FRED_API_KEY": None}
        namespace = runpy.run_path(str(config_path))
        return {
            "EIA_API_KEY": namespace.get("EIA_API_KEY"),
            "FRED_API_KEY": namespace.get("FRED_API_KEY"),
        }

    def _load_local_gpr_frame(self, start_date: str, end_date: str) -> pd.DataFrame:
        self._restore_reference_assets()
        local_gpr_file = self.script_dir / "gpr_data" / "data_gpr_export.xls"
        if not local_gpr_file.exists():
            return pd.DataFrame()
        frame = pd.read_excel(local_gpr_file)
        if "Date" not in frame.columns:
            return pd.DataFrame()
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        frame = frame.dropna(subset=["Date"])
        if start_date:
            frame = frame[frame["Date"] >= pd.to_datetime(start_date)]
        if end_date:
            frame = frame[frame["Date"] <= pd.to_datetime(end_date)]
        frame = frame.sort_values("Date")
        if frame.empty:
            return frame
        frame = frame.set_index("Date").resample("D").ffill().reset_index()
        return frame

    def _fetch_gpr_via_fallback(self, start_date: str, end_date: str) -> pd.DataFrame:
        local_frame = self._load_local_gpr_frame(start_date, end_date)
        if not local_frame.empty:
            return local_frame
        fetcher_module = self._load_fetcher_module("gpr_fetcher")
        fetcher_instance = getattr(fetcher_module, "GPRFetcher")()
        return fetcher_instance.fetch(start_date, end_date)

    def _has_price_factor_data(self, frame: pd.DataFrame) -> bool:
        if frame is None or frame.empty:
            return False
        available_columns = [column for column in self.PRICE_FACTOR_COLUMNS if column in frame.columns]
        if not available_columns:
            return False
        return bool(frame[available_columns].notna().any(axis=None))

    def _load_local_market_price_frame(self, start_date: str, end_date: str) -> pd.DataFrame:
        if not self.LOCAL_MARKET_DB.exists():
            return pd.DataFrame()

        start_ts = pd.to_datetime(start_date, errors="coerce")
        end_ts = pd.to_datetime(end_date, errors="coerce")
        if pd.isna(start_ts) or pd.isna(end_ts):
            return pd.DataFrame()
        query_start = (start_ts - timedelta(days=self.LOCAL_MARKET_LOOKBACK_DAYS)).strftime("%Y-%m-%dT00:00:00+00:00")
        query_end = (end_ts + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+00:00")

        with sqlite3.connect(self.LOCAL_MARKET_DB) as connection:
            rows = connection.execute(
                """
                SELECT observed_at, open, high, low, close
                FROM market_bars
                WHERE symbol = 'WTI_Close' AND granularity = '1d'
                  AND observed_at >= ? AND observed_at < ?
                ORDER BY observed_at ASC
                """,
                (query_start, query_end),
            ).fetchall()

        if not rows:
            return pd.DataFrame()

        frame = pd.DataFrame(rows, columns=["observed_at", "WTI_Open", "WTI_High", "WTI_Low", "WTI_Close"])
        frame["Date"] = pd.to_datetime(frame["observed_at"], errors="coerce", utc=True).dt.normalize()
        frame = frame.dropna(subset=["Date"]).drop(columns=["observed_at"])
        frame["Price"] = pd.to_numeric(frame["WTI_Close"], errors="coerce")
        return frame.dropna(subset=["Price"]).drop_duplicates(subset=["Date"], keep="last").sort_values("Date").reset_index(drop=True)

    def _build_wti_price_fallback_frame(
        self,
        start_date: str,
        end_date: str,
        reference_columns: list[str],
        reference_module: Any,
        market_provider: Any | None = None,
    ) -> pd.DataFrame:
        price_columns = [column for column in reference_columns if column in self.PRICE_FACTOR_COLUMNS]
        if not price_columns:
            return pd.DataFrame(columns=reference_columns)

        try:
            from .market_data import FredProvider, YahooFinanceProvider, resolve_provider_symbol
        except ImportError:
            from market_data import FredProvider, YahooFinanceProvider, resolve_provider_symbol

        start_ts = pd.to_datetime(start_date, errors="coerce", utc=True)
        end_ts = pd.to_datetime(end_date, errors="coerce", utc=True)
        if pd.isna(start_ts) or pd.isna(end_ts) or start_ts > end_ts:
            return pd.DataFrame(columns=reference_columns)

        outputsize = max(int((end_ts - start_ts).days) + 120, 180)
        provider_symbol = resolve_provider_symbol("WTI_Close")
        local_market_frame = self._load_local_market_price_frame(start_date, end_date)
        if not local_market_frame.empty:
            price_frame = local_market_frame.set_index("Date").sort_index()
            indicator_frame = reference_module.DataFetcher().calculate_wti_indicators(price_frame["Price"])
            indicator_frame["WTI_Open"] = price_frame["WTI_Open"]
            indicator_frame["WTI_High"] = price_frame["WTI_High"]
            indicator_frame["WTI_Low"] = price_frame["WTI_Low"]
            indicator_frame = indicator_frame.loc[(indicator_frame.index >= start_ts) & (indicator_frame.index <= end_ts)]
            if not indicator_frame.empty:
                indicator_frame = self._populate_related_wti_price_columns(indicator_frame, reference_columns)
                return normalize_factor_frame(indicator_frame.reset_index(), reference_columns)

        providers = [("market", market_provider)] if market_provider is not None else [("fred", FredProvider()), ("yahoo", YahooFinanceProvider())]

        last_error = None
        for _, provider in providers:
            try:
                bars = provider.fetch_bars(provider_symbol, "1d", outputsize, "WTI_Close")
                if not bars:
                    continue
                price_rows = []
                for bar in bars:
                    observed_at = pd.to_datetime(bar["observed_at"], errors="coerce", utc=True)
                    if pd.isna(observed_at):
                        continue
                    price_rows.append({"Date": observed_at.normalize(), "Price": float(bar["close"])})
                if not price_rows:
                    continue
                price_frame = pd.DataFrame(price_rows).drop_duplicates(subset=["Date"], keep="last").set_index("Date").sort_index()
                indicator_frame = reference_module.DataFetcher().calculate_wti_indicators(price_frame["Price"])
                indicator_frame = indicator_frame.loc[(indicator_frame.index >= start_ts) & (indicator_frame.index <= end_ts)]
                if indicator_frame.empty:
                    continue
                indicator_frame = self._populate_related_wti_price_columns(indicator_frame, reference_columns)
                return normalize_factor_frame(indicator_frame.reset_index(), reference_columns)
            except Exception as error:
                last_error = error
                continue

        if last_error is not None:
            raise RuntimeError(f"WTI 价格回补失败：{last_error}") from last_error
        return pd.DataFrame(columns=reference_columns)

    def _populate_related_wti_price_columns(self, frame: pd.DataFrame, reference_columns: list[str]) -> pd.DataFrame:
        related_columns = [column for column in self.RELATED_WTI_PRICE_COLUMNS if column in reference_columns]
        if not related_columns:
            return frame

        enriched = frame.copy()
        def _numeric_series(column: str) -> pd.Series:
            if column not in enriched.columns:
                return pd.Series(index=enriched.index, dtype="float64")
            return pd.to_numeric(enriched[column], errors="coerce")

        close_series = _numeric_series("WTI_Close")
        price_series = _numeric_series("Price")
        anchor_series = close_series.combine_first(price_series)

        if "WTI_Fut_Price" in related_columns:
            current = _numeric_series("WTI_Fut_Price")
            enriched["WTI_Fut_Price"] = current.combine_first(anchor_series)

        if "WTI_Crude_Oil" in related_columns:
            current = _numeric_series("WTI_Crude_Oil")
            enriched["WTI_Crude_Oil"] = current.combine_first(price_series).combine_first(anchor_series)

        if "WTI_Basis" in related_columns:
            current = _numeric_series("WTI_Basis")
            futures_series = _numeric_series("WTI_Fut_Price")
            spot_series = _numeric_series("WTI_Crude_Oil")
            computed_basis = futures_series - spot_series
            enriched["WTI_Basis"] = current.combine_first(computed_basis)

        return enriched

    def fetch(self, start_date: str, end_date: str, reference_columns: list[str]) -> ProviderFetchResult:
        if not start_date or not end_date or start_date > end_date:
            return ProviderFetchResult(frame=pd.DataFrame(columns=reference_columns))

        warnings: list[str] = []
        failed_sources: list[str] = []

        try:
            module = self._load_module()
        except Exception as error:
            return ProviderFetchResult(
                frame=pd.DataFrame(columns=reference_columns),
                warnings=[f"参考因子更新脚本加载失败：{error}"],
                failed_sources=["reference_loader"],
            )

        if "config" not in sys.modules:
            sys.path.insert(0, str(self.script_dir))
        try:
            module.requests = requests
            module.json = json
            module.load_config()
            config_keys = self._read_reference_config_keys()
            module.Config.EIA_API_KEY = os.getenv("EIA_API_KEY") or module.Config.EIA_API_KEY or config_keys.get("EIA_API_KEY")
            module.Config.FRED_API_KEY = os.getenv("FRED_API_KEY") or module.Config.FRED_API_KEY or config_keys.get("FRED_API_KEY")

            fetcher = module.DataFetcher()
            direct_fetchers = {
                "CFTC": ("cftc_fetcher", "CFTCFetcher"),
                "GDELT": ("gdel_fetcher", "GDELTFetcher"),
                "TPU": ("tpu_fetcher", "TPUFetcher"),
                "GPR": ("gpr_fetcher", "GPRFetcher"),
            }
            source_methods = [
                ("EIA", fetcher.fetch_eia_data),
                ("FRED", fetcher.fetch_fred_data),
                ("CFTC", fetcher.fetch_cftc_data),
                ("CBOE", fetcher.fetch_cboe_data),
                ("GDELT", fetcher.fetch_gdelt_data),
                ("GPR", fetcher.fetch_gpr_data),
                ("TPU", fetcher.fetch_tpu_data),
                ("China", fetcher.fetch_china_data),
                ("Sina", fetcher.fetch_sina_data),
            ]

            data_frames: list[pd.DataFrame] = []
            with pushd(self.script_dir):
                for source_name, fetch_method in source_methods:
                    try:
                        if source_name in direct_fetchers:
                            if source_name == "GPR":
                                source_frame = self._fetch_gpr_via_fallback(start_date, end_date)
                            else:
                                module_name, class_name = direct_fetchers[source_name]
                                fetcher_module = self._load_fetcher_module(module_name)
                                fetcher_instance = getattr(fetcher_module, class_name)()
                                source_frame = fetcher_instance.fetch(start_date, end_date)
                        else:
                            source_frame = fetch_method(start_date, end_date)
                    except Exception as error:
                        failed_sources.append(source_name)
                        warnings.append(f"{source_name} 数据源更新失败：{error}")
                        continue
                    if source_frame is None or source_frame.empty:
                        failed_sources.append(source_name)
                        warnings.append(f"{source_name} 数据源未返回可用数据")
                        continue
                    data_frames.append(source_frame)

                fallback_frame = self._build_wti_price_fallback_frame(start_date, end_date, reference_columns, module)
                if not fallback_frame.empty:
                    fallback_indexed = fallback_frame.copy()
                    fallback_indexed["Date"] = pd.to_datetime(fallback_indexed["Date"], errors="coerce")
                    fallback_indexed = fallback_indexed.dropna(subset=["Date"]).set_index("Date")
                    data_frames.append(fallback_indexed)
                    price_probe = pd.concat(data_frames, axis=1)
                    if not self._has_price_factor_data(price_probe):
                        warnings.append("WTI 价格回补通道未生成可用价格因子")
                    else:
                        warnings.append("WTI 价格因子已通过市场数据通道补齐缺失日期")
        finally:
            if sys.path and sys.path[0] == str(self.script_dir):
                sys.path.pop(0)

        if not data_frames:
            return ProviderFetchResult(
                frame=pd.DataFrame(columns=reference_columns),
                warnings=warnings or [f"未获取到 {start_date} 至 {end_date} 的外部因子数据"],
                failed_sources=sorted(set(failed_sources)),
            )

        merged = pd.concat(data_frames, axis=1)
        merged = merged.sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]

        return ProviderFetchResult(
            frame=self._align_to_reference_columns(merged, reference_columns),
            warnings=warnings,
            failed_sources=sorted(set(failed_sources)),
        )

    def _align_to_reference_columns(self, merged: pd.DataFrame, reference_columns: list[str]) -> pd.DataFrame:
        aligned_columns = [column for column in reference_columns if column != "Date"]
        aligned = pd.DataFrame(index=merged.index, columns=aligned_columns)
        for column in aligned.columns:
            if column not in merged.columns:
                continue
            column_value = merged.loc[:, column]
            if isinstance(column_value, pd.DataFrame):
                if column in self.FALLBACK_PRIORITY_COLUMNS:
                    column_value = column_value.ffill(axis=1).iloc[:, -1]
                else:
                    column_value = column_value.bfill(axis=1).iloc[:, 0]
            aligned[column] = column_value
        return normalize_factor_frame(aligned, reference_columns)


class FactorUpdatePipeline:
    PRICE_ANCHOR_COLUMNS = ("Price", "WTI_Close", "WTI_Open", "WTI_High", "WTI_Low")
    PRICE_REFRESH_WINDOW_DAYS = 14
    RELATED_WTI_MAX_DEVIATION = 0.15

    def __init__(self, provider: ReferenceFactorScriptAdapter | None = None, timezone_name: str | None = None):
        self.provider = provider or ReferenceFactorScriptAdapter()
        self.timezone_name = timezone_name or os.getenv("ORCHESTRATOR_TIMEZONE", "Asia/Shanghai")

    def _build_base_frame(self, existing_frame: pd.DataFrame, reference_frame: pd.DataFrame) -> pd.DataFrame:
        reference_columns = reference_frame.columns.tolist() if not reference_frame.empty else ["Date"]
        normalized_existing = normalize_factor_frame(existing_frame, reference_columns)
        if not normalized_existing.empty:
            return normalized_existing
        return normalize_factor_frame(reference_frame, reference_columns)

    def _resolve_fetch_start(self, base_frame: pd.DataFrame) -> str | None:
        missing_dates = detect_missing_dates(base_frame)
        if missing_dates:
            return min(missing_dates)
        if base_frame.empty:
            return None
        latest_date = pd.to_datetime(base_frame["Date"]).max()
        refresh_start = latest_date - timedelta(days=self.PRICE_REFRESH_WINDOW_DAYS - 1)
        return refresh_start.strftime("%Y-%m-%d")

    def _price_anchor_columns(self, reference_columns: list[str]) -> list[str]:
        return [column for column in self.PRICE_ANCHOR_COLUMNS if column in reference_columns]

    def _drop_new_dates_without_price_anchor(
        self, base_frame: pd.DataFrame, provider_frame: pd.DataFrame, reference_columns: list[str]
    ) -> tuple[pd.DataFrame, list[str]]:
        normalized_base = normalize_factor_frame(base_frame, reference_columns)
        normalized_provider = normalize_factor_frame(provider_frame, reference_columns)
        if normalized_provider.empty:
            return normalized_provider, []

        anchor_columns = self._price_anchor_columns(reference_columns)
        if not anchor_columns:
            return normalized_provider, []

        existing_dates = set(normalized_base["Date"].tolist()) if not normalized_base.empty else set()
        new_rows = normalized_provider[~normalized_provider["Date"].isin(existing_dates)]
        if new_rows.empty:
            return normalized_provider, []

        valid_new_rows = new_rows[anchor_columns].notna().any(axis=1)
        skipped_dates = new_rows.loc[~valid_new_rows, "Date"].tolist()
        if not skipped_dates:
            return normalized_provider, []

        filtered_provider = normalized_provider[~normalized_provider["Date"].isin(skipped_dates)].reset_index(drop=True)
        return filtered_provider, skipped_dates

    def _forward_fill_columns(self, merged: pd.DataFrame) -> pd.DataFrame:
        fillable_columns = [column for column in merged.columns if column != "Price" and not column.startswith("WTI_")]
        if fillable_columns:
            merged.loc[:, fillable_columns] = merged.loc[:, fillable_columns].ffill().infer_objects(copy=False)
        return merged

    def _repair_wti_price_cluster(self, merged: pd.DataFrame) -> pd.DataFrame:
        if merged.empty:
            return merged
        if "Price" not in merged.columns and "WTI_Close" not in merged.columns:
            return merged

        repaired = merged.copy()
        anchor = pd.to_numeric(repaired.get("WTI_Close", repaired.get("Price")), errors="coerce")
        if "Price" in repaired.columns:
            anchor = anchor.combine_first(pd.to_numeric(repaired["Price"], errors="coerce"))

        def _repair_column(column: str):
            if column not in repaired.columns:
                return
            current = pd.to_numeric(repaired[column], errors="coerce")
            deviation = (current - anchor).abs() / anchor.abs().clip(lower=1e-6)
            should_replace = anchor.notna() & (
                current.isna() | (deviation > self.RELATED_WTI_MAX_DEVIATION)
            )
            repaired.loc[should_replace, column] = anchor.loc[should_replace]

        _repair_column("WTI_Crude_Oil")
        _repair_column("WTI_Fut_Price")

        if "WTI_Basis" in repaired.columns:
            futures = pd.to_numeric(repaired.get("WTI_Fut_Price"), errors="coerce")
            spot = pd.to_numeric(repaired.get("WTI_Crude_Oil"), errors="coerce")
            repaired["WTI_Basis"] = futures - spot

        return repaired

    def _merge_frames(self, base_frame: pd.DataFrame, provider_frame: pd.DataFrame, reference_columns: list[str]) -> pd.DataFrame:
        normalized_base = normalize_factor_frame(base_frame, reference_columns)
        normalized_provider, _ = self._drop_new_dates_without_price_anchor(base_frame, provider_frame, reference_columns)
        if normalized_provider.empty:
            return normalized_base

        base_indexed = normalized_base.set_index("Date") if not normalized_base.empty else pd.DataFrame(columns=reference_columns[1:])
        provider_indexed = normalized_provider.set_index("Date")
        union_index = sorted(set(base_indexed.index.tolist()) | set(provider_indexed.index.tolist()))
        merged = provider_indexed.reindex(union_index).combine_first(base_indexed.reindex(union_index))

        merged = merged.sort_index()
        merged = self._forward_fill_columns(merged)
        merged = self._repair_wti_price_cluster(merged)
        merged.index.name = "Date"
        return normalize_factor_frame(merged.reset_index(), reference_columns)

    def run(self, existing_frame: pd.DataFrame, reference_frame: pd.DataFrame) -> FactorUpdateResult:
        normalized_reference = normalize_factor_frame(reference_frame)
        reference_columns = normalized_reference.columns.tolist() if not normalized_reference.empty else ["Date"]
        base_frame = self._build_base_frame(existing_frame, normalized_reference)

        updated_dates = base_frame["Date"].tolist() if normalize_factor_frame(existing_frame, reference_columns).empty else []
        warnings: list[str] = []
        failed_sources: list[str] = []

        start_date = self._resolve_fetch_start(base_frame)
        end_date = yesterday_date_key(self.timezone_name)
        provider_frame = pd.DataFrame(columns=reference_columns)

        if start_date and start_date <= end_date:
            provider_result = self.provider.fetch(start_date, end_date, reference_columns)
            provider_frame, skipped_dates = self._drop_new_dates_without_price_anchor(
                base_frame, provider_result.frame, reference_columns
            )
            warnings.extend(provider_result.warnings)
            failed_sources.extend(provider_result.failed_sources)
            if skipped_dates:
                warnings.append(
                    "因子更新跳过缺少价格锚点的新日期："
                    + ", ".join(skipped_dates)
                    + "；请检查 EIA/WTI 价格链路是否成功更新"
                )
            if not provider_frame.empty:
                updated_dates.extend(provider_frame["Date"].tolist())
        elif start_date and start_date > end_date:
            warnings.append(f"当前因子快照已覆盖到 {base_frame['Date'].max()}，无需补最新日期")

        final_frame = self._merge_frames(base_frame, provider_frame, reference_columns)
        updated_date_set = sorted(set(updated_dates))
        rows = final_frame[final_frame["Date"].isin(updated_date_set)].to_dict(orient="records") if updated_date_set else []
        latest_date = final_frame["Date"].max() if not final_frame.empty else None
        return FactorUpdateResult(
            rows=rows,
            latest_date=latest_date,
            updated_dates=updated_date_set,
            warnings=warnings,
            failed_sources=sorted(set(failed_sources)),
        )
