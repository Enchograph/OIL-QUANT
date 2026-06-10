from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import core_backend as backend_core
from backend.ai_advisory import (
    SYSTEM_PROMPT,
    build_preview_prompt,
    build_prompt,
    get_chat_completion_options,
    load_project_env,
    normalize_openai_base_url,
    normalize_prediction_payload,
)
from backend.chat_service import ChatOrchestrator
from backend.query_service import QueryService
from backend.runtime_store import RuntimeStore


def _runtime_store() -> RuntimeStore:
    store = RuntimeStore(backend_core.DB_PATH, backend_core.iso_now)
    store.init()
    store.bootstrap_views_from_existing_data()
    return store


def _build_chat_orchestrator() -> ChatOrchestrator:
    database = backend_core.create_database()
    queries = QueryService(_runtime_store(), database=database)
    return ChatOrchestrator(queries)


def _make_chat_client() -> tuple[OpenAI, str]:
    load_project_env()
    api_key = backend_core.os.getenv("AI_CHAT_API_KEY", "").strip() or backend_core.os.getenv("AI_OPENAI_API_KEY", "").strip()
    model = backend_core.os.getenv("AI_CHAT_MODEL", "").strip()
    base_url = normalize_openai_base_url(
        backend_core.os.getenv("AI_CHAT_BASE_URL", "").strip()
        or backend_core.os.getenv("AI_OPENAI_BASE_URL", "").strip()
        or None
    )
    if not api_key or not model:
        raise RuntimeError("AI_CHAT_API_KEY / AI_CHAT_MODEL 未配置")
    return OpenAI(api_key=api_key, base_url=base_url), model


def _make_embedding_client() -> tuple[OpenAI, str]:
    load_project_env()
    api_key = backend_core.os.getenv("AI_EMBEDDING_API_KEY", "").strip() or backend_core.os.getenv("AI_CHAT_API_KEY", "").strip()
    model = backend_core.os.getenv("AI_EMBEDDING_MODEL", "").strip()
    base_url = normalize_openai_base_url(
        backend_core.os.getenv("AI_EMBEDDING_BASE_URL", "").strip()
        or backend_core.os.getenv("AI_CHAT_BASE_URL", "").strip()
        or None
    )
    if not api_key or not model:
        raise RuntimeError("AI_EMBEDDING_API_KEY / AI_EMBEDDING_MODEL 未配置")
    return OpenAI(api_key=api_key, base_url=base_url), model


def _measure_chat(client: OpenAI, model: str, *, system_prompt: str, user_prompt: str, timeout_seconds: float | None) -> dict[str, Any]:
    started_at = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=800,
            timeout=timeout_seconds,
            **get_chat_completion_options(),
        )
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        content = (response.choices[0].message.content or "").strip()
        return {
            "ok": True,
            "elapsedMs": elapsed_ms,
            "contentChars": len(content),
        }
    except Exception as error:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {
            "ok": False,
            "elapsedMs": elapsed_ms,
            "errorType": error.__class__.__name__,
            "error": str(error),
        }


def _measure_embedding(client: OpenAI, model: str, *, text: str, timeout_seconds: float | None) -> dict[str, Any]:
    started_at = time.monotonic()
    try:
        response = client.embeddings.create(model=model, input=[text], timeout=timeout_seconds)
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {
            "ok": True,
            "elapsedMs": elapsed_ms,
            "vectorCount": len(response.data),
            "dimensions": len(response.data[0].embedding) if response.data else 0,
        }
    except Exception as error:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {
            "ok": False,
            "elapsedMs": elapsed_ms,
            "errorType": error.__class__.__name__,
            "error": str(error),
        }


def _build_real_prompt(orchestrator: ChatOrchestrator, *, question: str, audience: str) -> dict[str, Any]:
    question_type = orchestrator._classify_question(question)
    raw_bundle = orchestrator._build_data_bundle(question_type)
    compact_bundle = orchestrator._build_model_context_bundle(question_type, raw_bundle)
    knowledge_chunks = orchestrator._retrieve_knowledge(question, question_type)
    system_prompt, user_prompt = orchestrator._build_prompt(
        question=question,
        audience=audience,
        question_type=question_type,
        bundle=compact_bundle,
        knowledge_chunks=knowledge_chunks,
        history=[],
        context={},
    )
    return {
        "questionType": question_type,
        "rawChars": len(json.dumps(raw_bundle, ensure_ascii=False)),
        "compactChars": len(json.dumps(compact_bundle, ensure_ascii=False)),
        "knowledgeCount": len(knowledge_chunks),
        "knowledgeChars": len(json.dumps(knowledge_chunks, ensure_ascii=False)),
        "systemChars": len(system_prompt),
        "userChars": len(user_prompt),
        "systemPrompt": system_prompt,
        "userPrompt": user_prompt,
    }


def _build_analysis_prompts() -> dict[str, Any]:
    database = backend_core.create_database()
    model_context = database.get_model_output("prediction_ai_context")
    if not model_context:
        raise RuntimeError("缺少 prediction_ai_context，无法构造 AI 分析 prompt")
    prediction = normalize_prediction_payload(model_context["payload"]["prediction"], model_context["payload"])
    chat = _build_chat_orchestrator()
    pipeline = chat._get_pipeline()
    query = pipeline._build_query(prediction)
    pipeline.kb.ensure_loaded()
    corporate_chunks = pipeline.kb.retrieve(query, top_k=pipeline.top_k, category_filter="financial_qa")
    bank_chunks = pipeline.kb.retrieve(query, top_k=pipeline.top_k, category_filter="crude_oil_market")
    prediction_summary = (
        f"WTI ${prediction.wti_price:.2f} | "
        f"Brent ${prediction.brent_price:.2f} | "
        f"{prediction.horizon_days}日预测变动 {prediction.forecast_change_pct:+.2f}% | "
        f"风险等级 {prediction.risk_level}"
    )
    corporate_prompt = build_prompt(prediction, corporate_chunks, "corporate")
    bank_prompt = build_prompt(prediction, bank_chunks, "bank")
    preview_prompt = build_preview_prompt(prediction_summary, "企业侧分析正文占位")
    return {
        "query": query,
        "corporatePrompt": corporate_prompt,
        "bankPrompt": bank_prompt,
        "previewPrompt": preview_prompt,
        "corporateKnowledgeCount": len(corporate_chunks),
        "bankKnowledgeCount": len(bank_chunks),
        "corporateUserChars": len(corporate_prompt),
        "bankUserChars": len(bank_prompt),
        "previewUserChars": len(preview_prompt),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="请结合当前预测、新闻、因子与市场快照，解释今天油价判断的关键驱动是什么。")
    parser.add_argument("--audience", default="enterprise")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    orchestrator = _build_chat_orchestrator()
    chat_client, chat_model = _make_chat_client()
    embedding_client, embedding_model = _make_embedding_client()

    real_prompt = _build_real_prompt(orchestrator, question=args.question, audience=args.audience)
    analysis_prompts = _build_analysis_prompts()
    minimal_system = "你是金融分析助手。"
    minimal_user = "请用一句话回答：WTI 原油风险怎么看？"
    fixed_user = "请严格输出 JSON，说明油价风险判断。" + ("市场分析。" * 300)

    measures: dict[str, Any] = {
        "embeddingMinimal": [],
        "chatMinimal": [],
        "chatFixedLong": [],
        "chatRealPrompt": [],
        "analysisCorporatePrompt": [],
        "analysisBankPrompt": [],
        "analysisPreviewPrompt": [],
    }
    for _ in range(max(1, args.repeat)):
        measures["embeddingMinimal"].append(
            _measure_embedding(
                embedding_client,
                embedding_model,
                text="WTI 原油风险判断",
                timeout_seconds=args.timeout,
            )
        )
        measures["chatMinimal"].append(
            _measure_chat(
                chat_client,
                chat_model,
                system_prompt=minimal_system,
                user_prompt=minimal_user,
                timeout_seconds=args.timeout,
            )
        )
        measures["chatFixedLong"].append(
            _measure_chat(
                chat_client,
                chat_model,
                system_prompt=minimal_system,
                user_prompt=fixed_user,
                timeout_seconds=args.timeout,
            )
        )
        measures["chatRealPrompt"].append(
            _measure_chat(
                chat_client,
                chat_model,
                system_prompt=real_prompt["systemPrompt"],
                user_prompt=real_prompt["userPrompt"],
                timeout_seconds=args.timeout,
            )
        )
        measures["analysisCorporatePrompt"].append(
            _measure_chat(
                chat_client,
                chat_model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=analysis_prompts["corporatePrompt"],
                timeout_seconds=args.timeout,
            )
        )
        measures["analysisBankPrompt"].append(
            _measure_chat(
                chat_client,
                chat_model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=analysis_prompts["bankPrompt"],
                timeout_seconds=args.timeout,
            )
        )
        measures["analysisPreviewPrompt"].append(
            _measure_chat(
                chat_client,
                chat_model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=analysis_prompts["previewPrompt"],
                timeout_seconds=args.timeout,
            )
        )

    result = {
        "question": args.question,
        "audience": args.audience,
        "chatModel": chat_model,
        "embeddingModel": embedding_model,
        "repeat": max(1, args.repeat),
        "promptMetrics": {
            "realQuestionType": real_prompt["questionType"],
            "rawChars": real_prompt["rawChars"],
            "compactChars": real_prompt["compactChars"],
            "knowledgeCount": real_prompt["knowledgeCount"],
            "knowledgeChars": real_prompt["knowledgeChars"],
            "systemChars": real_prompt["systemChars"],
            "userChars": real_prompt["userChars"],
            "analysisCorporateKnowledgeCount": analysis_prompts["corporateKnowledgeCount"],
            "analysisBankKnowledgeCount": analysis_prompts["bankKnowledgeCount"],
            "analysisCorporateUserChars": analysis_prompts["corporateUserChars"],
            "analysisBankUserChars": analysis_prompts["bankUserChars"],
            "analysisPreviewUserChars": analysis_prompts["previewUserChars"],
        },
        "measures": measures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
