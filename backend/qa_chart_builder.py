from __future__ import annotations

from typing import Any


def build_qa_charts(question_type: str, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    builders = {
        "smalltalk": [
            _build_prediction_line_chart,
            _build_market_stat_strip,
            _build_news_stat_strip,
            _build_prediction_stat_strip,
            _build_ai_analysis_stat_strip,
        ],
        "prediction": [
            _build_prediction_line_chart,
            _build_prediction_split_meter,
            _build_prediction_driver_chart,
            _build_prediction_stat_strip,
        ],
        "news": [
            _build_news_sentiment_chart,
            _build_news_distribution_chart,
            _build_news_region_chart,
            _build_news_stat_strip,
        ],
        "factor": [
            _build_factor_impact_chart,
            _build_factor_split_meter,
            _build_factor_snapshot_chart,
            _build_factor_stat_strip,
        ],
        "strategy": [
            _build_prediction_line_chart,
            _build_strategy_split_meter,
            _build_prediction_driver_chart,
            _build_strategy_stat_strip,
        ],
    }
    fallback_builders = [
        _build_prediction_line_chart,
        _build_prediction_driver_chart,
        _build_prediction_stat_strip,
        _build_market_change_chart,
        _build_market_stat_strip,
        _build_ai_analysis_stat_strip,
        _build_factor_snapshot_chart,
        _build_news_region_chart,
    ]
    charts_by_id: dict[str, dict[str, Any]] = {}
    for builder in builders.get(question_type, builders["prediction"]):
        chart = builder(bundle)
        if chart and chart.get("id"):
            charts_by_id[chart["id"]] = chart
    for builder in fallback_builders:
        if len(charts_by_id) >= 5:
            break
        chart = builder(bundle)
        if chart and chart.get("id") and chart["id"] not in charts_by_id:
            charts_by_id[chart["id"]] = chart
    charts = sorted(charts_by_id.values(), key=lambda item: int(item.get("priority", 999)))
    return charts[:5]


def _build_prediction_line_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction_chart = bundle.get("prediction_chart")
    if not prediction_chart:
        return None
    history = prediction_chart.get("history", [])[-6:]
    projection = prediction_chart.get("projection", [])[:6]
    if not history and not projection:
        return None
    points = [
        {"label": item["observed_at"][5:10], "value": round(float(item["close"]), 2), "series": "历史"}
        for item in history
    ] + [
        {"label": item["date"][5:10], "value": round(float(item["prediction"]), 2), "series": "预测"}
        for item in projection
    ]
    return {
        "id": "prediction-line",
        "kind": "line",
        "title": "WTI 历史与短期预测",
        "subtitle": "最近 6 个历史点 + 未来 6 个预测点",
        "priority": 1,
        "data": {"points": points},
        "footnote": "基于站内已发布预测结果拼装",
    }


def _build_prediction_split_meter(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    if not prediction:
        return None
    movers = prediction.get("topMovers", [])[:6]
    positive = sum(max(float(item.get("impactScore", 0) or 0), 0) for item in movers)
    negative = sum(abs(min(float(item.get("impactScore", 0) or 0), 0)) for item in movers)
    total = positive + negative
    if total <= 0:
        return None
    return {
        "id": "prediction-balance",
        "kind": "split-meter",
        "title": "驱动倾向",
        "subtitle": "多空驱动占比",
        "priority": 2,
        "data": {
            "segments": [
                {"label": "上行驱动", "value": round((positive / total) * 100, 1), "tone": "positive"},
                {"label": "下行驱动", "value": round((negative / total) * 100, 1), "tone": "negative"},
            ]
        },
        "footnote": prediction.get("riskSignal") or "来源于 top movers 影响分解",
    }


def _build_prediction_driver_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    if not prediction:
        return None
    movers = prediction.get("topMovers", [])[:5]
    if not movers:
        return None
    return {
        "id": "prediction-drivers",
        "kind": "bars",
        "title": "关键驱动分解",
        "subtitle": "当前判断对应的主导因子强弱",
        "priority": 3,
        "data": {
            "items": [
                {"label": item.get("factor", "未知因子"), "value": round(float(item.get("impactScore", 0) or 0), 2)}
                for item in movers
            ]
        },
        "footnote": "正负值分别表示上行或下行拉动",
    }


def _build_prediction_stat_strip(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    if not prediction:
        return None
    stats = []
    forecast_value = prediction.get("next10DayForecast")
    if forecast_value:
        stats.append({"label": "预测区间", "value": str(forecast_value), "tone": "neutral"})
    if prediction.get("riskSignal"):
        stats.append({"label": "风险信号", "value": str(prediction.get("riskSignal")), "tone": "warning"})
    top_mover = next((item for item in prediction.get("topMovers", []) if item.get("factor")), None)
    if top_mover:
        stats.append({"label": "主导因子", "value": str(top_mover.get("factor")), "tone": "accent"})
    if not stats:
        return None
    return {
        "id": "prediction-stats",
        "kind": "stat-strip",
        "title": "预测摘要带",
        "subtitle": "本次回答引用的核心预测指标",
        "priority": 4,
        "data": {"stats": stats[:3]},
        "footnote": "仅展示当前回答使用到的关键摘要",
    }


def _build_news_sentiment_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    news = bundle.get("news_overview")
    if not news:
        return None
    series = news.get("sentimentSeries", [])[-6:]
    if not series:
        return None
    return {
        "id": "news-sentiment",
        "kind": "bars",
        "title": "新闻情绪脉冲",
        "subtitle": "最近样本情绪均值",
        "priority": 1,
        "data": {
            "items": [
                {"label": item["label"], "value": round(float(item["sentiment"]), 2)}
                for item in series
            ]
        },
        "footnote": "情绪值越高，偏多语义越强",
    }


def _build_news_distribution_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    news = bundle.get("news_overview")
    if not news:
        return None
    distribution = news.get("topicDistribution", [])[:5]
    if not distribution:
        return None
    return {
        "id": "news-topics",
        "kind": "bars",
        "title": "热点主题分布",
        "subtitle": "近期新闻关注主题",
        "priority": 2,
        "data": {
            "items": [
                {"label": item["label"], "value": round(float(item.get("count", item.get("value", 0)) or 0), 2)}
                for item in distribution
            ]
        },
        "footnote": "按主题标签提及频次排序",
    }


def _build_news_region_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    news = bundle.get("news_overview")
    if not news:
        return None
    regions = news.get("regionalRiskData", [])[:5]
    if not regions:
        return None
    return {
        "id": "news-regions",
        "kind": "bars",
        "title": "地缘热区分布",
        "subtitle": "近期新闻中高频区域",
        "priority": 3,
        "data": {
            "items": [
                {"label": item.get("label", "未知区域"), "value": round(float(item.get("count", item.get("value", 0)) or 0), 2)}
                for item in regions
            ]
        },
        "footnote": "按区域实体提及频次聚合",
    }


def _build_news_stat_strip(bundle: dict[str, Any]) -> dict[str, Any] | None:
    news = bundle.get("news_overview")
    if not news:
        return None
    summary = news.get("summary", {})
    stats = [
        {"label": "样本量", "value": str(summary.get("articleCount", 0)), "tone": "neutral"},
        {"label": "主主题", "value": str(summary.get("primaryTopic") or "暂无"), "tone": "accent"},
        {"label": "风险热度", "value": str(summary.get("averageRisk") or 0), "tone": "warning"},
    ]
    return {
        "id": "news-stats",
        "kind": "stat-strip",
        "title": "新闻摘要带",
        "subtitle": "问答中引用的新闻上下文",
        "priority": 4,
        "data": {"stats": stats},
        "footnote": "来源于当前新闻概览聚合结果",
    }


def _build_factor_impact_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    if not prediction:
        return None
    movers = prediction.get("topMovers", [])[:5]
    if not movers:
        return None
    return {
        "id": "factor-impacts",
        "kind": "bars",
        "title": "主导因子",
        "subtitle": "当前模型解释中的关键因子",
        "priority": 1,
        "data": {
            "items": [
                {"label": item.get("factor", "未知因子"), "value": round(float(item.get("impactScore", 0)), 2)}
                for item in movers
            ]
        },
        "footnote": "值越大表示对当前判断影响越强",
    }


def _build_factor_split_meter(bundle: dict[str, Any]) -> dict[str, Any] | None:
    factors = bundle.get("factors", {}).get("rows", [])[:10]
    if not factors:
        return None
    positive = 0
    negative = 0
    for row in factors:
        numeric_values = [value for value in row.values() if isinstance(value, (int, float))]
        if not numeric_values:
            continue
        probe = float(numeric_values[-1])
        if probe >= 0:
            positive += 1
        else:
            negative += 1
    total = positive + negative
    if total <= 0:
        return None
    return {
        "id": "factor-bias",
        "kind": "split-meter",
        "title": "因子方向",
        "subtitle": "抽样行的方向分布",
        "priority": 2,
        "data": {
            "segments": [
                {"label": "偏正向", "value": round((positive / total) * 100, 1), "tone": "positive"},
                {"label": "偏负向", "value": round((negative / total) * 100, 1), "tone": "negative"},
            ]
        },
        "footnote": "仅作问答摘要拼图，不替代完整因子表",
    }


def _build_factor_snapshot_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    factor_rows = bundle.get("factors", {}).get("rows", [])
    if not factor_rows:
        return None
    latest_row = factor_rows[0]
    candidates = []
    for label, value in latest_row.items():
        if label in {"Date", "date", "id"} or not isinstance(value, (int, float)):
            continue
        numeric = round(float(value), 2)
        if numeric == 0:
            continue
        candidates.append({"label": str(label), "value": numeric})
    if not candidates:
        return None
    candidates.sort(key=lambda item: abs(item["value"]), reverse=True)
    return {
        "id": "factor-snapshot",
        "kind": "bars",
        "title": "最新因子切面",
        "subtitle": "最近一行因子样本中的显著变量",
        "priority": 3,
        "data": {"items": candidates[:5]},
        "footnote": "从最新因子行提取绝对值较高的字段",
    }


def _build_factor_stat_strip(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    factor_rows = bundle.get("factors", {}).get("rows", [])
    if not prediction and not factor_rows:
        return None
    top_movers = prediction.get("topMovers", []) if prediction else []
    stats = []
    if top_movers:
        stats.append({"label": "关键因子数", "value": str(len(top_movers[:5])), "tone": "neutral"})
        stats.append({"label": "第一驱动", "value": str(top_movers[0].get("factor", "未知")), "tone": "accent"})
    if factor_rows:
        stats.append({"label": "因子样本", "value": str(len(factor_rows)), "tone": "neutral"})
    if not stats:
        return None
    return {
        "id": "factor-stats",
        "kind": "stat-strip",
        "title": "因子摘要带",
        "subtitle": "当前因子归因的核心摘要",
        "priority": 4,
        "data": {"stats": stats[:3]},
        "footnote": "综合预测摘要与因子表可用数据",
    }


def _build_strategy_split_meter(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    news = bundle.get("news_overview")
    if not prediction and not news:
        return None
    risk_signal = str((prediction or {}).get("riskSignal", "")).lower()
    avg_risk = float((news or {}).get("summary", {}).get("averageRisk", 0) or 0)
    defensive = 60.0 if "高" in risk_signal else 48.0
    defensive = max(defensive, min(avg_risk, 82.0))
    offensive = max(100.0 - defensive, 18.0)
    total = defensive + offensive
    return {
        "id": "strategy-balance",
        "kind": "split-meter",
        "title": "策略重心",
        "subtitle": "防御与进攻动作配比",
        "priority": 2,
        "data": {
            "segments": [
                {"label": "风险防御", "value": round((defensive / total) * 100, 1), "tone": "warning"},
                {"label": "机会跟进", "value": round((offensive / total) * 100, 1), "tone": "positive"},
            ]
        },
        "footnote": "根据风险信号与新闻热度派生",
    }


def _build_strategy_stat_strip(bundle: dict[str, Any]) -> dict[str, Any] | None:
    prediction = bundle.get("prediction")
    news = bundle.get("news_overview")
    stats = []
    if prediction and prediction.get("riskSignal"):
        stats.append({"label": "当前风险", "value": str(prediction.get("riskSignal")), "tone": "warning"})
    if news:
        summary = news.get("summary", {})
        stats.append({"label": "新闻样本", "value": str(summary.get("articleCount", 0)), "tone": "neutral"})
        if summary.get("primaryRegion"):
            stats.append({"label": "焦点区域", "value": str(summary.get("primaryRegion")), "tone": "accent"})
    if not stats:
        return None
    return {
        "id": "strategy-stats",
        "kind": "stat-strip",
        "title": "策略上下文",
        "subtitle": "当前建议动作所依赖的环境摘要",
        "priority": 4,
        "data": {"stats": stats[:3]},
        "footnote": "站内预测与新闻上下文组合",
    }


def _build_market_change_chart(bundle: dict[str, Any]) -> dict[str, Any] | None:
    ticker = bundle.get("ticker")
    if not ticker:
        return None
    items = ticker.get("items", [])[:5]
    if not items:
        return None
    return {
        "id": "market-changes",
        "kind": "bars",
        "title": "市场变动截面",
        "subtitle": "当前主要行情指标的日变动",
        "priority": 5,
        "data": {
            "items": [
                {"label": item.get("label", "市场指标"), "value": round(float(item.get("changePercent", 0) or 0), 2)}
                for item in items
            ]
        },
        "footnote": "以日度涨跌幅刻画市场联动方向",
    }


def _build_market_stat_strip(bundle: dict[str, Any]) -> dict[str, Any] | None:
    ticker = bundle.get("ticker")
    if not ticker:
        return None
    items = ticker.get("items", [])[:3]
    if not items:
        return None
    stats = [
        {
            "label": item.get("label", "市场指标"),
            "value": item.get("displayValue", "--"),
            "tone": "accent" if item.get("direction") == "up" else "warning" if item.get("direction") == "down" else "neutral",
        }
        for item in items
    ]
    return {
        "id": "market-strip",
        "kind": "stat-strip",
        "title": "市场快照摘要",
        "subtitle": "当前回答引用的即时行情",
        "priority": 6,
        "data": {"stats": stats},
        "footnote": "基于当前市场快照拼装",
    }


def _build_ai_analysis_stat_strip(bundle: dict[str, Any]) -> dict[str, Any] | None:
    analysis = bundle.get("ai_analysis")
    if not analysis:
        return None
    stats = []
    drivers = analysis.get("drivers") or []
    if drivers:
        stats.append({"label": "AI 驱动数", "value": str(len(drivers[:5])), "tone": "neutral"})
        stats.append({"label": "首要驱动", "value": str(drivers[0]), "tone": "accent"})
    if analysis.get("predictionDate"):
        stats.append({"label": "分析日期", "value": str(analysis.get("predictionDate")), "tone": "neutral"})
    if not stats:
        return None
    return {
        "id": "ai-analysis-strip",
        "kind": "stat-strip",
        "title": "AI 分析摘要",
        "subtitle": "独立 AI 日报中的稳定要点",
        "priority": 7,
        "data": {"stats": stats[:3]},
        "footnote": "仅取 AI 分析结果中的结构化字段",
    }
