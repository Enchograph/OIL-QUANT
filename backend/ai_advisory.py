from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from openai import OpenAI


SYSTEM_PROMPT = """你是一位专业的石油市场金融分析师，服务对象为大型能源企业和商业银行。
你的任务是基于最新的石油价格预测数据和权威金融知识，生成结构清晰、可操作性强的建议报告。
要求：
- 语言专业、简洁，避免模糊表述
- 建议必须与预测数据和检索知识直接挂钩
- 区分企业客户（套保、采购）和银行客户（授信、风险敞口）的不同需求
- 所有风险提示需量化到具体数值
- 不得把多日预测数据表述为单日行情、日内波动或 1 日 VaR
"""

REFERENCE_FALLBACK_EXCERPT = "该来源片段暂不可读"
LOGGER = logging.getLogger("backend.ai_advisory")


def load_project_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_openai_base_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().rstrip("/")
    if normalized.endswith("/embeddings"):
        normalized = normalized[: -len("/embeddings")]
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return normalized


def _parse_optional_bool_env(key: str) -> bool | None:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{key} 配置无效，应为 true/false 或 1/0")


def _parse_optional_int_env(key: str) -> int | None:
    raw = os.getenv(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise RuntimeError(f"{key} 配置无效，应为整数") from error


def get_chat_completion_options(
    *,
    enable_thinking: bool | None = None,
    thinking_budget: int | None = None,
) -> dict[str, Any]:
    if enable_thinking is None:
        enable_thinking = _parse_optional_bool_env("AI_CHAT_ENABLE_THINKING")
    if thinking_budget is None:
        thinking_budget = _parse_optional_int_env("AI_CHAT_THINKING_BUDGET")
    extra_body: dict[str, Any] = {}
    if enable_thinking is not None:
        extra_body["enable_thinking"] = enable_thinking
    if enable_thinking is not False and thinking_budget is not None:
        extra_body["thinking_budget"] = thinking_budget
    if not extra_body:
        return {}
    return {"extra_body": extra_body}


def _clean_reference_line(value: str) -> str:
    text = str(value or "")
    text = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\b(question|answer|context|evidence|instruction|input|output)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" '\"`[]{}()<>")
    text = re.sub(r"(?:['\"`]+[\]\}]?|[\]\}]+['\"`]?)$", "", text)
    return text.strip()


def _is_meaningful_reference_line(value: str, source: str, category: str) -> bool:
    text = _clean_reference_line(value)
    if len(text) < 12:
        return False
    if re.fullmatch(r"[\W\d_]+", text):
        return False
    lowered = text.lower()
    if lowered == category.lower():
        return False
    if source and lowered == source.lower():
        return False
    source_tokens = [token for token in re.split(r"[^a-z0-9]+", source.lower()) if len(token) >= 4]
    if source_tokens and len(text) <= 48 and all(token in lowered for token in source_tokens[:2]):
        return False
    return True


def _truncate_reference_excerpt(value: str, max_length: int = 160) -> str:
    if len(value) <= max_length:
        return value
    boundary = max(
        value.rfind("。", 0, max_length + 1),
        value.rfind("！", 0, max_length + 1),
        value.rfind("？", 0, max_length + 1),
        value.rfind(".", 0, max_length + 1),
        value.rfind(";", 0, max_length + 1),
        value.rfind("；", 0, max_length + 1),
    )
    if boundary >= 60:
        return value[: boundary + 1].strip()
    word_boundary = value.rfind(" ", 0, max_length + 1)
    if word_boundary >= 60:
        return value[:word_boundary].strip() + "…"
    return value[:max_length].strip() + "…"


def build_reference_excerpt(content: str, source: str, category: str, max_length: int = 160) -> str:
    raw_text = str(content or "").strip()
    if not raw_text:
        return REFERENCE_FALLBACK_EXCERPT

    segments = re.split(r"(?:\\n|\n)+", raw_text)
    candidates = [_clean_reference_line(segment) for segment in segments if _is_meaningful_reference_line(segment, source, category)]
    fallback = _clean_reference_line(raw_text)
    preferred = next((candidate for candidate in candidates if len(candidate) >= 48), "")
    if not preferred and candidates:
        preferred = max(candidates, key=len)
    if not preferred:
        preferred = fallback
    preferred = re.sub(r"\s*[,;:：-]+\s*$", "", preferred).strip()
    if not preferred:
        return REFERENCE_FALLBACK_EXCERPT
    return _truncate_reference_excerpt(preferred, max_length=max_length) or REFERENCE_FALLBACK_EXCERPT


@dataclass
class OilPrediction:
    date: str
    horizon_days: int
    latest_close: float
    wti_price: float
    brent_price: float
    forecast_change_pct: float
    forecast_band_pct: float
    downside_risk_pct: float
    trend: str
    risk_level: str
    key_drivers: list[str]


@dataclass
class AdvisoryReport:
    date: str
    prediction_summary: str
    preview_summary: str
    corporate_advice: str
    bank_advice: str
    retrieved_references: list[dict[str, str]]


def normalize_prediction_payload(payload: dict[str, Any], context: dict[str, Any] | None = None) -> OilPrediction:
    data = dict(payload or {})
    model_context = context or {}
    price_forecast = dict(model_context.get("priceForecast") or {})

    horizon_days = int(
        data.get("horizon_days")
        or price_forecast.get("horizonDays")
        or 0
    )
    latest_close = float(
        data.get("latest_close")
        or price_forecast.get("latestClose")
        or 0.0
    )

    forecast_change_pct = data.get("forecast_change_pct")
    if forecast_change_pct is None:
        legacy_change = data.get("price_change_pct")
        forecast_change_pct = float(legacy_change) if legacy_change is not None else 0.0

    forecast_band_pct = data.get("forecast_band_pct")
    if forecast_band_pct is None:
        legacy_band = data.get("volatility_index")
        forecast_band_pct = float(legacy_band) * 100 if legacy_band is not None else 0.0

    downside_risk_pct = data.get("downside_risk_pct")
    if downside_risk_pct is None:
        legacy_risk = data.get("var_95")
        downside_risk_pct = (float(legacy_risk) / latest_close * 100) if legacy_risk is not None and latest_close else 0.0

    return OilPrediction(
        date=str(data.get("date") or price_forecast.get("asOf") or ""),
        horizon_days=horizon_days,
        latest_close=latest_close,
        wti_price=float(data.get("wti_price") or price_forecast.get("expectedPrice") or 0.0),
        brent_price=float(data.get("brent_price") or 0.0),
        forecast_change_pct=float(forecast_change_pct),
        forecast_band_pct=float(forecast_band_pct),
        downside_risk_pct=float(downside_risk_pct),
        trend=str(data.get("trend") or "震荡"),
        risk_level=str(data.get("risk_level") or price_forecast.get("signal", {}).get("riskLevel") or "中等风险"),
        key_drivers=[str(item) for item in (data.get("key_drivers") or [])],
    )


class OpenAICompatibleEmbeddingFunction:
    def __init__(
        self,
        client: OpenAI,
        model: str,
        *,
        base_url: str | None = None,
        debug_hook: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.client = client
        self.model = model
        self.base_url = base_url or ""
        self.debug_hook = debug_hook
        self.batch_size = max(1, int(os.getenv("AI_EMBEDDING_BATCH_SIZE", "32")))

    def _debug(self, stage: str, **fields: Any) -> None:
        message = stage if not fields else f"{stage} | " + " ".join(f"{key}={value}" for key, value in fields.items())
        LOGGER.info(message)
        if self.debug_hook is not None:
            self.debug_hook(stage, fields)

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(input), self.batch_size):
            batch = input[start : start + self.batch_size]
            started_at = time.monotonic()
            self._debug(
                "embedding_request_start",
                model=self.model,
                baseUrl=self.base_url or "default",
                batchSize=len(batch),
                firstChars=len(batch[0]) if batch else 0,
            )
            response = self.client.embeddings.create(model=self.model, input=batch)
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            self._debug(
                "embedding_request_done",
                model=self.model,
                vectorCount=len(response.data),
                elapsedMs=elapsed_ms,
            )
            vectors.extend(item.embedding for item in response.data)
        return vectors

    def name(self) -> str:
        return f"openai-compatible::{self.model}"

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_query(self, input: str | list[str]) -> list[float] | list[list[float]]:
        if isinstance(input, list):
            if not input:
                raise ValueError("embed_query 输入不能为空")
            return self(input)
        return self([input])[0]


class OpenAICompatibleAdvisor:
    def __init__(
        self,
        client: OpenAI,
        model: str,
        *,
        base_url: str | None = None,
        debug_hook: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.client = client
        self.model = model
        self.base_url = base_url or ""
        self.debug_hook = debug_hook

    def _debug(self, stage: str, **fields: Any) -> None:
        message = stage if not fields else f"{stage} | " + " ".join(f"{key}={value}" for key, value in fields.items())
        LOGGER.info(message)
        if self.debug_hook is not None:
            self.debug_hook(stage, fields)

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
        request_options = get_chat_completion_options()
        started_at = time.monotonic()
        self._debug(
            "chat_request_start",
            model=self.model,
            baseUrl=self.base_url or "default",
            systemChars=len(system_prompt),
            userChars=len(user_prompt),
            temperature=temperature,
            maxTokens=2000,
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=2000,
            **request_options,
        )
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        content = (response.choices[0].message.content or "").strip()
        self._debug(
            "chat_request_done",
            model=self.model,
            elapsedMs=elapsed_ms,
            contentChars=len(content),
        )
        return content


def build_prompt(prediction: OilPrediction, chunks: list[dict[str, str]], target: str) -> str:
    pred_block = f"""
【今日石油价格预测 · {prediction.date}】
- 预测窗口：未来 {prediction.horizon_days} 个交易日
- 最新收盘价：${prediction.latest_close:.2f}/桶
- WTI 预测价格：${prediction.wti_price:.2f}/桶
- Brent 预测价格：${prediction.brent_price:.2f}/桶
- 相对最新收盘价的预测变动：{prediction.forecast_change_pct:+.2f}%
- 预测区间宽度占最新收盘价比例：{prediction.forecast_band_pct:.2f}%
- Q10 下沿对应的潜在下行空间：{prediction.downside_risk_pct:.2f}%
- 趋势判断：{prediction.trend}
- 风险等级：{prediction.risk_level}
- 主要驱动因素：{'、'.join(prediction.key_drivers)}
"""
    knowledge_block = "\n【相关金融知识参考】\n"
    for index, chunk in enumerate(chunks, 1):
        knowledge_block += f"{index}. [{chunk['source']}] {chunk['content'][:300]}\n\n"

    if target == "corporate":
        task = """请为大型能源企业生成今日套保与采购建议，包括：
1. 价格走势解读（50字以内）
2. 套期保值建议（是否建仓/平仓、建议比例、工具：期货/期权/互换）
3. 现货采购时机建议
4. 风险预警（结合预测区间宽度和下行空间）
5. 一句话执行摘要"""
    else:
        task = """请为商业银行生成今日石油相关授信与风险管理建议，包括：
1. 市场风险概述（50字以内）
2. 石油企业授信风险评估（结合预测变动和下行空间）
3. 抵押品折扣率建议
4. 敞口限额调整建议
5. 一句话风控摘要"""

    data_contract = """
硬性口径约束：
- “预测窗口”内的数据是多日预测，不得表述为“单日涨跌”“日内暴跌”“未来一天内损失”。
- “相对最新收盘价的预测变动”是预测窗口累计变动，不是较前一交易日变化。
- “预测区间宽度占比”是预测价格区间宽度相对最新收盘价的比例，不是历史实现波动率。
- “Q10 下沿对应的潜在下行空间”是预测区间下沿相对最新收盘价的距离，不是统计学 VaR。
- 如果引用数值，必须明确其对应口径；不能自行改写成未提供的时间尺度或风险指标名称。
"""

    return pred_block + knowledge_block + data_contract + task


def build_preview_prompt(prediction_summary: str, corporate_advice: str) -> str:
    return f"""你将收到一份石油市场企业侧分析正文。请输出一段连续的中文概要总结，供首页概览卡片直接展示。

硬性要求：
- 只输出一段连续文本
- 不要标题、不要 markdown、不要序号、不要分点、不要换行
- 不要出现“核心观点：”“价格走势解读：”“一句话执行摘要：”这类标签
- 控制在 60 到 110 个中文字符之间
- 内容要概括主要结论、风险判断和行动建议

预测摘要：{prediction_summary}

企业侧分析正文：
{corporate_advice}
"""


def _require_module(name: str):
    try:
        return __import__(name)
    except ModuleNotFoundError as error:
        raise RuntimeError(f"缺少依赖 `{name}`，请先安装后再运行 AI 分析链路") from error


class OilFinanceKnowledgeBase:
    def __init__(
        self,
        persist_directory: Path,
        cache_directory: Path,
        embedding_function: OpenAICompatibleEmbeddingFunction,
        collection_name: str = "oil_finance_knowledge",
    ):
        chromadb = _require_module("chromadb")
        self._datasets = _require_module("datasets")
        splitters = _require_module("langchain_text_splitters")
        self._splitter = splitters.RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=60)
        self._persist_directory = persist_directory
        self._cache_directory = cache_directory
        self._embedding_function = embedding_function
        self._ready_marker = self._persist_directory / "ready.json"
        self._persist_directory.mkdir(parents=True, exist_ok=True)
        self._cache_directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_directory))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    def ensure_loaded(self, force_rebuild: bool = False) -> dict[str, int]:
        if force_rebuild and self._collection.count():
            self._client.delete_collection(self._collection.name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection.name,
                embedding_function=self._embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
            if self._ready_marker.exists():
                self._ready_marker.unlink()
        if self._collection.count() and self._ready_marker.exists():
            return {"chunks": self._collection.count()}
        if self._collection.count() and not self._ready_marker.exists():
            self._client.delete_collection(self._collection.name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection.name,
                embedding_function=self._embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
        documents = list(self._build_documents())
        if not documents:
            raise RuntimeError("知识库构建失败：未提取到任何可用文本")
        self._add_documents(documents)
        self._ready_marker.write_text(json.dumps({"chunks": self._collection.count()}, ensure_ascii=False), encoding="utf-8")
        return {"chunks": self._collection.count()}

    def retrieve(self, query: str, top_k: int = 5, category_filter: str | None = None) -> list[dict[str, str]]:
        where = {"category": category_filter} if category_filter else None
        result = self._collection.query(query_texts=[query], n_results=top_k, where=where)
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        rows: list[dict[str, str]] = []
        for content, metadata in zip(documents, metadatas):
            rows.append(
                {
                    "content": content,
                    "source": str(metadata.get("source", "unknown")),
                    "category": str(metadata.get("category", "unknown")),
                }
            )
        return rows

    def _add_documents(self, rows: list[dict[str, str]]) -> None:
        ids = [row["id"] for row in rows]
        documents = [row["content"] for row in rows]
        metadatas = [{"source": row["source"], "category": row["category"]} for row in rows]
        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)

    def _build_documents(self) -> Iterable[dict[str, str]]:
        specs = [
            {
                "dataset": "virattt/financial-qa-10K",
                "category": "financial_qa",
                "source": "virattt/financial-qa-10K",
                "limit": int(os.getenv("AI_KB_FINANCIAL_QA_LIMIT", "120")),
                "extractor": self._extract_financial_qa_10k,
            },
            {
                "dataset": "PatronusAI/financebench",
                "category": "financial_qa",
                "source": "PatronusAI/financebench",
                "limit": int(os.getenv("AI_KB_FINANCEBENCH_LIMIT", "80")),
                "extractor": self._extract_financebench,
            },
            {
                "dataset": "zeroshot/twitter-financial-news-topic",
                "category": "crude_oil_market",
                "source": "zeroshot/twitter-financial-news-topic",
                "limit": int(os.getenv("AI_KB_CRUDE_NEWS_LIMIT", "160")),
                "extractor": self._extract_energy_news,
            },
            {
                "dataset": "sujet-ai/Sujet-Finance-Instruct-177k",
                "category": "financial_qa",
                "source": "sujet-ai/Sujet-Finance-Instruct-177k",
                "limit": int(os.getenv("AI_KB_FINANCE_INSTRUCT_LIMIT", "120")),
                "extractor": self._extract_finance_instruct,
            },
        ]

        for spec in specs:
            texts = spec["extractor"](spec["dataset"], spec["limit"])
            source_key = re.sub(r"[^a-zA-Z0-9]+", "-", spec["source"]).strip("-").lower()
            for index, text in enumerate(texts):
                chunks = self._splitter.split_text(text)
                for chunk_index, chunk in enumerate(chunks):
                    if not chunk.strip():
                        continue
                    yield {
                        "id": f"{source_key}-{spec['category']}-{index}-{chunk_index}",
                        "source": spec["source"],
                        "category": spec["category"],
                        "content": chunk.strip(),
                    }

    def _dataset_rows(self, dataset_name: str, split: str = "train"):
        try:
            return self._datasets.load_dataset(
                dataset_name,
                split=split,
                cache_dir=str(self._cache_directory),
                download_config=self._datasets.DownloadConfig(local_files_only=True),
            )
        except Exception:
            return self._datasets.load_dataset(
                dataset_name,
                split=split,
                cache_dir=str(self._cache_directory),
            )

    def _extract_financial_qa_10k(self, dataset_name: str, limit: int) -> list[str]:
        dataset = self._dataset_rows(dataset_name)
        rows = []
        for row in dataset:
            parts = [str(row.get("question", "")), str(row.get("answer", "")), str(row.get("context", ""))]
            text = "\n".join(part.strip() for part in parts if part and str(part).strip())
            if text:
                rows.append(text)
            if len(rows) >= limit:
                break
        return rows

    def _extract_financebench(self, dataset_name: str, limit: int) -> list[str]:
        dataset = self._dataset_rows(dataset_name)
        rows = []
        for row in dataset:
            parts = [
                str(row.get("question", "")),
                str(row.get("answer", "")),
                str(row.get("evidence", "")),
                str(row.get("context", "")),
            ]
            text = "\n".join(part.strip() for part in parts if part and str(part).strip())
            if text:
                rows.append(text)
            if len(rows) >= limit:
                break
        return rows

    def _extract_energy_news(self, dataset_name: str, limit: int) -> list[str]:
        dataset = self._dataset_rows(dataset_name)
        rows = []
        for row in dataset:
            label = row.get("label")
            if str(label) not in {"6", "energy", "oil"} and label != 6:
                continue
            text = str(row.get("text", "")).strip()
            if text:
                rows.append(text)
            if len(rows) >= limit:
                break
        return rows

    def _extract_finance_instruct(self, dataset_name: str, limit: int) -> list[str]:
        dataset = self._dataset_rows(dataset_name)
        rows = []
        for row in dataset:
            parts = [
                str(row.get("instruction", "")),
                str(row.get("input", "")),
                str(row.get("output", "")),
            ]
            text = "\n".join(part.strip() for part in parts if part and str(part).strip())
            if text:
                rows.append(text)
            if len(rows) >= limit:
                break
        return rows


class OilAdvisoryPipeline:
    def __init__(
        self,
        kb: OilFinanceKnowledgeBase,
        advisor: OpenAICompatibleAdvisor,
        top_k: int = 5,
        debug_hook: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.kb = kb
        self.advisor = advisor
        self.top_k = top_k
        self.debug_hook = debug_hook

    def _debug(self, stage: str, **fields: Any) -> None:
        message = stage if not fields else f"{stage} | " + " ".join(f"{key}={value}" for key, value in fields.items())
        LOGGER.info(message)
        if self.debug_hook is not None:
            self.debug_hook(stage, fields)

    def _build_query(self, pred: OilPrediction) -> str:
        return (
            f"石油价格{pred.trend}趋势 风险等级{pred.risk_level} "
            f"区间宽度占比{pred.forecast_band_pct:.2f}% "
            f"{'、'.join(pred.key_drivers[:2])} 套保策略 银行授信"
        )

    def run(self, prediction: OilPrediction) -> AdvisoryReport:
        query = self._build_query(prediction)
        self._debug("pipeline_query_built", query=query, riskLevel=prediction.risk_level)
        self._debug("kb_retrieve_start", target="corporate", topK=self.top_k)
        corp_chunks = self.kb.retrieve(query, top_k=self.top_k, category_filter="financial_qa")
        self._debug("kb_retrieve_done", target="corporate", chunkCount=len(corp_chunks))
        self._debug("kb_retrieve_start", target="bank", topK=self.top_k)
        bank_chunks = self.kb.retrieve(query, top_k=self.top_k, category_filter="crude_oil_market")
        self._debug("kb_retrieve_done", target="bank", chunkCount=len(bank_chunks))
        if not corp_chunks:
            self._debug("kb_retrieve_fallback", target="corporate")
            corp_chunks = self.kb.retrieve(query, top_k=self.top_k)
            self._debug("kb_retrieve_done", target="corporate_fallback", chunkCount=len(corp_chunks))
        if not bank_chunks:
            self._debug("kb_retrieve_fallback", target="bank")
            bank_chunks = self.kb.retrieve(query, top_k=self.top_k)
            self._debug("kb_retrieve_done", target="bank_fallback", chunkCount=len(bank_chunks))

        self._debug("advisor_generate_start", target="corporate")
        corporate_advice = self.advisor.generate(
            SYSTEM_PROMPT,
            build_prompt(prediction, corp_chunks, "corporate"),
        )
        self._debug("advisor_generate_done", target="corporate", charCount=len(corporate_advice))
        self._debug("advisor_generate_start", target="bank")
        bank_advice = self.advisor.generate(
            SYSTEM_PROMPT,
            build_prompt(prediction, bank_chunks, "bank"),
        )
        self._debug("advisor_generate_done", target="bank", charCount=len(bank_advice))

        self._debug("advisor_generate_start", target="preview")
        preview_summary = self.advisor.generate(
            SYSTEM_PROMPT,
            build_preview_prompt(
                (
                    f"WTI ${prediction.wti_price:.2f} | "
                    f"Brent ${prediction.brent_price:.2f} | "
                    f"{prediction.horizon_days}日预测变动 {prediction.forecast_change_pct:+.2f}% | "
                    f"风险等级 {prediction.risk_level}"
                ),
                corporate_advice,
            ),
            temperature=0.2,
        ).replace("\r", " ").replace("\n", " ").strip()
        self._debug("advisor_generate_done", target="preview", charCount=len(preview_summary))

        all_chunks = corp_chunks + bank_chunks
        references = [
            {
                "source": chunk["source"],
                "category": chunk["category"],
                "excerpt": build_reference_excerpt(
                    chunk["content"],
                    chunk["source"],
                    chunk["category"],
                ),
            }
            for chunk in all_chunks
        ]
        self._debug("pipeline_completed", referenceCount=len(references))

        return AdvisoryReport(
            date=prediction.date,
            prediction_summary=(
                f"WTI ${prediction.wti_price:.2f} | "
                f"Brent ${prediction.brent_price:.2f} | "
                f"{prediction.horizon_days}日预测变动 {prediction.forecast_change_pct:+.2f}% | "
                f"风险等级 {prediction.risk_level}"
            ),
            preview_summary=preview_summary,
            corporate_advice=corporate_advice,
            bank_advice=bank_advice,
            retrieved_references=references,
        )

    def save_report(self, report: AdvisoryReport, output_dir: Path) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        base = output_dir / f"ai_advisory_report_{report.date}"
        json_path = base.with_suffix(".json")
        md_path = base.with_suffix(".md")
        json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")

        md_text = f"""# 石油市场每日建议报告
**日期**：{report.date}
**预测摘要**：{report.prediction_summary}

---
## 企业客户建议（套保 · 采购）
{report.corporate_advice}

---
## 银行客户建议（授信 · 风险管理）
{report.bank_advice}

---
## 知识库参考来源
{chr(10).join(f"- [{item['category']}] {item['source']}：{item['excerpt']}" for item in report.retrieved_references)}
"""
        md_path.write_text(md_text, encoding="utf-8")
        return {"json": str(json_path), "md": str(md_path)}


def create_pipeline(generated_root: Path) -> OilAdvisoryPipeline:
    load_project_env()
    chat_api_key = os.getenv("AI_CHAT_API_KEY", "").strip() or os.getenv("AI_OPENAI_API_KEY", "").strip()
    embedding_api_key = os.getenv("AI_EMBEDDING_API_KEY", "").strip() or chat_api_key
    chat_base_url = normalize_openai_base_url(
        os.getenv("AI_CHAT_BASE_URL", "").strip() or os.getenv("AI_OPENAI_BASE_URL", "").strip() or None
    )
    embedding_base_url = normalize_openai_base_url(
        os.getenv("AI_EMBEDDING_BASE_URL", "").strip() or chat_base_url
    )
    chat_model = os.getenv("AI_CHAT_MODEL", "").strip()
    embedding_model = os.getenv("AI_EMBEDDING_MODEL", "").strip()
    if not chat_api_key:
        raise RuntimeError("缺少配置 AI_CHAT_API_KEY")
    if not embedding_api_key:
        raise RuntimeError("缺少配置 AI_EMBEDDING_API_KEY")
    if not chat_model:
        raise RuntimeError("缺少配置 AI_CHAT_MODEL")
    if not embedding_model:
        raise RuntimeError("缺少配置 AI_EMBEDDING_MODEL")

    chat_client = OpenAI(api_key=chat_api_key, base_url=chat_base_url)
    embedding_client = OpenAI(api_key=embedding_api_key, base_url=embedding_base_url)
    embedding_function = OpenAICompatibleEmbeddingFunction(
        embedding_client,
        embedding_model,
        base_url=embedding_base_url,
    )
    kb = OilFinanceKnowledgeBase(
        persist_directory=generated_root / "ai_kb" / "chroma",
        cache_directory=generated_root / "ai_kb" / "datasets_cache",
        embedding_function=embedding_function,
    )
    advisor = OpenAICompatibleAdvisor(
        chat_client,
        chat_model,
        base_url=chat_base_url,
    )
    return OilAdvisoryPipeline(kb=kb, advisor=advisor, top_k=int(os.getenv("AI_ADVISORY_TOP_K", "5")))
