from __future__ import annotations

import hashlib
import re
import threading
from csv import DictReader
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from nltk import ne_chunk, pos_tag, word_tokenize
from nltk.sentiment import SentimentIntensityAnalyzer
from nltk.tree import Tree

try:
    from .network_utils import run_with_proxy_fallback
except ImportError:
    from network_utils import run_with_proxy_fallback


NEWS_SOURCE_KEY = "news"
NEWS_SOURCE_NAME = "OilPrice"
NEWS_SOURCE_BASE_URL = "https://oilprice.com/Latest-Energy-News/World-News/"
ANALYZER_VERSION = "nltk-vader-ner-v1"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://oilprice.com/",
}

TOPIC_RULES = {
    "Geopolitical": [
        "sanction",
        "war",
        "attack",
        "military",
        "conflict",
        "ceasefire",
        "red sea",
        "iran",
        "russia",
        "ukraine",
        "israel",
        "gaza",
        "houthi",
    ],
    "Macro": [
        "federal reserve",
        "fed",
        "inflation",
        "interest rate",
        "rate cut",
        "recession",
        "cpi",
        "ppi",
        "gdp",
        "dollar",
        "treasury",
    ],
    "Inventory": [
        "inventory",
        "stockpile",
        "storage",
        "eia",
        "api",
        "spr",
        "draw",
        "build",
        "refinery run",
    ],
    "Policy": [
        "policy",
        "opec",
        "opec+",
        "quota",
        "production cut",
        "output cut",
        "regulation",
        "tariff",
        "subsidy",
    ],
    "Freight": [
        "shipping",
        "freight",
        "tanker",
        "pipeline",
        "port",
        "strait",
        "logistics",
        "transport",
    ],
}

GEO_KEYWORDS = {
    "Red Sea": ["red sea", "bab el-mandeb"],
    "Russia": ["russia", "russian", "moscow"],
    "Ukraine": ["ukraine", "kyiv"],
    "United States": ["united states", "u.s.", "usa", "washington", "america"],
    "China": ["china", "beijing"],
    "Iran": ["iran", "tehran"],
    "Israel": ["israel", "israeli"],
    "Saudi Arabia": ["saudi", "riyadh"],
    "OPEC+": ["opec", "opec+"],
}

MACRO_KEYWORDS = {
    "Rate Cut": ["rate cut", "easing", "federal reserve", "fed", "ecb"],
    "Inflation": ["inflation", "cpi", "ppi"],
    "Inventory": ["inventory", "stockpile", "spr", "eia", "api"],
    "Shale": ["shale", "permian", "drilling", "rig count"],
    "Demand": ["demand", "consumption", "refinery run", "jet fuel"],
    "Freight": ["freight", "shipping", "tanker", "port", "pipeline"],
    "Sanctions": ["sanction", "embargo", "price cap"],
    "OPEC": ["opec", "opec+", "quota", "output cut"],
}

RISK_KEYWORDS = {
    "critical": 18,
    "disruption": 16,
    "attack": 16,
    "war": 18,
    "sanction": 14,
    "shortage": 14,
    "cut": 8,
    "surge": 8,
    "slump": 8,
    "volatility": 10,
    "tight": 6,
}

US_TIMEZONE_OFFSETS = {
    "EDT": -4,
    "EST": -5,
    "CDT": -5,
    "CST": -6,
    "MDT": -6,
    "MST": -7,
    "PDT": -7,
    "PST": -8,
}

NER_ANALYSIS_LOCK = threading.Lock()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return standardize_datetime_value(value)


def standardize_datetime_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value
    if normalized.tzinfo is None or normalized.utcoffset() is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    else:
        normalized = normalized.astimezone(timezone.utc)
    return normalized.isoformat(timespec="seconds")


def parse_flexible_datetime(value: str | None) -> datetime | None:
    clean = normalize_whitespace(value or "")
    if not clean:
        return None

    clean = clean.replace("Z", "+00:00")
    if clean.startswith("ts") and len(clean) > 2:
        clean = clean[2:]
    if re.match(r"^\d{2}-\d{2}-\d{2}T", clean):
        clean = f"20{clean}"

    try:
        parsed = datetime.fromisoformat(clean)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def standardize_published_at(value: str | None) -> str | None:
    parsed = parse_flexible_datetime(value)
    if parsed is None:
        return normalize_whitespace(value) or None
    return standardize_datetime_value(parsed)


def compute_digest(title: str, published_at: str | None, content_text: str) -> str:
    raw = f"{title}\n{published_at or ''}\n{content_text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sentence_preview(text: str, max_sentences: int = 2) -> str:
    chunks = re.split(r"(?<=[.!?])\s+", text)
    preview = " ".join(chunk.strip() for chunk in chunks[:max_sentences] if chunk.strip())
    if preview:
        return preview[:400]
    return text[:400]


def slugify_title(title: str) -> str:
    normalized = re.sub(r"[’']", "", title)
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-")
    return normalized or quote(title)


class OilPriceNewsPipeline:
    def __init__(self) -> None:
        self.sentiment = SentimentIntensityAnalyzer()

    def list_page_url(self, page: int) -> str:
        return NEWS_SOURCE_BASE_URL if page <= 1 else f"{NEWS_SOURCE_BASE_URL}Page-{page}.html"

    def fetch_text(self, url: str, timeout_seconds: int = 25) -> str:
        response = run_with_proxy_fallback(
            lambda session: self._perform_request(
                "GET",
                url,
                headers=REQUEST_HEADERS,
                timeout=timeout_seconds,
                session=session,
            )
        )
        response.raise_for_status()
        return response.text

    def _perform_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        session: requests.Session | None = None,
    ) -> requests.Response:
        if session is None:
            return requests.request(method, url, headers=headers, timeout=timeout)
        return session.request(method, url, headers=headers, timeout=timeout)

    def collect_listing_entries(self, max_pages: int, article_limit: int) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for page in range(1, max_pages + 1):
            for entry in self.fetch_listing_entries_for_page(page):
                if entry["url"] in seen_urls:
                    continue
                seen_urls.add(entry["url"])
                found.append(entry)
                if len(found) >= article_limit:
                    return found
        return found

    def fetch_listing_entries_for_page(self, page: int) -> list[dict[str, str]]:
        html = self.fetch_text(self.list_page_url(page))
        return self.parse_listing_html(html)

    def parse_listing_html(self, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[dict[str, str]] = []
        for article in soup.select("div.categoryArticle"):
            link_tag = article.find("a", href=True)
            title_tag = article.find("h2")
            if not link_tag or not title_tag:
                continue
            url = normalize_whitespace(link_tag["href"])
            title = normalize_whitespace(title_tag.get_text(" ", strip=True))
            if not url or not title:
                continue
            items.append({"url": url, "title": title})
        return items

    def parse_article_html(self, html: str, url: str, fallback_title: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_title(soup, fallback_title)
        published_at = self._extract_published_at(soup)
        published_at = standardize_published_at(published_at)
        author = self._extract_author(soup)
        category = self._extract_category(soup)
        image_url = self._extract_cover_image(soup)
        body = self._extract_body_text(soup)
        summary = self._extract_summary(soup, body)
        article_id = compute_digest(url, published_at, body)[:20]
        return {
            "id": article_id,
            "source": NEWS_SOURCE_NAME,
            "url": url,
            "title": title,
            "published_at": published_at,
            "author": author,
            "summary": summary,
            "content_text": body,
            "content_html": None,
            "cover_image_url": image_url,
            "source_category": category,
            "language": "en",
            "hash_digest": compute_digest(title, published_at, body),
            "status": "ready",
        }

    def analyze_article(self, article: dict[str, Any]) -> dict[str, Any]:
        text = normalize_whitespace(
            " ".join(
                part
                for part in (
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("content_text", ""),
                )
                if part
            )
        )
        sentiment_scores = self.sentiment.polarity_scores(text)
        sentiment_score = round(float(sentiment_scores["compound"]), 4)
        sentiment_label = "positive" if sentiment_score > 0.05 else "negative" if sentiment_score < -0.05 else "neutral"

        extracted_entities = self._extract_named_entities(text)
        geo_entities = self._score_geo_entities(text, extracted_entities)
        macro_entities = self._score_macro_entities(text, extracted_entities)
        topic_tags = self._score_topics(text)
        keywords = self._extract_keywords(text, geo_entities, macro_entities, topic_tags)
        mention_count = sum(item["count"] for item in geo_entities[:6]) + sum(item["count"] for item in macro_entities[:6])
        risk_score = self._compute_risk_score(sentiment_score, geo_entities, topic_tags, text)
        risk_level = "High" if risk_score >= 67 else "Medium" if risk_score >= 34 else "Low"

        return {
            "sentiment_score": sentiment_score,
            "sentiment_label": sentiment_label,
            "tone_score": sentiment_score,
            "geo_entities": geo_entities,
            "macro_entities": macro_entities,
            "topic_tags": topic_tags,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "keywords": keywords,
            "mention_count": mention_count,
            "analyzer_version": ANALYZER_VERSION,
        }

    def build_article_bundle(self, listing_entry: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        html = self.fetch_text(listing_entry["url"])
        article = self.parse_article_html(html, listing_entry["url"], listing_entry["title"])
        analysis = self.analyze_article(article)
        return article, analysis

    def load_summary_index(self, csv_path: Path) -> dict[str, Any]:
        exact_map: dict[tuple[str, str], dict[str, str]] = {}
        title_map: dict[str, list[dict[str, str]]] = {}
        if not csv_path.exists():
            return {"exact": exact_map, "title": title_map}

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = DictReader(handle)
            for row in reader:
                published_at = normalize_whitespace(row.get("发布时间", ""))
                title = normalize_whitespace(row.get("新闻标题", ""))
                url = normalize_whitespace(row.get("新闻页面链接", ""))
                if not title:
                    continue
                metadata = {"published_at": published_at, "title": title, "url": url}
                if published_at:
                    exact_map[(published_at, title.lower())] = metadata
                title_map.setdefault(title.lower(), []).append(metadata)

        return {"exact": exact_map, "title": title_map}

    def parse_historical_filename(self, path: Path) -> dict[str, str]:
        stem = path.stem
        match = re.match(r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})_(?P<title>.+)$", stem)
        if not match:
            raise ValueError(f"无法解析历史新闻文件名：{path.name}")
        raw_time = match.group("timestamp")
        iso_time = raw_time[:13] + ":" + raw_time[14:16] + ":" + raw_time[17:19]
        title = normalize_whitespace(match.group("title"))
        return {"published_at": iso_time, "title": title}

    def build_historical_article(
        self,
        file_path: Path,
        summary_index: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = self.resolve_historical_metadata(file_path, summary_index)
        metadata["published_at"] = standardize_published_at(metadata.get("published_at"))
        content_text = normalize_whitespace(file_path.read_text(encoding="utf-8", errors="ignore"))
        if not content_text:
            raise ValueError(f"历史新闻正文为空：{file_path.name}")

        summary = sentence_preview(content_text)
        article_id = compute_digest(metadata["url"], metadata["published_at"], content_text)[:20]
        return {
            "id": article_id,
            "source": NEWS_SOURCE_NAME,
            "url": metadata["url"],
            "title": metadata["title"],
            "published_at": metadata["published_at"],
            "author": None,
            "summary": summary,
            "content_text": content_text,
            "content_html": None,
            "cover_image_url": None,
            "source_category": "World News",
            "language": "en",
            "hash_digest": compute_digest(metadata["title"], metadata["published_at"], content_text),
            "status": "historical",
            "summary_matched": metadata["summary_matched"],
        }

    def resolve_historical_metadata(self, file_path: Path, summary_index: dict[str, Any]) -> dict[str, Any]:
        filename_meta = self.parse_historical_filename(file_path)
        published_at = filename_meta["published_at"]
        title = filename_meta["title"]
        exact_map = summary_index.get("exact", {})
        title_map = summary_index.get("title", {})

        summary_meta = exact_map.get((published_at, title.lower()))
        if not summary_meta:
            title_matches = title_map.get(title.lower(), [])
            if len(title_matches) == 1:
                summary_meta = title_matches[0]
            else:
                for candidate in title_matches:
                    candidate_time = candidate.get("published_at", "")
                    if candidate_time[:10] == published_at[:10]:
                        summary_meta = candidate
                        break

        url = ""
        if summary_meta:
            url = summary_meta.get("url", "")
            published_at = summary_meta.get("published_at") or published_at
            title = summary_meta.get("title") or title
        if not url:
            url = (
                "https://oilprice.com/Latest-Energy-News/World-News/"
                f"{slugify_title(title)}.html"
            )

        return {
            "url": url,
            "title": title,
            "published_at": published_at,
            "summary_matched": bool(summary_meta),
        }

    def _extract_title(self, soup: BeautifulSoup, fallback_title: str) -> str:
        headline = soup.select_one("h1.singleArticle__title, h1") or soup.find("title")
        if headline:
            value = normalize_whitespace(headline.get_text(" ", strip=True))
            if value:
                return value
        return fallback_title

    def _extract_author(self, soup: BeautifulSoup) -> str | None:
        author_meta = soup.select_one("meta[name='author']")
        if author_meta and author_meta.get("content"):
            return normalize_whitespace(author_meta["content"])
        byline = soup.find("span", class_="article_byline")
        if not byline:
            return None
        text = normalize_whitespace(byline.get_text(" ", strip=True))
        match = re.search(r"By\s+(.*?)\s+-", text, re.IGNORECASE)
        if match:
            return normalize_whitespace(match.group(1))
        return None

    def _extract_published_at(self, soup: BeautifulSoup) -> str | None:
        for selector in (
            "meta[property='article:published_time']",
            "meta[name='article:published_time']",
            "time[datetime]",
        ):
            node = soup.select_one(selector)
            if node and node.get("content"):
                parsed = self._parse_datetime(node["content"])
                if parsed:
                    return iso_or_none(parsed)
            if node and node.get("datetime"):
                parsed = self._parse_datetime(node["datetime"])
                if parsed:
                    return iso_or_none(parsed)

        byline = soup.find("span", class_="article_byline")
        if not byline:
            return None
        text = normalize_whitespace(byline.get_text(" ", strip=True))
        if "-" in text:
            parsed = self._parse_datetime(text.split("-")[-1].strip())
            if parsed:
                return iso_or_none(parsed)
        return None

    def _extract_category(self, soup: BeautifulSoup) -> str | None:
        breadcrumb = soup.select("div.breadcrumb a, nav.breadcrumb a")
        if breadcrumb:
            return normalize_whitespace(breadcrumb[-1].get_text(" ", strip=True))
        return "World News"

    def _extract_cover_image(self, soup: BeautifulSoup) -> str | None:
        for selector in ("meta[property='og:image']", "img[src]"):
            node = soup.select_one(selector)
            if not node:
                continue
            url = node.get("content") or node.get("src")
            if url:
                return normalize_whitespace(url)
        return None

    def _extract_summary(self, soup: BeautifulSoup, body: str) -> str:
        for selector in ("meta[name='description']", "meta[property='og:description']"):
            node = soup.select_one(selector)
            if node and node.get("content"):
                value = normalize_whitespace(node["content"])
                if value:
                    return value
        return sentence_preview(body)

    def _extract_body_text(self, soup: BeautifulSoup) -> str:
        root = soup.find("div", id="news-content") or soup.find("article")
        if not root:
            raise ValueError("新闻正文解析失败：未找到文章内容节点")

        paragraphs = []
        for paragraph in root.find_all("p"):
            text = normalize_whitespace(paragraph.get_text(" ", strip=True))
            if not text:
                continue
            if text.lower().startswith("more top reads"):
                continue
            if text.startswith("By "):
                continue
            paragraphs.append(text)

        body = "\n\n".join(paragraphs).strip()
        if not body:
            raise ValueError("新闻正文解析失败：正文为空")
        return body

    def _parse_datetime(self, value: str) -> datetime | None:
        clean = normalize_whitespace(value)
        if not clean:
            return None
        custom_parsed = self._parse_us_published_datetime(clean)
        if custom_parsed:
            return custom_parsed
        parsed = parse_flexible_datetime(clean)
        if parsed:
            return parsed
        try:
            return parsedate_to_datetime(clean)
        except (TypeError, ValueError, IndexError):
            pass

        for fmt in ("%b %d, %Y, %I:%M %p %Z", "%b %d, %Y, %I:%M %p", "%B %d, %Y %H:%M"):
            try:
                return datetime.strptime(clean, fmt)
            except ValueError:
                continue
        return None

    def _parse_us_published_datetime(self, value: str) -> datetime | None:
        match = re.match(
            r"^(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4}),\s+"
            r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+(?P<ampm>AM|PM)"
            r"(?:\s+(?P<tz>[A-Z]{2,5}))?$",
            value,
            re.IGNORECASE,
        )
        if not match:
            return None

        month = match.group("month")
        day = int(match.group("day"))
        year = int(match.group("year"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        ampm = match.group("ampm").upper()
        timezone_name = (match.group("tz") or "").upper()

        if hour == 12:
            hour = 0
        if ampm == "PM":
            hour += 12

        try:
            parsed = datetime.strptime(f"{month} {day} {year}", "%b %d %Y").replace(hour=hour, minute=minute)
        except ValueError:
            try:
                parsed = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").replace(hour=hour, minute=minute)
            except ValueError:
                return None

        offset_hours = US_TIMEZONE_OFFSETS.get(timezone_name)
        if offset_hours is None:
            return parsed
        return parsed.replace(tzinfo=timezone(timedelta(hours=offset_hours)))

    def _extract_named_entities(self, text: str) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        try:
            # NLTK named-entity internals lazily initialize shared corpus readers and
            # are not safe to initialize concurrently from multiple threads.
            with NER_ANALYSIS_LOCK:
                tree = ne_chunk(pos_tag(word_tokenize(text[:8000])))
        except LookupError:
            return entities

        counts: Counter[tuple[str, str]] = Counter()
        for node in tree:
            if isinstance(node, Tree):
                label = node.label()
                name = normalize_whitespace(" ".join(token for token, _ in node.leaves()))
                if name:
                    counts[(name, label)] += 1

        for (name, label), count in counts.most_common():
            entities.append({"label": name, "type": label, "count": count})
        return entities

    def _score_geo_entities(self, text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: Counter[str] = Counter()
        lowered = text.lower()

        for entity in entities:
            if entity["type"] in {"GPE", "GSP", "LOCATION", "ORGANIZATION"}:
                normalized = self._map_geo_label(entity["label"])
                if normalized:
                    counter[normalized] += int(entity["count"])

        for label, aliases in GEO_KEYWORDS.items():
            alias_hits = sum(lowered.count(alias) for alias in aliases)
            if alias_hits:
                counter[label] += alias_hits

        top_value = max(counter.values(), default=0)
        return [
            {
                "label": label,
                "count": count,
                "value": int(round((count / top_value) * 100)) if top_value else 0,
            }
            for label, count in counter.most_common(8)
        ]

    def _score_macro_entities(self, text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: Counter[str] = Counter()
        lowered = text.lower()

        for label, aliases in MACRO_KEYWORDS.items():
            hits = sum(lowered.count(alias) for alias in aliases)
            if hits:
                counter[label] += hits

        for entity in entities:
            entity_name = entity["label"].lower()
            for label, aliases in MACRO_KEYWORDS.items():
                if any(alias in entity_name for alias in aliases):
                    counter[label] += int(entity["count"])

        return [{"label": label, "count": count} for label, count in counter.most_common(12)]

    def _score_topics(self, text: str) -> list[dict[str, Any]]:
        lowered = text.lower()
        topic_scores = []
        for topic, keywords in TOPIC_RULES.items():
            score = sum(lowered.count(keyword) for keyword in keywords)
            if score:
                topic_scores.append({"label": topic, "count": score})
        if not topic_scores:
            topic_scores.append({"label": "Macro", "count": 1})
        topic_scores.sort(key=lambda item: item["count"], reverse=True)
        return topic_scores

    def _extract_keywords(
        self,
        text: str,
        geo_entities: list[dict[str, Any]],
        macro_entities: list[dict[str, Any]],
        topic_tags: list[dict[str, Any]],
    ) -> list[str]:
        keywords: list[str] = []
        keywords.extend(item["label"] for item in geo_entities[:4])
        keywords.extend(item["label"] for item in macro_entities[:4])
        keywords.extend(item["label"] for item in topic_tags[:2])
        normalized = []
        seen: set[str] = set()
        for keyword in keywords:
            value = normalize_whitespace(keyword)
            if value and value.lower() not in seen:
                seen.add(value.lower())
                normalized.append(value)
        if normalized:
            return normalized[:8]

        token_counts = Counter(
            token.lower()
            for token in re.findall(r"[A-Za-z][A-Za-z\-\+]{2,}", text)
            if token.lower() not in {"with", "that", "from", "have", "this", "will", "into"}
        )
        return [token for token, _ in token_counts.most_common(8)]

    def _compute_risk_score(
        self,
        sentiment_score: float,
        geo_entities: list[dict[str, Any]],
        topic_tags: list[dict[str, Any]],
        text: str,
    ) -> int:
        lowered = text.lower()
        score = min(abs(sentiment_score) * 38, 32)
        score += min(sum(item["count"] for item in geo_entities[:4]) * 6, 28)
        score += min(sum(item["count"] for item in topic_tags[:3]) * 4, 18)
        score += min(sum(lowered.count(keyword) * weight for keyword, weight in RISK_KEYWORDS.items()) / 8, 22)
        return max(0, min(100, int(round(score))))

    def _map_geo_label(self, label: str) -> str | None:
        lowered = label.lower()
        for canonical, aliases in GEO_KEYWORDS.items():
            if lowered == canonical.lower() or any(alias in lowered for alias in aliases):
                return canonical
        return None
