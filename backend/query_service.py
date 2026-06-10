from __future__ import annotations

from typing import Any

from . import core_backend as backend_core
from .runtime_store import RuntimeStore


VIEW_TO_SOURCE = {
    "latest_prices": "market",
    "latest_news": backend_core.NEWS_SOURCE_KEY,
    "latest_factors": "factors",
    "latest_model": "model",
    "latest_ai_report": "ai_analysis",
}

PREDICTION_CHART_RANGE_LIMITS = {
    "1M": 30,
    "3M": 92,
    "1Y": 366,
}

class QueryService:
    def __init__(self, runtime_store: RuntimeStore, database=None):
        self.database = database or backend_core.create_database()
        self.runtime_store = runtime_store

    def _meta(self, view_key: str) -> dict[str, Any]:
        published = self.runtime_store.get_published_view(view_key)
        if not published:
            raise RuntimeError(f"视图 `{view_key}` 尚未发布")
        source_key = VIEW_TO_SOURCE.get(view_key)
        source_status = self.database.get_source_status().get(source_key, {}) if source_key else {}
        source_payload = source_status.get("payload", {})
        stale = bool(published["stale"]) or source_payload.get("status") == "failed"
        return {
            "viewKey": view_key,
            "batchId": published["batchId"],
            "dataAsOf": published["dataAsOf"],
            "generatedAt": published["generatedAt"],
            "publishedAt": published["publishedAt"],
            "servedAt": backend_core.iso_now(),
            "stale": stale,
            "sourceStatus": source_status,
            "inputBatches": self.runtime_store.list_batch_inputs(published["batchId"]),
        }

    def _factor_rows(self) -> list[dict[str, Any]]:
        return self.database.get_factor_rows(limit=2000)

    def _fallback_feature_importance(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        feature_importance = payload.get("featureImportance")
        if isinstance(feature_importance, list) and feature_importance:
            return feature_importance
        top_movers = payload.get("topMovers")
        if not isinstance(top_movers, list):
            return []
        fallback = []
        for index, item in enumerate(top_movers[:5]):
            factor = item.get("factor") if isinstance(item, dict) else None
            if not factor:
                continue
            fallback.append(
                {
                    "feature": factor,
                    "value": max(5, 100 - index * 12),
                }
            )
        return fallback

    def _merge_prediction_summary_with_ai(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(payload)
        merged["featureImportance"] = self._fallback_feature_importance(merged)
        ai_output = self.database.get_model_output("prediction_ai_analysis")
        if not ai_output:
            return merged

        ai_payload = dict(ai_output["payload"])
        corporate_view = ((ai_payload.get("views") or {}).get("corporate") or {})
        merged["aiInsightSummary"] = (
            str(ai_payload.get("previewSummary", "")).strip()
            or backend_core.build_ai_preview_summary(
                str(corporate_view.get("body", "")),
                str(ai_payload.get("predictionSummary", merged.get("insight", ""))),
            )
        )
        merged["aiInsightPreview"] = merged["aiInsightSummary"]
        merged["aiAnalysisAvailable"] = True
        merged["aiAnalysisUpdatedAt"] = ai_payload.get("generatedAt", ai_output["as_of"])
        return merged

    def _build_prediction_history_from_factors(self, range_key: str, model_as_of: str | None) -> list[dict[str, Any]]:
        limit = PREDICTION_CHART_RANGE_LIMITS.get(range_key)
        if limit is None:
            raise ValueError(f"不支持的 prediction range: {range_key}")

        cutoff = backend_core.parse_flexible_datetime(model_as_of) if model_as_of else None
        cutoff_date = cutoff.date().isoformat() if cutoff else None
        factor_rows = self.database.get_factor_history_rows(limit=limit, end_date=cutoff_date)
        filtered_rows = []
        for row in factor_rows:
            row_date = str(row.get("Date") or "").strip()
            if not row_date:
                continue
            if cutoff_date and row_date > cutoff_date:
                continue
            close_value = row.get("WTI_Close")
            if close_value in {None, ""}:
                continue
            filtered_rows.append(
                {
                    "observed_at": f"{row_date}T00:00:00+00:00",
                    "open": float(row.get("WTI_Open", close_value)),
                    "high": float(row.get("WTI_High", close_value)),
                    "low": float(row.get("WTI_Low", close_value)),
                    "close": float(close_value),
                    "source_updated_at": model_as_of or row_date,
                }
            )
        return self._attach_wti_moving_averages(filtered_rows[-limit:])

    def _attach_wti_moving_averages(self, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        windows = (5, 20, 60)
        window_sums = {window: 0.0 for window in windows}
        closes: list[float] = []
        enriched = []
        for point in points:
            close_value = float(point["close"])
            closes.append(close_value)
            item = dict(point)
            item["price"] = round(close_value, 4)
            for window in windows:
                key = f"ma{window}"
                window_sums[window] += close_value
                if len(closes) > window:
                    window_sums[window] -= closes[-window - 1]
                if len(closes) < window:
                    item[key] = None
                    continue
                item[key] = round(window_sums[window] / window, 4)
            enriched.append(item)
        return enriched

    def _resolve_market_chart_rows(
        self,
        symbol: str,
        range_key: str,
        chart_kind: str = "main",
        viewport_width: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        profile = backend_core.resolve_market_chart_profile(range_key, chart_kind=chart_kind)
        if profile["layer"] == "aggregate":
            points = self.database.get_market_aggregate_bars(symbol, profile["granularity"], profile["limit"])
            if points:
                return points, profile, "aggregate"
            source_limit = backend_core.resolve_display_source_limit(profile)
            fallback_points = self.database.get_market_bars(symbol, profile["fallback_granularity"], source_limit)
            rebuilt_points = backend_core.aggregate_market_bars(fallback_points, profile["granularity"])
            return rebuilt_points[-profile["limit"] :], profile, "aggregate_fallback"
        points = self.database.get_market_bars(symbol, profile["granularity"], profile["limit"])
        source_layer = "raw"
        target_points = backend_core.resolve_main_chart_target_points(viewport_width)
        if chart_kind == "main" and profile["granularity"] == "1m" and len(points) > target_points:
            points = backend_core.downsample_market_bars_by_time(points, target_points)
            source_layer = "raw_downsampled"
        return points, profile, source_layer

    def get_market_ticker(self) -> dict[str, Any]:
        items = []
        latest_update = None
        for symbol in backend_core.MARKET_SYMBOLS:
            daily_bars = self.database.get_market_bars(symbol, "1d", 2)
            sparkline_source, _, _ = self._resolve_market_chart_rows(symbol, "1D", chart_kind="sparkline")
            if len(daily_bars) < 2:
                continue
            latest = daily_bars[-1]
            previous = daily_bars[-2]
            current = float(latest["close"])
            prev = float(previous["close"])
            change_value = current - prev
            change_percent = 0.0 if prev == 0 else (change_value / prev) * 100
            latest_update = latest_update or latest["source_updated_at"]
            items.append(
                {
                    "id": symbol,
                    "label": backend_core.get_market_series_definition(symbol).label,
                    "value": round(current, 4),
                    "displayValue": f"{current:.2f}",
                    "changePercent": round(change_percent, 2),
                    "direction": "up" if change_percent >= 0 else "down",
                    "sparkline": [{"value": round(float(bar["close"]), 4)} for bar in sparkline_source],
                    "updatedAt": latest["source_updated_at"],
                }
            )
        if not items:
            raise RuntimeError("暂无行情数据，请先完成市场数据同步")
        return {"items": items, "updatedAt": latest_update or backend_core.iso_now(), "meta": self._meta("latest_prices")}

    def get_market_chart(
        self,
        symbol: str,
        range_key: str,
        chart_kind: str = "main",
        viewport_width: int | None = None,
    ) -> dict[str, Any]:
        points, profile, source_layer = self._resolve_market_chart_rows(
            symbol,
            range_key,
            chart_kind=chart_kind,
            viewport_width=viewport_width,
        )
        if symbol == "WTI_Close" and points:
            points = self._attach_wti_moving_averages(points)
        return {
            "symbol": symbol,
            "range": range_key,
            "chartKind": chart_kind,
            "granularity": profile["granularity"],
            "sourceLayer": source_layer,
            "points": points,
            "targetPoints": backend_core.resolve_main_chart_target_points(viewport_width) if chart_kind == "main" else None,
            "updatedAt": points[-1]["source_updated_at"] if points else None,
            "meta": self._meta("latest_prices"),
        }

    def get_market_charts_batch(
        self,
        symbols: list[str],
        range_key: str,
        chart_kind: str = "sparkline",
    ) -> dict[str, Any]:
        items: dict[str, Any] = {}
        updated_at = None
        for symbol in symbols:
            if symbol not in backend_core.MARKET_SYMBOLS:
                continue
            chart = self.get_market_chart(symbol, range_key, chart_kind=chart_kind)
            items[symbol] = chart
            updated_at = updated_at or chart.get("updatedAt")
        return {
            "items": items,
            "range": range_key,
            "chartKind": chart_kind,
            "updatedAt": updated_at or backend_core.iso_now(),
            "meta": self._meta("latest_prices"),
        }

    def get_dashboard_overview(self) -> dict[str, Any]:
        ticker = self.get_market_ticker()
        output = self.database.get_model_output("dashboard_overview")
        if not output:
            raise RuntimeError("暂无模型结果，请先运行模型任务")
        payload = {
            "metrics": ticker["items"],
            **output["payload"],
            "updatedAt": output["as_of"],
            "meta": self._meta("latest_model"),
        }
        return payload

    def get_prediction_summary(self) -> dict[str, Any]:
        output = self.database.get_model_output("prediction_summary")
        if not output:
            raise RuntimeError("暂无模型结果，请先运行模型任务")
        payload = self._merge_prediction_summary_with_ai(dict(output["payload"]))
        payload["updatedAt"] = output["as_of"]
        payload["meta"] = self._meta("latest_model")
        return payload

    def get_prediction_chart(self, range_key: str) -> dict[str, Any]:
        output = self.database.get_model_output("prediction_chart")
        if not output:
            raise RuntimeError("暂无模型图表结果，请先运行模型任务")
        model_as_of = output["as_of"]
        history_points = self._build_prediction_history_from_factors(range_key, model_as_of)
        return {
            "history": history_points,
            "projection": output["payload"]["projection"],
            "method": output["payload"].get("method"),
            "horizonDays": output["payload"].get("horizonDays"),
            "priceInterval": output["payload"].get("priceInterval"),
            "historySource": "factor_rows",
            "granularity": "1d",
            "range": range_key,
            "updatedAt": output["as_of"],
            "meta": self._meta("latest_model"),
        }

    def get_prediction_ai_analysis(self) -> dict[str, Any]:
        output = self.database.get_model_output("prediction_ai_analysis")
        if not output:
            raise RuntimeError("暂无 AI 分析结果，请先运行 AI 分析任务")
        payload = dict(output["payload"])
        payload["updatedAt"] = output["as_of"]
        payload["meta"] = self._meta("latest_ai_report")
        payload["stale"] = payload["meta"]["stale"]
        if payload["meta"]["sourceStatus"].get("payload", {}).get("status") == "failed":
            payload["lastError"] = str(payload["meta"]["sourceStatus"]["payload"].get("last_error", ""))
        else:
            payload["lastError"] = ""
        return payload

    def get_factor_table(self, query: str = "", limit: int = 80) -> dict[str, Any]:
        return {
            "columns": backend_core.FACTOR_COLUMNS,
            "rows": self.database.get_factor_rows(limit=limit, query=query),
            "updatedAt": backend_core.iso_now(),
            "meta": self._meta("latest_factors"),
        }

    def get_news_list(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        limit: int = 80,
        timezone_name: str | None = "UTC",
    ) -> dict[str, Any]:
        return {
            "items": self.database.get_news_articles(start=start, end=end, query=query, limit=limit, timezone_name=timezone_name),
            "total": self.database.count_news_articles(start=start, end=end, query=query, timezone_name=timezone_name),
            "updatedAt": backend_core.iso_now(),
            "meta": self._meta("latest_news"),
        }

    def _build_news_overview_payload(
        self,
        items: list[dict[str, Any]],
        *,
        source_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_source_status = source_status or self.database.get_source_status().get(backend_core.NEWS_SOURCE_KEY, {})
        if not items:
            return {
                "summary": {
                    "articleCount": 0,
                    "averageSentiment": "0.00",
                    "positiveCount": 0,
                    "negativeCount": 0,
                    "averageRisk": 0,
                    "averageMentions": 0,
                    "primaryTopic": "",
                    "primaryRegion": "",
                },
                "insightText": "当前筛选窗口内新闻样本不足，情绪与主题信号暂未形成有效共振，建议适当放宽时间范围以获取更稳定的事件脉冲。",
                "sentimentSeries": [],
                "regionalRiskData": [],
                "entityTags": [],
                "topicDistribution": [],
                "sourceStatus": resolved_source_status,
                "updatedAt": backend_core.iso_now(),
                "meta": self._meta("latest_news"),
            }

        average_sentiment = sum(item["sentiment"] for item in items) / len(items)
        average_risk = sum(item["risk"] for item in items) / len(items)
        average_mentions = sum(item["mentionCount"] for item in items) / len(items)
        positive_count = len([item for item in items if item["sentiment"] > 0.05])
        negative_count = len([item for item in items if item["sentiment"] < -0.05])
        sentiment_series = [
            {
                "label": item["publishedDate"],
                "sentiment": item["sentiment"],
                "title": item["title"],
                "date": item["publishedDate"],
                "publishedAt": item["publishedAt"],
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
        max_topic = max((item["count"] for item in topic_distribution), default=1)
        topic_distribution = [
            {
                **item,
                "value": int(round((item["count"] / max_topic) * 100)) if max_topic else 0,
            }
            for item in topic_distribution
        ]
        primary_topic = topic_distribution[0]["label"] if topic_distribution else ""
        primary_region = regional_risk_data[0]["label"] if regional_risk_data else ""
        return {
            "summary": {
                "articleCount": len(items),
                "averageSentiment": f"{average_sentiment:.2f}",
                "positiveCount": positive_count,
                "negativeCount": negative_count,
                "averageRisk": int(round(average_risk)),
                "averageMentions": int(round(average_mentions)),
                "primaryTopic": primary_topic,
                "primaryRegion": primary_region,
            },
            "insightText": self._build_news_insight_text(
                article_count=len(items),
                average_sentiment=average_sentiment,
                positive_count=positive_count,
                negative_count=negative_count,
                average_risk=average_risk,
                primary_topic=primary_topic,
                primary_region=primary_region,
            ),
            "sentimentSeries": sentiment_series,
            "regionalRiskData": regional_risk_data,
            "entityTags": entity_tags,
            "topicDistribution": topic_distribution,
            "sourceStatus": resolved_source_status,
            "updatedAt": backend_core.iso_now(),
            "meta": self._meta("latest_news"),
        }

    def get_news_date_bounds(self, timezone_name: str | None = "UTC") -> dict[str, Any]:
        return {
            **self.database.get_news_date_bounds(timezone_name=timezone_name),
            "updatedAt": backend_core.iso_now(),
            "meta": self._meta("latest_news"),
        }

    def _classify_news_sentiment(self, average_sentiment: float, positive_count: int, negative_count: int) -> str:
        if positive_count == 0 and negative_count == 0:
            return "整体情绪偏中性"
        if average_sentiment >= 0.12 or positive_count >= negative_count + 3:
            return "整体情绪偏多"
        if average_sentiment <= -0.12 or negative_count >= positive_count + 3:
            return "整体情绪偏空"
        return "整体情绪分化"

    def _classify_news_risk(self, average_risk: float) -> str:
        if average_risk >= 67:
            return "高关注"
        if average_risk >= 34:
            return "中等关注"
        return "低关注"

    def _build_news_insight_text(
        self,
        article_count: int,
        average_sentiment: float,
        positive_count: int,
        negative_count: int,
        average_risk: float,
        primary_topic: str,
        primary_region: str,
    ) -> str:
        if article_count <= 0:
            return "当前筛选窗口内新闻样本不足，情绪与主题信号暂未形成有效共振，建议适当放宽时间范围以获取更稳定的事件脉冲。"

        sentiment_bias = "偏多" if average_sentiment >= 0 else "偏空"
        risk_level = self._classify_news_risk(average_risk)
        topic_text = primary_topic or "暂无明确主题"
        region_text = primary_region or "跨区域分散"
        return (
            f"当前筛选窗口内共纳入 {article_count} 条新闻样本，正向新闻 {positive_count} 条、负向新闻 {negative_count} 条，"
            f"整体语义基调{sentiment_bias}。"
            f"主题热度主要集中在 {topic_text}，地缘扰动焦点位于 {region_text}，"
            f"综合风险信号处于{risk_level}区间，建议结合事件演化持续跟踪后续脉冲变化。"
        )

    def get_news_overview(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        limit: int = 120,
        timezone_name: str | None = "UTC",
    ) -> dict[str, Any]:
        items = self.database.get_news_articles(start=start, end=end, query=query, limit=limit, timezone_name=timezone_name)
        source_status = self.database.get_source_status().get(backend_core.NEWS_SOURCE_KEY, {})
        return self._build_news_overview_payload(items, source_status=source_status)

    def get_news_feed(
        self,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        list_limit: int = 80,
        overview_limit: int = 120,
        timezone_name: str | None = "UTC",
    ) -> dict[str, Any]:
        effective_limit = max(list_limit, overview_limit)
        items = self.database.get_news_articles(
            start=start,
            end=end,
            query=query,
            limit=effective_limit,
            timezone_name=timezone_name,
        )
        source_status = self.database.get_source_status().get(backend_core.NEWS_SOURCE_KEY, {})
        total = self.database.count_news_articles(start=start, end=end, query=query, timezone_name=timezone_name)
        date_bounds = self.database.get_news_date_bounds(timezone_name=timezone_name)
        return {
            "list": {
                "items": items[:list_limit],
                "total": total,
                "updatedAt": backend_core.iso_now(),
                "meta": self._meta("latest_news"),
            },
            "overview": self._build_news_overview_payload(items[:overview_limit], source_status=source_status),
            "dateBounds": {
                **date_bounds,
                "updatedAt": backend_core.iso_now(),
                "meta": self._meta("latest_news"),
            },
            "updatedAt": backend_core.iso_now(),
            "meta": self._meta("latest_news"),
        }

    def get_news_detail(self, article_id: str) -> dict[str, Any]:
        item = self.database.get_news_article_detail(article_id)
        if not item:
            raise ValueError("新闻不存在")
        item["meta"] = self._meta("latest_news")
        return item

    def get_status(self) -> dict[str, Any]:
        return {
            "sources": self.database.get_source_status(),
            "views": self.runtime_store.list_views(),
            "runs": self.runtime_store.list_recent_task_runs(),
            "updatedAt": backend_core.iso_now(),
        }
