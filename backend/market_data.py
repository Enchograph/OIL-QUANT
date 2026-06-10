from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import pandas as pd
from pandas_datareader import data as web
import yfinance as yf

try:
    from .network_utils import is_retryable_network_error, run_with_proxy_fallback
except ImportError:
    from network_utils import is_retryable_network_error, run_with_proxy_fallback


@dataclass(frozen=True)
class MarketSeriesDefinition:
    series_id: str
    label: str
    source_kind: str
    env_key: str | None = None
    default_symbol: str | None = None


MARKET_SERIES_DEFINITIONS = {
    "WTI_Close": MarketSeriesDefinition("WTI_Close", "WTI", "provider", "MARKET_SYMBOL_WTI_CLOSE", "CL=F"),
    "Brent_Close": MarketSeriesDefinition("Brent_Close", "Brent", "provider", "MARKET_SYMBOL_BRENT_CLOSE", "BZ=F"),
    "WTI_Brent_Spread": MarketSeriesDefinition("WTI_Brent_Spread", "WTI-Brent Spread", "derived"),
    "HenryHub_NG": MarketSeriesDefinition("HenryHub_NG", "Henry Hub", "provider", "MARKET_SYMBOL_HENRY_HUB_NG", "NG=F"),
    "RBOB_Gasoline": MarketSeriesDefinition("RBOB_Gasoline", "RBOB Gasoline", "provider", "MARKET_SYMBOL_RBOB_GASOLINE", "RB=F"),
    "DXY_Price": MarketSeriesDefinition("DXY_Price", "DXY", "provider", "MARKET_SYMBOL_DXY_PRICE", "DX-Y.NYB"),
    "VIX_Price": MarketSeriesDefinition("VIX_Price", "VIX", "provider", "MARKET_SYMBOL_VIX_PRICE", "^VIX"),
    "Treasury_10Y_Yield": MarketSeriesDefinition(
        "Treasury_10Y_Yield",
        "US 10Y Yield",
        "provider",
        "MARKET_SYMBOL_TREASURY_10Y_YIELD",
        "^TNX",
    ),
}

MARKET_SERIES_IDS = tuple(MARKET_SERIES_DEFINITIONS.keys())

PROVIDER_INTERVALS = {
    "1m": "1min",
    "5m": "5min",
    "1h": "1h",
    "1d": "1day",
}

YFINANCE_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "1h": "60m",
    "1d": "1d",
}

YFINANCE_PERIODS = {
    "1m": "7d",
    "5m": "60d",
    "1h": "730d",
    "1d": "5y",
}

YFINANCE_SAFE_LOOKBACKS = {
    "1m": timedelta(days=29, hours=23, minutes=59),
    "5m": timedelta(days=59, hours=23, minutes=59),
    "1h": timedelta(days=729, hours=23, minutes=59),
    "1d": timedelta(days=(365 * 5) - 1, hours=23, minutes=59),
}

YFINANCE_INTRADAY_CHUNK_WINDOWS = {
    "1m": timedelta(days=6),
    "5m": timedelta(days=7),
    "1h": timedelta(days=30),
}

YFINANCE_INTRADAY_LOOKBACK_MARGIN = {
    "1m": timedelta(minutes=5),
    "5m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
}

GRANULARITY_TO_TIMESTEP = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}

YFINANCE_SCALES: dict[str, float] = {}

YFINANCE_CACHE_DIR = Path(__file__).resolve().parent / "data" / "yfinance_cache"
_YFINANCE_CACHE_READY = False

FRED_SERIES_MAP = {
    "WTI_Close": "DCOILWTICO",
    "Brent_Close": "DCOILBRENTEU",
    "HenryHub_NG": "DHHNGSP",
    "RBOB_Gasoline": "DRGASLA",
    "VIX_Price": "VIXCLS",
    "Treasury_10Y_Yield": "DGS10",
    "DXY_Price": "DTWEXBGS",
}


def get_market_series_definition(series_id: str) -> MarketSeriesDefinition:
    return MARKET_SERIES_DEFINITIONS[series_id]


def resolve_provider_symbol(series_id: str) -> str:
    definition = get_market_series_definition(series_id)
    if definition.source_kind != "provider":
        raise ValueError(f"{series_id} 不是外部 provider 序列")
    if definition.env_key:
        configured = os.getenv(definition.env_key, "").strip()
        if configured:
            return configured
    if definition.default_symbol:
        return definition.default_symbol
    raise ValueError(f"缺少 {series_id} 的 provider symbol 配置")


def _parse_timestamp(raw: str) -> str:
    normalized = raw.strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=UTC).isoformat()
    except ValueError:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").replace(tzinfo=UTC).isoformat()


class TwelveDataProvider:
    def __init__(self) -> None:
        self.api_key = os.getenv("MARKET_DATA_API_KEY", "").strip()
        self.base_url = os.getenv("MARKET_DATA_BASE_URL", "https://api.twelvedata.com").rstrip("/")
        self.timeout = max(5, int(os.getenv("MARKET_DATA_TIMEOUT_SECONDS", "20")))
        if not self.api_key:
            raise ValueError("缺少配置 MARKET_DATA_API_KEY")

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = parse.urlencode({**params, "apikey": self.api_key})
        url = f"{self.base_url}{path}?{query}"
        try:
            with request.urlopen(url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Twelve Data 请求失败 {exc.code}: {body[:200]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Twelve Data 网络请求失败: {exc.reason}") from exc

        if payload.get("status") == "error":
            raise RuntimeError(f"Twelve Data 返回错误: {payload.get('message', 'unknown error')}")
        return payload

    def fetch_bars(self, provider_symbol: str, granularity: str, outputsize: int) -> list[dict[str, Any]]:
        interval = PROVIDER_INTERVALS[granularity]
        payload = self._get(
            "/time_series",
            {
                "symbol": provider_symbol,
                "interval": interval,
                "outputsize": outputsize,
                "timezone": "UTC",
                "format": "JSON",
            },
        )
        values = payload.get("values") or []
        bars = []
        for item in reversed(values):
            bars.append(
                {
                    "observed_at": _parse_timestamp(str(item["datetime"])),
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                }
            )
        return bars


class YahooFinanceProvider:
    def __init__(self) -> None:
        self._ensure_cache_location()
        self.timeout = max(5, int(os.getenv("MARKET_DATA_TIMEOUT_SECONDS", "20")))
        self.lookback_days = max(7, int(os.getenv("MARKET_INTRADAY_LOOKBACK_DAYS", "30")))
        self.max_retries = max(1, int(os.getenv("MARKET_YF_MAX_RETRIES", "3")))
        self.retry_sleep_seconds = max(1, int(os.getenv("MARKET_YF_RETRY_SLEEP_SECONDS", "4")))

    def _ensure_cache_location(self) -> None:
        global _YFINANCE_CACHE_READY
        if _YFINANCE_CACHE_READY:
            return
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
        _YFINANCE_CACHE_READY = True

    def fetch_bars(self, provider_symbol: str, granularity: str, outputsize: int, series_id: str) -> list[dict[str, Any]]:
        interval = YFINANCE_INTERVALS[granularity]
        period = YFINANCE_PERIODS[granularity]
        history = yf.Ticker(provider_symbol).history(
            interval=interval,
            period=period,
            auto_adjust=False,
        )
        if history.empty:
            raise RuntimeError(f"Yahoo Finance 未返回 {series_id}({provider_symbol}) 的 {granularity} 数据")

        if history.index.tz is None:
            history.index = history.index.tz_localize("UTC")
        else:
            history.index = history.index.tz_convert("UTC")

        scale = YFINANCE_SCALES.get(series_id, 1.0)
        trimmed = history.tail(outputsize)
        bars = []
        for observed_at, row in trimmed.iterrows():
            open_value = float(row["Open"]) * scale
            high_value = float(row["High"]) * scale
            low_value = float(row["Low"]) * scale
            close_value = float(row["Close"]) * scale
            bars.append(
                {
                    "observed_at": pd.Timestamp(observed_at).to_pydatetime().isoformat(),
                    "open": round(open_value, 4),
                    "high": round(high_value, 4),
                    "low": round(low_value, 4),
                    "close": round(close_value, 4),
                }
            )
        return bars

    def fetch_batch_bars(
        self,
        series_ids: list[str],
        symbol_lookup: dict[str, str],
        granularity: str,
        outputsize: int,
    ) -> dict[str, list[dict[str, Any]]]:
        if granularity in YFINANCE_INTRADAY_CHUNK_WINDOWS:
            return self._fetch_chunked_intraday_bars(series_ids, symbol_lookup, granularity, outputsize)
        return self._fetch_windowed_batch_bars(series_ids, symbol_lookup, granularity, outputsize)

    def _normalize_history_index(self, history: pd.DataFrame) -> pd.DataFrame:
        if history.index.tz is None:
            history.index = history.index.tz_localize("UTC")
        else:
            history.index = history.index.tz_convert("UTC")
        return history

    def _bars_from_history(self, history: pd.DataFrame, series_id: str, provider_symbol: str, outputsize: int) -> list[dict[str, Any]]:
        scale = YFINANCE_SCALES.get(series_id, 1.0)
        trimmed = history.tail(outputsize).dropna(subset=["Open", "High", "Low", "Close"], how="any")
        bars = []
        for observed_at, row in trimmed.iterrows():
            bars.append(
                {
                    "observed_at": pd.Timestamp(observed_at).to_pydatetime().isoformat(),
                    "open": round(float(row["Open"]) * scale, 4),
                    "high": round(float(row["High"]) * scale, 4),
                    "low": round(float(row["Low"]) * scale, 4),
                    "close": round(float(row["Close"]) * scale, 4),
                }
            )
        if not bars:
            raise RuntimeError(f"Yahoo Finance 未返回 {series_id}({provider_symbol}) 可用数据")
        return bars

    def _download_with_retries(self, tickers: list[str], interval: str, start: datetime, end: datetime) -> pd.DataFrame:
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                history = run_with_proxy_fallback(
                    lambda session: yf.download(
                        tickers=" ".join(tickers),
                        interval=interval,
                        start=start,
                        end=end,
                        auto_adjust=False,
                        progress=False,
                        threads=False,
                        group_by="ticker",
                        timeout=self.timeout,
                        session=session,
                    ),
                    retry_on_masked_proxy_error=True,
                )
                if history is None or history.empty:
                    raise RuntimeError(f"Yahoo Finance 未返回 {interval} 数据")
                return self._normalize_history_index(history)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_sleep_seconds * attempt)
        raise RuntimeError(f"Yahoo Finance 请求失败: {last_error}") from last_error

    def _extract_symbol_history(self, history: pd.DataFrame, provider_symbol: str) -> pd.DataFrame:
        if isinstance(history.columns, pd.MultiIndex):
            if provider_symbol not in history.columns.get_level_values(0):
                raise RuntimeError(f"Yahoo Finance 批量结果缺少 {provider_symbol}")
            return history[provider_symbol]
        return history

    def _fetch_windowed_batch_bars(
        self,
        series_ids: list[str],
        symbol_lookup: dict[str, str],
        granularity: str,
        outputsize: int,
    ) -> dict[str, list[dict[str, Any]]]:
        interval = YFINANCE_INTERVALS[granularity]
        end = datetime.now(UTC)
        lookback = YFINANCE_SAFE_LOOKBACKS.get(granularity, timedelta(days=self.lookback_days))
        start = end - lookback
        tickers = [symbol_lookup[series_id] for series_id in series_ids]
        history = self._download_with_retries(tickers, interval, start, end)
        results: dict[str, list[dict[str, Any]]] = {}
        missing_series_ids: list[str] = []
        for series_id in series_ids:
            provider_symbol = symbol_lookup[series_id]
            try:
                symbol_history = self._extract_symbol_history(history, provider_symbol)
                results[series_id] = self._bars_from_history(symbol_history, series_id, provider_symbol, outputsize)
            except Exception:
                missing_series_ids.append(series_id)
        for series_id in missing_series_ids:
            provider_symbol = symbol_lookup[series_id]
            single_history = self._download_with_retries([provider_symbol], interval, start, end)
            results[series_id] = self._bars_from_history(single_history, series_id, provider_symbol, outputsize)
        return results

    def _fetch_chunked_intraday_bars(
        self,
        series_ids: list[str],
        symbol_lookup: dict[str, str],
        granularity: str,
        outputsize: int,
    ) -> dict[str, list[dict[str, Any]]]:
        end = datetime.now(UTC).replace(second=0, microsecond=0)
        interval = YFINANCE_INTERVALS[granularity]
        timestep = GRANULARITY_TO_TIMESTEP[granularity]
        requested_start = end - (timestep * max(outputsize, 1))
        safe_lookback = YFINANCE_SAFE_LOOKBACKS[granularity] - YFINANCE_INTRADAY_LOOKBACK_MARGIN.get(
            granularity,
            timedelta(0),
        )
        start = max(requested_start, end - safe_lookback)
        chunk_size = YFINANCE_INTRADAY_CHUNK_WINDOWS[granularity]
        combined_rows: dict[str, dict[str, dict[str, float]]] = {series_id: {} for series_id in series_ids}
        for series_id in series_ids:
            provider_symbol = symbol_lookup[series_id]
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(chunk_start + chunk_size, end)
                history = self._download_with_retries([provider_symbol], interval, chunk_start, chunk_end)
                symbol_history = self._extract_symbol_history(history, provider_symbol)
                scale = YFINANCE_SCALES.get(series_id, 1.0)
                trimmed = symbol_history.dropna(subset=["Open", "High", "Low", "Close"], how="any")
                for observed_at, row in trimmed.iterrows():
                    observed_key = pd.Timestamp(observed_at).to_pydatetime().isoformat()
                    combined_rows[series_id][observed_key] = {
                        "observed_at": observed_key,
                        "open": round(float(row["Open"]) * scale, 4),
                        "high": round(float(row["High"]) * scale, 4),
                        "low": round(float(row["Low"]) * scale, 4),
                        "close": round(float(row["Close"]) * scale, 4),
                    }
                chunk_start = chunk_end
                time.sleep(1)

        results: dict[str, list[dict[str, Any]]] = {}
        for series_id in series_ids:
            rows = list(combined_rows[series_id].values())
            rows.sort(key=lambda item: item["observed_at"])
            if not rows:
                raise RuntimeError(f"Yahoo Finance 未返回 {series_id} 的 {granularity} 数据")
            results[series_id] = rows[-outputsize:]
        return results


class FredProvider:
    def __init__(self) -> None:
        self.max_retries = max(1, int(os.getenv("MARKET_FRED_MAX_RETRIES", "3")))
        self.retry_sleep_seconds = max(1, int(os.getenv("MARKET_FRED_RETRY_SLEEP_SECONDS", "2")))

    def _load_daily_history(self, fred_series: str) -> pd.DataFrame:
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return run_with_proxy_fallback(
                    lambda session: web.DataReader(fred_series, "fred", session=session),
                )
            except Exception as error:
                last_error = error
                if attempt >= self.max_retries or not is_retryable_network_error(error):
                    break
                time.sleep(self.retry_sleep_seconds * attempt)
        raise RuntimeError(f"FRED 请求失败: {last_error}") from last_error

    def _daily_bars(self, series_id: str, outputsize: int) -> list[dict[str, Any]]:
        fred_series = FRED_SERIES_MAP[series_id]
        history = self._load_daily_history(fred_series).dropna().reset_index().rename(columns={fred_series: "value"})
        if history.empty:
            raise RuntimeError(f"FRED 未返回 {series_id}({fred_series}) 数据")
        if "DATE" in history.columns:
            history = history.rename(columns={"DATE": "Date"})
        if "Date" not in history.columns:
            history = history.rename(columns={history.columns[0]: "Date"})
        trimmed = history.tail(outputsize)
        bars = []
        previous_close = float(trimmed.iloc[0]["value"])
        for row in trimmed.itertuples(index=False):
            current_close = float(row.value)
            observed = pd.Timestamp(row.Date).to_pydatetime().replace(tzinfo=UTC)
            bars.append(
                {
                    "observed_at": observed.isoformat(),
                    "open": round(previous_close, 4),
                    "high": round(max(previous_close, current_close), 4),
                    "low": round(min(previous_close, current_close), 4),
                    "close": round(current_close, 4),
                }
            )
            previous_close = current_close
        return bars

    def fetch_bars(self, provider_symbol: str, granularity: str, outputsize: int, series_id: str) -> list[dict[str, Any]]:
        if granularity != "1d":
            raise ValueError(f"FRED provider 仅支持日线数据，不支持粒度: {granularity}")
        daily_limit = max(outputsize, 366)
        daily_bars = self._daily_bars(series_id, daily_limit)
        return daily_bars[-outputsize:]


class HybridProvider:
    def __init__(self) -> None:
        self.fred = FredProvider()
        self.yahoo = YahooFinanceProvider()

    def fetch_bars(self, provider_symbol: str, granularity: str, outputsize: int, series_id: str) -> list[dict[str, Any]]:
        if granularity == "1d":
            try:
                return self.fred.fetch_bars(provider_symbol, granularity, outputsize, series_id)
            except Exception:
                return self.yahoo.fetch_bars(provider_symbol, granularity, outputsize, series_id)
        return self.yahoo.fetch_bars(provider_symbol, granularity, outputsize, series_id)

    def fetch_batch_bars(
        self,
        series_ids: list[str],
        symbol_lookup: dict[str, str],
        granularity: str,
        outputsize: int,
    ) -> dict[str, list[dict[str, Any]]]:
        if granularity == "1d":
            return {
                series_id: self.fetch_bars(symbol_lookup[series_id], granularity, outputsize, series_id)
                for series_id in series_ids
            }
        try:
            return self.yahoo.fetch_batch_bars(series_ids, symbol_lookup, granularity, outputsize)
        except Exception:
            return {
                series_id: self.yahoo.fetch_bars(symbol_lookup[series_id], granularity, outputsize, series_id)
                for series_id in series_ids
            }


def build_market_data_provider() -> YahooFinanceProvider | TwelveDataProvider | FredProvider | HybridProvider:
    provider = os.getenv("MARKET_DATA_PROVIDER", "hybrid").strip().lower()
    if provider == "hybrid":
        return HybridProvider()
    if provider == "fred":
        return FredProvider()
    if provider == "yfinance":
        return YahooFinanceProvider()
    if provider == "twelvedata":
        return TwelveDataProvider()
    raise ValueError(f"不支持的 MARKET_DATA_PROVIDER: {provider}")
