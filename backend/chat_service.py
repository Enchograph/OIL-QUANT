from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from uuid import uuid4

from openai import OpenAI

from . import core_backend as backend_core
from .ai_advisory import create_pipeline, get_chat_completion_options, load_project_env, normalize_openai_base_url
from .qa_chart_builder import build_qa_charts

LOGGER = logging.getLogger("backend.chat_service")
CHAT_ROUTE_TIMEOUT_SECONDS = 20
CHAT_ROUTE_MAX_TOKENS = 360
SMALLTALK_CONFIDENCE_HIGH = "high"
SMALLTALK_ROUTE = "smalltalk"
QUESTION_ROUTES = {SMALLTALK_ROUTE, "prediction", "news", "factor", "strategy"}
DOMAIN_KEYWORDS = (
    "油价", "原油", "wti", "brent", "新闻", "资讯", "事件", "地缘", "情绪",
    "因子", "宏观", "美元", "vix", "库存", "opec", "套保", "对冲", "采购",
    "授信", "敞口", "策略", "建议", "企业", "银行", "风险", "走势", "行情",
    "市场", "预测", "driver", "hedge", "bank", "credit", "factor", "news",
    "price", "oil", "risk", "forecast", "trend", "market",
)


def _safe_json_loads(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _first_sentence(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    for delimiter in ("。", "\n", ".", "；", ";"):
        if delimiter in text:
            head = text.split(delimiter, 1)[0].strip()
            if head:
                return head
    return text[:120]


def _normalize_text_value(value: Any) -> str:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.replace("\n", " ")).strip()
    if isinstance(value, list):
        parts = [
            re.sub(r"\s+", " ", item.replace("\n", " ")).strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]
        return " ".join(parts).strip()
    return ""


class ChatOrchestrator:
    def __init__(self, query_service):
        self.query_service = query_service
        self._pipeline = None
        self._chat_client = None
        self._chat_model = None

    def _get_pipeline(self):
        if self._pipeline is None:
            self._pipeline = create_pipeline(backend_core.GENERATED_DIR)
        return self._pipeline

    def _get_chat_client(self) -> tuple[OpenAI, str]:
        if self._chat_client is not None and self._chat_model is not None:
            return self._chat_client, self._chat_model
        load_project_env()
        api_key = os.getenv("AI_CHAT_API_KEY", "").strip() or os.getenv("AI_OPENAI_API_KEY", "").strip()
        model = os.getenv("AI_CHAT_MODEL", "").strip()
        base_url = normalize_openai_base_url(
            os.getenv("AI_CHAT_BASE_URL", "").strip() or os.getenv("AI_OPENAI_BASE_URL", "").strip() or None
        )
        if not api_key:
            raise RuntimeError("缺少配置 AI_CHAT_API_KEY，无法启用智能问答")
        if not model:
            raise RuntimeError("缺少配置 AI_CHAT_MODEL，无法启用智能问答")
        self._chat_client = OpenAI(api_key=api_key, base_url=base_url)
        self._chat_model = model
        return self._chat_client, self._chat_model

    def get_bootstrap(self) -> dict[str, Any]:
        prediction = self._try_query(self.query_service.get_prediction_summary)
        news = self._try_query(lambda: self.query_service.get_news_overview(limit=40))
        ticker = self._try_query(self.query_service.get_market_ticker)
        ai_analysis = self._try_query(self.query_service.get_prediction_ai_analysis)
        contexts = []
        if prediction:
            contexts.append(
                {
                    "id": "prediction",
                    "label": "预测模型",
                    "detail": prediction.get("next10DayForecast") or "已加载",
                    "timestamp": prediction.get("updatedAt"),
                    "status": "ready",
                }
            )
        if news:
            summary = news.get("summary", {})
            contexts.append(
                {
                    "id": "news",
                    "label": "新闻情绪",
                    "detail": f"{summary.get('articleCount', 0)} 条样本 / {summary.get('primaryTopic') or '暂无主主题'}",
                    "timestamp": news.get("updatedAt"),
                    "status": "ready" if summary.get("articleCount", 0) else "limited",
                }
            )
        if ticker:
            contexts.append(
                {
                    "id": "market",
                    "label": "市场快照",
                    "detail": f"{len(ticker.get('items', []))} 个行情指标",
                    "timestamp": ticker.get("updatedAt"),
                    "status": "ready",
                }
            )
        if ai_analysis:
            contexts.append(
                {
                    "id": "ai_analysis",
                    "label": "AI 日报",
                    "detail": _first_sentence(ai_analysis.get("predictionSummary", ""), "已生成"),
                    "timestamp": ai_analysis.get("updatedAt"),
                    "status": "stale" if ai_analysis.get("stale") else "ready",
                }
            )
        return {
            "welcome": "基于预测、新闻、因子与市场快照的全面分析助手。",
            "recommendedPrompts": [
                {
                    "id": "trend-drivers",
                    "group": "价格与趋势",
                    "label": "今天油价判断的关键驱动是什么？",
                    "question": "请结合当前预测、因子与新闻，解释今天油价判断的关键驱动是什么。",
                },
                {
                    "id": "news-vs-model",
                    "group": "驱动因素与新闻",
                    "label": "最近新闻情绪会怎样影响原油价格？",
                    "question": "最近的地缘政治与新闻情绪会怎样影响原油价格？",
                },
                {
                    "id": "corporate-strategy",
                    "group": "行业影响与策略建议",
                    "label": "企业现在应如何看风险暴露？",
                    "question": "如果从企业经营视角出发，当前应如何理解油价风险暴露，并给出建议动作？",
                },
                {
                    "id": "bank-strategy",
                    "group": "行业影响与策略建议",
                    "label": "银行应该怎样评估授信风险？",
                    "question": "如果从银行授信与敞口管理视角出发，当前应该怎样评估油价相关风险？",
                },
            ],
            "dataContexts": contexts,
            "meta": {"generatedAt": backend_core.iso_now()},
        }

    def ask(
        self,
        *,
        question: str,
        audience: str = "enterprise",
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not question.strip():
            raise ValueError("问题不能为空")
        ask_started_at = time.perf_counter()
        route = self._route_question(
            question=question,
            audience=audience,
            history=history or [],
            context=context or {},
        )
        question_type = route["route"]
        if question_type == SMALLTALK_ROUTE:
            prepare_started_at = time.perf_counter()
            bootstrap = self.get_bootstrap()
            raw_bundle = self._build_data_bundle("strategy")
            bundle = self._build_model_context_bundle("strategy", raw_bundle)
            charts = self._build_smalltalk_charts(raw_bundle, bootstrap)
            evidence = self._build_evidence(raw_bundle, [], charts)
            self._log_chat_stage(
                "chat_smalltalk_prepared",
                question_type=question_type,
                elapsed_ms=self._elapsed_ms(prepare_started_at),
                bundle_chars=len(json.dumps(bundle, ensure_ascii=False)),
                history_chars=self._history_chars(history or []),
                chart_count=len(charts),
            )
            answer = self._build_smalltalk_answer(
                audience=audience,
                raw_bundle=raw_bundle,
                charts=charts,
                route=route,
            )
            self._log_chat_stage(
                "chat_ask_completed",
                question_type=question_type,
                elapsed_ms=self._elapsed_ms(ask_started_at),
                bundle_chars=len(json.dumps(bundle, ensure_ascii=False)),
                history_chars=self._history_chars(history or []),
                chart_count=len(charts),
            )
            return {
                "session": {
                    "sessionId": session_id or uuid4().hex,
                    "answeredAt": backend_core.iso_now(),
                },
                "answer": answer,
                "evidence": evidence,
                "followups": self._build_followups(question_type, audience, {}),
                "meta": {
                    "audience": audience,
                    "questionType": question_type,
                    "contextSource": (context or {}).get("sourcePage", "qa"),
                    "generatedAt": backend_core.iso_now(),
                },
            }
        raw_bundle = self._build_data_bundle(question_type)
        bundle = self._build_model_context_bundle(question_type, raw_bundle)
        charts = self._build_charts(question_type, raw_bundle)
        primary_chart = charts[0] if charts else None
        knowledge_chunks = self._retrieve_knowledge(question, question_type)
        evidence = self._build_evidence(raw_bundle, knowledge_chunks, charts)
        response_payload = self._generate_response(
            question=question,
            audience=audience,
            question_type=question_type,
            bundle=bundle,
            knowledge_chunks=knowledge_chunks,
            history=history or [],
            context=context or {},
        )
        sections = self._build_sections(response_payload)
        followups = self._build_followups(question_type, audience, response_payload)
        self._log_chat_stage(
            "chat_ask_completed",
            question_type=question_type,
            elapsed_ms=self._elapsed_ms(ask_started_at),
            bundle_chars=len(json.dumps(bundle, ensure_ascii=False)),
            history_chars=self._history_chars(history or []),
            chart_count=len(charts),
            knowledge_count=len(knowledge_chunks),
        )
        return {
            "session": {
                "sessionId": session_id or uuid4().hex,
                "answeredAt": backend_core.iso_now(),
            },
            "answer": {
                "questionType": question_type,
                "audience": audience,
                "title": response_payload.get("title") or self._title_for(question_type, audience),
                "summary": response_payload.get("summary") or sections[0]["content"],
                "sections": sections,
                "usedDomains": self._used_domains(raw_bundle),
                "confidenceLabel": response_payload.get("confidenceLabel") or self._confidence_from_bundle(raw_bundle),
                "charts": charts,
                "chart": primary_chart,
            },
            "evidence": evidence,
            "followups": followups,
            "meta": {
                "audience": audience,
                "questionType": question_type,
                "contextSource": (context or {}).get("sourcePage", "qa"),
                "generatedAt": backend_core.iso_now(),
            },
        }

    def _try_query(self, fn):
        try:
            return fn()
        except Exception:
            return None

    def _fallback_route(self, question: str) -> dict[str, Any]:
        route = self._classify_question(question)
        return {
            "route": route,
            "needsDatabase": route != SMALLTALK_ROUTE,
            "needsKnowledge": route != SMALLTALK_ROUTE,
            "needsCharts": route != SMALLTALK_ROUTE,
            "smalltalkConfidence": "low",
            "reason": "fallback",
            "smalltalkPayload": None,
        }

    def _elapsed_ms(self, started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)

    def _history_chars(self, history: list[dict[str, Any]]) -> int:
        if not history:
            return 0
        return len(json.dumps(history[-4:], ensure_ascii=False))

    def _log_chat_stage(
        self,
        stage: str,
        *,
        question_type: str,
        elapsed_ms: int,
        bundle_chars: int | None = None,
        history_chars: int | None = None,
        chart_count: int | None = None,
        knowledge_count: int | None = None,
        route_reason: str | None = None,
        thinking_enabled: str | None = None,
        thinking_budget: str | None = None,
    ) -> None:
        client, model = self._get_chat_client()
        del client
        LOGGER.info(
            (
                "%s questionType=%s model=%s thinkingEnabled=%s thinkingBudget=%s "
                "elapsedMs=%s bundleChars=%s historyChars=%s chartCount=%s knowledgeCount=%s routeReason=%s"
            ),
            stage,
            question_type,
            model,
            thinking_enabled if thinking_enabled is not None else (os.getenv("AI_CHAT_ENABLE_THINKING", "").strip() or "unset"),
            thinking_budget if thinking_budget is not None else (os.getenv("AI_CHAT_THINKING_BUDGET", "").strip() or "unset"),
            elapsed_ms,
            bundle_chars if bundle_chars is not None else "-",
            history_chars if history_chars is not None else "-",
            chart_count if chart_count is not None else "-",
            knowledge_count if knowledge_count is not None else "-",
            route_reason or "-",
        )

    def _contains_domain_signal(self, question: str) -> bool:
        lowered = question.lower()
        return any(keyword in lowered for keyword in DOMAIN_KEYWORDS)

    def _route_question(
        self,
        *,
        question: str,
        audience: str,
        history: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        client, model = self._get_chat_client()
        system_prompt = """
你是问答入口路由器。你只负责判断这个用户问题该走哪条回答链路，不负责正式回答。
必须输出 JSON，且只能包含：
route, needsDatabase, needsKnowledge, needsCharts, smalltalkConfidence, reason, smalltalkPayload

规则：
- route 只能是 smalltalk / prediction / news / factor / strategy
- 只有非常明确的寒暄、感谢、身份询问、能力询问、简单闲聊，且不要求油价/市场/新闻/预测/策略信息时，才允许 route=smalltalk
- “你好”“hello”“hi”“在吗”“你是谁”“你能做什么” 这类纯寒暄或能力询问，优先归为 smalltalk
- 只要用户问题涉及油价、市场、新闻、预测、因子、企业、银行、策略、风险、建议、数据、图表、最近情况，就不能归为 smalltalk
- “你好，顺便看看今天油价”“在吗，帮我分析一下” 这类必须归到分析链路
- 当问题是在泛泛询问油价、走势、行情、价格判断，而没有明确要求新闻、因子或策略拆解时，优先归为 prediction
- 当你不确定时，优先不要判为 smalltalk
- smalltalkConfidence 只能是 low / medium / high
- reason 用一句中文短句说明判断原因，不超过 24 个字
- 仅当 route=smalltalk 时，必须补充 smalltalkPayload 对象
- smalltalkPayload 只能包含：title, summary, greeting, currentState, highlights, nextActions, confidenceLabel
- greeting 为单个字符串，使用专业、克制、分析助手风格的自然中文；先简短回应闲聊，再自然说明你能帮助分析什么
- currentState 为 2 到 4 句，顺势概括当前站内现状，为后续现状卡片和图表做铺垫
- highlights 为 2 到 4 条字符串数组，概括当前值得先看的点
- nextActions 为 2 到 3 条字符串数组，给出用户接下来可追问的方向
- confidenceLabel 在 smalltalkPayload 中固定写“闲聊模式”
- 禁止使用客服腔、过度热情措辞、语气词、波浪号、表情或拟人化欢迎语，例如“很高兴见到您”“当然可以哦”“～”
""".strip()
        payload = {
            "question": question,
            "audience": audience,
            "context": context,
            "recentHistory": [
                {
                    "role": item.get("role", "user"),
                    "content": item.get("content") or item.get("summary") or "",
                }
                for item in history[-4:]
            ],
        }
        route_started_at = time.perf_counter()
        request_options = get_chat_completion_options(enable_thinking=False)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=CHAT_ROUTE_MAX_TOKENS,
                timeout=CHAT_ROUTE_TIMEOUT_SECONDS,
                **request_options,
            )
            raw = (response.choices[0].message.content or "").strip()
            routed = _safe_json_loads(raw)
            if not isinstance(routed, dict):
                raise RuntimeError("route payload invalid")
            route = str(routed.get("route") or "").strip().lower()
            confidence = str(routed.get("smalltalkConfidence") or "low").strip().lower()
            if route not in QUESTION_ROUTES:
                raise RuntimeError(f"unsupported route: {route}")
            if route == SMALLTALK_ROUTE:
                if confidence != SMALLTALK_CONFIDENCE_HIGH or self._contains_domain_signal(question):
                    LOGGER.info(
                        "chat_route_downgraded route=%s confidence=%s question=%s",
                        route,
                        confidence,
                        question,
                    )
                    self._log_chat_stage(
                        "chat_route_downgraded",
                        question_type=route,
                        elapsed_ms=self._elapsed_ms(route_started_at),
                        history_chars=self._history_chars(history),
                        route_reason=str(routed.get("reason") or "").strip(),
                        thinking_enabled="false",
                        thinking_budget="-",
                    )
                    return self._fallback_route(question)
            self._log_chat_stage(
                "chat_route_completed",
                question_type=route,
                elapsed_ms=self._elapsed_ms(route_started_at),
                history_chars=self._history_chars(history),
                route_reason=str(routed.get("reason") or "").strip(),
                thinking_enabled="false",
                thinking_budget="-",
            )
            return {
                "route": route,
                "needsDatabase": bool(routed.get("needsDatabase", route != SMALLTALK_ROUTE)),
                "needsKnowledge": bool(routed.get("needsKnowledge", route != SMALLTALK_ROUTE)),
                "needsCharts": bool(routed.get("needsCharts", route != SMALLTALK_ROUTE)),
                "smalltalkConfidence": confidence if confidence in {"low", "medium", "high"} else "low",
                "reason": str(routed.get("reason") or "").strip(),
                "smalltalkPayload": routed.get("smalltalkPayload") if isinstance(routed.get("smalltalkPayload"), dict) else None,
            }
        except Exception as error:
            LOGGER.warning("chat_route_fallback error=%s", error)
            self._log_chat_stage(
                "chat_route_fallback",
                question_type="fallback",
                elapsed_ms=self._elapsed_ms(route_started_at),
                history_chars=self._history_chars(history),
                route_reason=str(error),
                thinking_enabled="false",
                thinking_budget="-",
            )
            return self._fallback_route(question)

    def _classify_question(self, question: str) -> str:
        lowered = question.lower()
        if any(keyword in question for keyword in ("新闻", "资讯", "事件", "地缘", "情绪")):
            return "news"
        if any(keyword in question for keyword in ("因子", "宏观", "美元", "vix", "库存", "opec")):
            return "factor"
        if any(keyword in question for keyword in ("套保", "对冲", "采购", "授信", "敞口", "策略", "建议", "企业", "银行")):
            return "strategy"
        if any(keyword in lowered for keyword in ("hedge", "bank", "credit", "factor", "news")):
            return "strategy"
        return "prediction"

    def _build_smalltalk_context_chart(self, bootstrap: dict[str, Any]) -> dict[str, Any] | None:
        items = []
        for item in (bootstrap.get("dataContexts") or [])[:4]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "label": str(item.get("label") or "").strip(),
                    "detail": str(item.get("detail") or "").strip(),
                    "status": str(item.get("status") or "ready").strip() or "ready",
                    "timestamp": str(item.get("timestamp") or "").strip(),
                }
            )
        if not items:
            return None
        return {
            "id": "smalltalk-contexts",
            "kind": "context-grid",
            "title": "当前现状概览",
            "subtitle": "如果你继续问油价、新闻、因子或策略问题，我会基于这些真实数据继续展开",
            "priority": 1,
            "data": {"items": items},
            "footnote": "以下为当前可用的实时/已发布站内上下文摘要",
        }

    def _build_smalltalk_charts(self, raw_bundle: dict[str, Any], bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
        charts = build_qa_charts(SMALLTALK_ROUTE, raw_bundle)
        context_chart = self._build_smalltalk_context_chart(bootstrap)
        if context_chart:
            charts = [context_chart, *charts]
        charts_by_id: dict[str, dict[str, Any]] = {}
        for chart in charts:
            if chart and chart.get("id"):
                charts_by_id[chart["id"]] = chart
        return sorted(charts_by_id.values(), key=lambda item: int(item.get("priority", 999)))[:5]

    def _build_smalltalk_answer(
        self,
        *,
        audience: str,
        raw_bundle: dict[str, Any],
        charts: list[dict[str, Any]],
        route: dict[str, Any],
    ) -> dict[str, Any]:
        response = route.get("smalltalkPayload") if isinstance(route.get("smalltalkPayload"), dict) else None
        if not response:
            response = {
                "title": "你好，我在",
                "summary": "我可以先回应你的问题，再基于当前数据给出现状概览。",
                "greeting": "你好，我在。你可以继续问我油价走势、新闻情绪、关键因子，或企业与银行视角下的策略判断。",
                "currentState": "我已经把当前站内可用的预测、新闻、市场和 AI 摘要都整理出来了，下面这些卡片就是当前现状概览。你如果愿意，我可以继续把其中任何一块展开讲清楚。",
                "highlights": ["先看预测和风险信号的方向", "再结合新闻热度与市场快照判断当前环境", "需要的话我可以切到企业侧或银行侧继续展开"],
                "nextActions": ["帮我看今天油价的关键驱动", "总结一下最近新闻情绪对油价的影响", "从企业或银行视角给我一版简短建议"],
                "confidenceLabel": "闲聊模式",
            }
            LOGGER.info("smalltalk_payload_fallback reason=%s", route.get("reason") or "missing_payload")
        greeting = _normalize_text_value(response.get("greeting"))
        current_state = _normalize_text_value(response.get("currentState"))
        if not greeting:
            greeting = "你好，我在。你可以继续问我油价走势、新闻情绪、关键因子，或企业与银行视角下的策略判断。"
        if not current_state:
            current_state = "我已经把当前站内可用的预测、新闻、市场和 AI 摘要都整理出来了，下面这些卡片就是当前现状概览。"
        highlights = [
            item for item in (response.get("highlights") or [])
            if isinstance(item, str) and item.strip()
        ][:4]
        next_actions = [
            item for item in (response.get("nextActions") or [])
            if isinstance(item, str) and item.strip()
        ][:3]
        sections = [
            {"title": "先和你打个招呼", "type": "text", "content": greeting},
            {"title": "当前现状", "type": "text", "content": current_state},
        ]
        if highlights:
            sections.append({"title": "现在值得先看的点", "type": "list", "items": highlights})
        if next_actions:
            sections.append({"title": "你可以继续这样问我", "type": "list", "items": next_actions})
        return {
            "questionType": SMALLTALK_ROUTE,
            "audience": audience,
            "title": _normalize_text_value(response.get("title")) or "聊聊也可以",
            "summary": _first_sentence(_normalize_text_value(response.get("summary")) or current_state, "你好，我在。"),
            "sections": sections,
            "usedDomains": self._used_domains(raw_bundle),
            "confidenceLabel": _normalize_text_value(response.get("confidenceLabel")) or "闲聊模式",
            "charts": charts,
            "chart": charts[0] if charts else None,
        }

    def _build_data_bundle(self, question_type: str) -> dict[str, Any]:
        bundle = {
            "prediction": self._try_query(self.query_service.get_prediction_summary),
            "ai_analysis": self._try_query(self.query_service.get_prediction_ai_analysis),
            "ticker": self._try_query(self.query_service.get_market_ticker),
            "news_overview": self._try_query(lambda: self.query_service.get_news_overview(limit=60)),
            "factors": self._try_query(lambda: self.query_service.get_factor_table(limit=10)),
            "prediction_chart": self._try_query(lambda: self.query_service.get_prediction_chart("1M")),
        }
        if question_type in {"news", "strategy"}:
            bundle["news_overview"] = self._try_query(lambda: self.query_service.get_news_overview(limit=60))
            bundle["news_list"] = self._try_query(lambda: self.query_service.get_news_list(limit=10))
        return bundle

    def _build_model_context_bundle(self, question_type: str, raw_bundle: dict[str, Any]) -> dict[str, Any]:
        bundle = {
            "prediction": self._summarize_prediction(raw_bundle.get("prediction")),
            "ai_analysis": self._summarize_ai_analysis(raw_bundle.get("ai_analysis")),
            "ticker": self._summarize_ticker(raw_bundle.get("ticker")),
            "news_overview": self._summarize_news_overview(raw_bundle.get("news_overview")),
            "factors": self._summarize_factor_table(raw_bundle.get("factors"), raw_bundle.get("prediction")),
            "prediction_chart": self._summarize_prediction_chart(raw_bundle.get("prediction_chart")),
        }
        if question_type in {"news", "strategy"}:
            bundle["news_list"] = self._summarize_news_list(raw_bundle.get("news_list"))
        else:
            bundle["news_list"] = []
        self._log_context_size(question_type, raw_bundle, bundle)
        return bundle

    def _summarize_prediction(self, prediction: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(prediction, dict):
            return None
        return dict(prediction)

    def _summarize_ai_analysis(self, analysis: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(analysis, dict):
            return None
        views = analysis.get("views") if isinstance(analysis.get("views"), dict) else {}
        corporate_view = views.get("corporate") if isinstance(views.get("corporate"), dict) else {}
        bank_view = views.get("bank") if isinstance(views.get("bank"), dict) else {}
        return {
            "predictionSummary": analysis.get("predictionSummary"),
            "previewSummary": analysis.get("previewSummary"),
            "corporateSummary": _first_sentence(corporate_view.get("body", ""), ""),
            "bankSummary": _first_sentence(bank_view.get("body", ""), ""),
            "stale": analysis.get("stale"),
            "updatedAt": analysis.get("updatedAt"),
        }

    def _summarize_ticker(self, ticker: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(ticker, dict):
            return None
        items = []
        for item in (ticker.get("items") or []):
            if not isinstance(item, dict):
                continue
            compact_item = dict(item)
            compact_item.pop("sparkline", None)
            items.append(compact_item)
        return {"items": items, "updatedAt": ticker.get("updatedAt")}

    def _summarize_news_overview(self, overview: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(overview, dict):
            return None
        compact_overview = dict(overview)
        compact_overview.pop("sourceStatus", None)
        compact_overview.pop("meta", None)
        return compact_overview

    def _summarize_factor_table(
        self,
        factors: dict[str, Any] | None,
        prediction: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(factors, dict):
            return None
        top_movers = []
        if isinstance(prediction, dict):
            for item in (prediction.get("topMovers") or [])[:8]:
                if not isinstance(item, dict):
                    continue
                top_movers.append(
                    {
                        "factor": item.get("factor"),
                        "value": item.get("value"),
                        "zScore": item.get("zScore"),
                        "direction": item.get("direction"),
                        "description": item.get("description"),
                    }
                )
        return {
            "topMovers": top_movers,
            "updatedAt": factors.get("updatedAt"),
        }

    def _summarize_prediction_chart(self, chart: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(chart, dict):
            return None
        compact_chart = dict(chart)
        compact_chart.pop("history", None)
        return compact_chart

    def _summarize_news_list(self, news_list: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(news_list, dict):
            return {"titles": [], "updatedAt": None}
        titles = []
        for item in (news_list.get("items") or [])[:12]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            published_at = str(item.get("publishedAt") or item.get("publishedDate") or "").strip()
            if published_at:
                titles.append(f"{published_at} | {title}")
            else:
                titles.append(title)
        return {"titles": titles, "updatedAt": news_list.get("updatedAt")}

    def _limit_items(
        self,
        items: Any,
        limit: int,
        allowed_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        rows = []
        for item in (items or [])[:limit]:
            if not isinstance(item, dict):
                continue
            rows.append({key: item.get(key) for key in allowed_keys if key in item})
        return rows

    def _log_context_size(self, question_type: str, raw_bundle: dict[str, Any], compact_bundle: dict[str, Any]) -> None:
        raw_chars = len(json.dumps(raw_bundle, ensure_ascii=False))
        compact_chars = len(json.dumps(compact_bundle, ensure_ascii=False))
        reduction = 0 if raw_chars <= 0 else round((1 - (compact_chars / raw_chars)) * 100, 1)
        LOGGER.info(
            "chat_context_compacted questionType=%s rawChars=%s compactChars=%s reductionPct=%s includeNewsList=%s",
            question_type,
            raw_chars,
            compact_chars,
            reduction,
            bool(compact_bundle.get("news_list")),
        )

    def _retrieve_knowledge(self, question: str, question_type: str) -> list[dict[str, str]]:
        pipeline = self._get_pipeline()
        pipeline.kb.ensure_loaded()
        category = "crude_oil_market" if question_type in {"news", "prediction"} else "financial_qa"
        chunks = pipeline.kb.retrieve(question, top_k=3, category_filter=category)
        if not chunks:
            chunks = pipeline.kb.retrieve(question, top_k=3)
        return chunks

    def _build_charts(self, question_type: str, bundle: dict[str, Any]) -> list[dict[str, Any]]:
        return build_qa_charts(question_type, bundle)

    def _build_prompt(
        self,
        *,
        question: str,
        audience: str,
        question_type: str,
        bundle: dict[str, Any],
        knowledge_chunks: list[dict[str, str]],
        history: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[str, str]:
        system_prompt = """
你是花旗企业银行油价风险分析副驾驶，服务于企业侧与银行侧用户。
你只能基于给定的站内数据、检索知识和用户问题作答，不能臆造未提供的数据。
输出必须是 JSON，且只能包含以下字段：
title, summary, conclusion, drivers, impact, actions, risks, evidenceSummary, confidenceLabel
字段要求：
- title, summary, conclusion, impact, evidenceSummary, confidenceLabel 为字符串
- drivers, actions, risks 为字符串数组
- summary 必须是 1 句话，语气谨慎、概括全局，不要展开分点，不超过 45 个中文字符
- conclusion 要先给结论，再点出主要依据，但保持简短
- actions 要写成可执行动作，不要空话
- 若信息不足，直接说明“当前站内数据不足以支持该判断”
""".strip()

        history_block = [
            {
                "role": item.get("role", "user"),
                "content": item.get("content") or item.get("summary") or "",
            }
            for item in history[-4:]
        ]

        payload = {
            "audience": "银行侧" if audience == "bank" else "企业侧",
            "questionType": question_type,
            "question": question,
            "pageContext": context,
            "recentHistory": history_block,
            "siteData": bundle,
            "knowledge": knowledge_chunks,
        }
        return system_prompt, json.dumps(payload, ensure_ascii=False)

    def _generate_response(
        self,
        *,
        question: str,
        audience: str,
        question_type: str,
        bundle: dict[str, Any],
        knowledge_chunks: list[dict[str, str]],
        history: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        client, model = self._get_chat_client()
        system_prompt, user_prompt = self._build_prompt(
            question=question,
            audience=audience,
            question_type=question_type,
            bundle=bundle,
            knowledge_chunks=knowledge_chunks,
            history=history,
            context=context,
        )
        request_options = get_chat_completion_options()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1600,
            **request_options,
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise RuntimeError("智能问答返回内容为空")
        payload = _safe_json_loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError("智能问答返回格式无效")
        if isinstance(payload.get("summary"), str):
            payload["summary"] = _first_sentence(payload["summary"], "当前站内数据不足以支持该判断")
        return payload

    def _build_sections(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        sections = []
        mapping = [
            ("结论", payload.get("conclusion") or payload.get("summary") or "暂无结论"),
            ("关键驱动", payload.get("drivers") or []),
            ("影响判断", payload.get("impact") or "暂无影响判断"),
            ("建议动作", payload.get("actions") or []),
            ("风险提示", payload.get("risks") or []),
            ("依据说明", payload.get("evidenceSummary") or "暂无依据说明"),
        ]
        for title, value in mapping:
            if isinstance(value, list):
                content = [item for item in value if isinstance(item, str) and item.strip()]
                if not content:
                    continue
                sections.append({"title": title, "type": "list", "items": content})
                continue
            text = str(value).strip()
            if text:
                sections.append({"title": title, "type": "text", "content": text})
        return sections

    def _build_evidence(
        self,
        bundle: dict[str, Any],
        knowledge_chunks: list[dict[str, str]],
        charts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        prediction = bundle.get("prediction")
        if prediction:
            rows.append(
                {
                    "kind": "prediction",
                    "title": "10 交易日价格区间摘要",
                    "summary": prediction.get("insight") or prediction.get("next10DayForecast") or "已加载预测结果",
                    "timestamp": prediction.get("updatedAt"),
                    "targetTab": "prediction",
                }
            )
        news = bundle.get("news_overview")
        if news:
            summary = news.get("summary", {})
            rows.append(
                {
                    "kind": "news",
                    "title": "新闻概览",
                    "summary": news.get("insightText")
                    or f"{summary.get('articleCount', 0)} 条新闻，主主题 {summary.get('primaryTopic') or '暂无'}",
                    "timestamp": news.get("updatedAt"),
                    "targetTab": "news",
                }
            )
        factors = prediction.get("topMovers", [])[:3] if prediction else []
        if factors:
            rows.append(
                {
                    "kind": "factor",
                    "title": "关键因子",
                    "summary": "、".join(item.get("factor", "未知因子") for item in factors),
                    "timestamp": prediction.get("updatedAt"),
                    "targetTab": "factors",
                }
            )
        ticker = bundle.get("ticker")
        if ticker:
            items = ticker.get("items", [])[:3]
            rows.append(
                {
                    "kind": "market",
                    "title": "市场快照",
                    "summary": " | ".join(f"{item.get('label')}: {item.get('displayValue')}" for item in items),
                    "timestamp": ticker.get("updatedAt"),
                    "targetTab": "dashboard",
                }
            )
        for chart in charts:
            rows.append(
                {
                    "kind": "chart",
                    "title": chart.get("title", "图表摘要"),
                    "summary": chart.get("footnote") or chart.get("subtitle", ""),
                    "timestamp": prediction.get("updatedAt") if prediction else backend_core.iso_now(),
                    "targetTab": "prediction" if chart.get("kind") == "line" else "news",
                }
            )
        for chunk in knowledge_chunks:
            rows.append(
                {
                    "kind": "knowledge",
                    "title": chunk.get("source", "知识库"),
                    "summary": chunk.get("content", "")[:160],
                    "timestamp": "",
                    "targetTab": "settings",
                    "category": chunk.get("category", ""),
                }
            )
        return rows

    def _build_followups(self, question_type: str, audience: str, payload: dict[str, Any]) -> list[str]:
        options = {
            SMALLTALK_ROUTE: [
                "帮我看看今天油价的关键驱动",
                "总结一下最近新闻情绪对油价的影响",
                "从企业或银行视角给我一版简短建议",
            ],
            "prediction": [
                "把这个判断拆解成预测、新闻、因子三部分再解释一遍",
                "这个结论与最近 7 天新闻方向是否一致？",
                "如果改成另一视角，会得出什么不同结论？",
            ],
            "news": [
                "哪些新闻事件对这个结论影响最大？",
                "这些新闻信号和模型预测是否背离？",
                "如果切到另一视角，该如何解读这些新闻？",
            ],
            "factor": [
                "这些因子中哪个对当前判断最关键？",
                "这些因子和新闻情绪是否互相印证？",
                "换成另一视角后，重点该看哪些因子？",
            ],
            "strategy": [
                "请把建议动作拆成未来 24 小时和未来一周两层",
                "把另一视角的建议也补充出来",
                "如果油价继续上行/下行，应该重点监控什么？",
            ],
        }
        followups = list(options.get(question_type, options["prediction"]))
        if audience == "bank":
            followups[1] = "如果从企业经营侧看，这个结论会有什么不同？"
        else:
            followups[1] = "如果从银行授信侧看，这个结论会有什么不同？"
        return followups[:3]

    def _used_domains(self, bundle: dict[str, Any]) -> list[str]:
        labels = []
        if bundle.get("prediction"):
            labels.append("预测")
        if bundle.get("news_overview"):
            labels.append("新闻")
        if bundle.get("factors"):
            labels.append("因子")
        if bundle.get("ticker"):
            labels.append("市场")
        return labels

    def _confidence_from_bundle(self, bundle: dict[str, Any]) -> str:
        domain_count = len(self._used_domains(bundle))
        if domain_count >= 4:
            return "证据较充分"
        if domain_count >= 2:
            return "主要基于多域数据"
        return "当前依据较有限"

    def _title_for(self, question_type: str, audience: str) -> str:
        audience_label = "银行侧" if audience == "bank" else "企业侧"
        titles = {
            SMALLTALK_ROUTE: "助手已就绪",
            "prediction": f"{audience_label}趋势解读",
            "news": f"{audience_label}新闻解读",
            "factor": f"{audience_label}因子归因",
            "strategy": f"{audience_label}策略建议",
        }
        return titles.get(question_type, f"{audience_label}分析结论")
