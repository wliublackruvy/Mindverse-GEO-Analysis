from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .errors import SensitiveContentError
from .models import DiagnosisRequest, Industry, SENSITIVE_KEYWORDS, SENSITIVE_BLOCK_MESSAGE


class SecretsManager:
    """Thread-safe secrets registry that tracks quota usage (PRD F-06.1)."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._alerts: List[Dict[str, Any]] = []

    def register_key(
        self,
        name: str,
        api_key: str,
        *,
        quota_limit: int = 0,
        expires_at: Optional[float] = None,
    ) -> None:
        with self._lock:
            self._records[name] = {
                "api_key": api_key,
                "quota_limit": quota_limit,
                "expires_at": expires_at,
                "usage": 0,
                "alerted": False,
            }

    def has_key(self, name: str) -> bool:
        with self._lock:
            return name in self._records

    def get_key(self, name: str) -> str:
        with self._lock:
            if name not in self._records:
                raise KeyError(f"Secret '{name}' not found")
            return self._records[name]["api_key"]

    def revoke_key(self, name: str) -> None:
        with self._lock:
            self._records.pop(name, None)

    def record_usage(self, name: str, used_tokens: int) -> None:
        if used_tokens <= 0:
            return
        with self._lock:
            record = self._records.get(name)
            if not record:
                return
            record["usage"] += used_tokens
            quota = record.get("quota_limit") or 0
            if quota and not record["alerted"] and record["usage"] >= quota * 0.8:
                record["alerted"] = True
                self._alerts.append(
                    {
                        "name": name,
                        "message": "API Key usage exceeded 80% of quota",
                        "usage": record["usage"],
                        "quota_limit": quota,
                        "expires_at": record.get("expires_at"),
                    }
                )

    def snapshot(self, name: str) -> Dict[str, Any]:
        with self._lock:
            if name not in self._records:
                raise KeyError(f"Secret '{name}' not found")
            return dict(self._records[name])

    def consume_alerts(self) -> List[Dict[str, Any]]:
        with self._lock:
            alerts = list(self._alerts)
            self._alerts.clear()
        return alerts


class RateLimitError(RuntimeError):
    pass


class LLMClientError(RuntimeError):
    pass


class TokenBucket:
    """Simple RPM bucket for Doubao/DeepSeek (PRD F-06.3)."""

    def __init__(self, *, capacity: int = 60, refill_rate_per_min: int = 60) -> None:
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_rate = refill_rate_per_min / 60.0
        self.updated_at = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> None:
        with self._lock:
            self._refill()
            if tokens > self.tokens:
                raise RateLimitError("Token bucket empty")
            self.tokens -= tokens

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated_at
        if elapsed <= 0:
            return
        refill = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + refill)
        self.updated_at = now


class BaseChatClient:
    """Shared HTTP client for POST /v1/chat/completions."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        secret_name: str,
        secrets: SecretsManager,
        token_bucket: TokenBucket,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.secret_name = secret_name
        self.secrets = secrets
        self.token_bucket = token_bucket
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> Dict[str, str]:
        api_key = self.secrets.get_key(self.secret_name)
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.token_bucket.consume()
        response = self.session.post(
            f"{self.base_url}/v1/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        self.secrets.record_usage(self.secret_name, int(usage.get("total_tokens", 0)))
        return data


class DoubaoClient(BaseChatClient):
    def __init__(
        self,
        *,
        secrets: SecretsManager,
        token_bucket: TokenBucket,
        base_url: str = "https://api.doubao.com",
        model: str = "doubao-pro",
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            secret_name="doubao",
            secrets=secrets,
            token_bucket=token_bucket,
            timeout=timeout,
            session=session,
        )

    def create_chat_completion(self, *, messages: List[Dict[str, str]], **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": extra.get("temperature", 0.4),
            "top_p": extra.get("top_p", 0.8),
        }
        payload.update(extra)
        return self._post(payload)


class DeepSeekClient(BaseChatClient):
    def __init__(
        self,
        *,
        secrets: SecretsManager,
        token_bucket: TokenBucket,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            secret_name="deepseek",
            secrets=secrets,
            token_bucket=token_bucket,
            timeout=timeout,
            session=session,
        )

    def create_chat_completion(self, *, messages: List[Dict[str, str]], **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": extra.get("max_tokens", 512),
        }
        payload.update(extra)
        data = self._post(payload)
        for choice in data.get("choices", []):
            finish_reason = choice.get("finish_reason")
            if finish_reason not in {"stop", "length"}:
                raise LLMClientError("DeepSeek reported abnormal finish_reason")
        return data


@dataclass
class LLMCall:
    task_id: str
    platform: str
    prompt_type: str
    prompt_hash: str
    content: str
    finish_reason: str
    mentions: List[str]
    sentiment: float
    cached: bool
    latency_ms: float


@dataclass
class RawTraceEntry:
    platform: str
    prompt_type: str
    content: List[str]
    mentions: List[str]
    sentiment_score: float
    latency_ms: float
    recorded_at: float


@dataclass
class SummaryTraceEntry:
    payload: Dict[str, Any]
    recorded_at: float


class LLMTraceStore:
    """In-memory trace store with retention policy (PRD F-06.4)."""

    def __init__(
        self,
        *,
        raw_ttl: int = 30 * 24 * 3600,
        summary_ttl: int = 365 * 24 * 3600,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.raw_ttl = raw_ttl
        self.summary_ttl = summary_ttl
        self._time = time_fn or time.time
        self._raw: Dict[str, List[RawTraceEntry]] = {}
        self._summary: Dict[str, SummaryTraceEntry] = {}

    def record_raw(self, call: LLMCall) -> None:
        now = self._time()
        entry = RawTraceEntry(
            platform=call.platform,
            prompt_type=call.prompt_type,
            content=[call.content],
            mentions=list(call.mentions),
            sentiment_score=call.sentiment,
            latency_ms=call.latency_ms,
            recorded_at=now,
        )
        self._raw.setdefault(call.task_id, []).append(entry)
        self._cleanup()

    def record_summary(self, task_id: str, payload: Dict[str, Any]) -> None:
        now = self._time()
        self._summary[task_id] = SummaryTraceEntry(
            payload=dict(payload),
            recorded_at=now,
        )
        self._cleanup()

    def get_trace(self, task_id: str) -> Dict[str, Any]:
        self._cleanup()
        raw_entries = [
            {
                "platform": entry.platform,
                "prompt_type": entry.prompt_type,
                "content": entry.content,
                "mentions": entry.mentions,
                "sentiment": {"score": entry.sentiment_score},
                "latency_ms": round(entry.latency_ms, 2),
                "recorded_at": entry.recorded_at,
            }
            for entry in self._raw.get(task_id, [])
        ]
        summary = None
        existing_summary = self._summary.get(task_id)
        if existing_summary:
            summary = {
                **existing_summary.payload,
                "recorded_at": existing_summary.recorded_at,
            }
        return {"task_id": task_id, "raw": raw_entries, "summary": summary}

    def _cleanup(self) -> None:
        now = self._time()
        for task_id, entries in list(self._raw.items()):
            filtered = [
                entry
                for entry in entries
                if now - entry.recorded_at <= self.raw_ttl
            ]
            if filtered:
                self._raw[task_id] = filtered
            else:
                self._raw.pop(task_id, None)
        for task_id, summary in list(self._summary.items()):
            if now - summary.recorded_at > self.summary_ttl:
                self._summary.pop(task_id, None)


@dataclass
class LLMObservation:
    iteration: int
    platform: str
    platform_key: str
    recommended: bool
    competitor: Optional[str]
    sentiment: float
    tag: str
    cached: bool = False


@dataclass
class LLMRunResult:
    task_id: str
    observations: List[LLMObservation]
    coverage: Dict[str, bool]
    cache_note: Optional[str]
    degraded: bool


class LLMOrchestrator:
    """Coordinates real Doubao/DeepSeek calls + fallback logic (PRD F-06, E-01/E-02)."""

    _EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    _PHONE_RE = re.compile(r"\b\d{3,4}-?\d{4,}\b")
    _ADDRESS_RE = re.compile(r"[\w\d]{0,10}(?:路|街|道|号)\w*", re.UNICODE)
    _MENTION_RE = re.compile(r"[A-Z][A-Za-z0-9\-]+")
    _PLATFORM_LABELS = {"doubao": "豆包", "deepseek": "DeepSeek"}

    def __init__(
        self,
        *,
        secrets: Optional[SecretsManager] = None,
        doubao_client: Optional[DoubaoClient] = None,
        deepseek_client: Optional[DeepSeekClient] = None,
        cache_ttl: int = 86400,
        industry_competitors: Optional[Dict[Industry, List[str]]] = None,
        positive_keywords: Optional[Dict[str, float]] = None,
        negative_keywords: Optional[Dict[str, float]] = None,
        negative_tags: Optional[List[str]] = None,
        trace_store: Optional[LLMTraceStore] = None,
    ) -> None:
        self.secrets = secrets or SecretsManager()
        self.cache_ttl = cache_ttl
        self.industry_competitors = industry_competitors or {}
        self.positive_keywords = positive_keywords or {}
        self.negative_keywords = negative_keywords or {}
        self.negative_tags = negative_tags or ["体验顺畅"]
        self.trace_store = trace_store or LLMTraceStore()
        self._cache: Dict[str, Tuple[float, LLMCall]] = {}
        self._task_queue: List[str] = []
        self._llm_logs: List[Dict[str, Any]] = []
        self._parser_version = "geo-llm-parser-v1"
        self._token_buckets = {
            "doubao": TokenBucket(),
            "deepseek": TokenBucket(),
        }
        self._bootstrap_secrets_from_env()
        self.clients: Dict[str, Optional[BaseChatClient]] = {
            "doubao": doubao_client or self._build_doubao_client(),
            "deepseek": deepseek_client or self._build_deepseek_client(),
        }

    @property
    def task_queue(self) -> List[str]:
        return list(self._task_queue)

    @property
    def llm_logs(self) -> List[Dict[str, Any]]:
        return list(self._llm_logs)

    def simulate(self, request: DiagnosisRequest, *, iterations: int) -> LLMRunResult:
        if not any(self.clients.values()):
            return self._simulate_offline(request, iterations)
        return self._simulate_online(request, iterations)

    def _simulate_offline(self, request: DiagnosisRequest, iterations: int) -> LLMRunResult:
        base_strength = 0.45
        normalized_desc = request.product_description.lower()
        for keyword, delta in self.positive_keywords.items():
            if keyword.lower() in normalized_desc:
                base_strength += delta
        for keyword, delta in self.negative_keywords.items():
            if keyword.lower() in normalized_desc:
                base_strength -= delta / 2
        base_strength = max(0.05, min(0.95, base_strength))
        recommended_runs = int(round(iterations * base_strength))

        negative_ratio = 0.1
        for keyword, delta in self.negative_keywords.items():
            if keyword.lower() in normalized_desc:
                negative_ratio += delta
        negative_ratio = min(0.9, max(0.0, negative_ratio))
        negative_runs = int(round(iterations * negative_ratio))

        competitors = self._inline_competitors(request)
        observations: List[LLMObservation] = []
        platforms = ["doubao", "deepseek"]
        for platform_key in platforms:
            platform_label = self._PLATFORM_LABELS[platform_key]
            for iteration in range(iterations):
                recommended = iteration < recommended_runs
                competitor = None
                if not recommended and competitors:
                    competitor = competitors[(iteration + platforms.index(platform_key)) % len(competitors)]
                sentiment = -0.3 if iteration < negative_runs else 0.2
                tag = self.negative_tags[iteration % len(self.negative_tags)]
                observations.append(
                    LLMObservation(
                        iteration=len(observations) + 1,
                        platform=platform_label,
                        platform_key=platform_key,
                        recommended=recommended,
                        competitor=competitor,
                        sentiment=sentiment,
                        tag=tag,
                    )
                )
        return LLMRunResult(
            task_id=str(uuid.uuid4()),
            observations=observations,
            coverage={"doubao": False, "deepseek": False},
            cache_note=None,
            degraded=False,
        )

    def _simulate_online(self, request: DiagnosisRequest, iterations: int) -> LLMRunResult:
        task_id = str(uuid.uuid4())
        self._task_queue.append(task_id)
        coverage = {name: False for name in self.clients}
        strike_counts = {name: 0 for name in self.clients}
        cache_note: Optional[str] = None
        active_clients = {name: client for name, client in self.clients.items() if client}
        if not active_clients:
            return self._simulate_offline(request, iterations)

        observations: List[LLMObservation] = []
        for iteration in range(iterations):
            for platform_key in list(active_clients.keys()):
                client = active_clients.get(platform_key)
                if not client:
                    continue
                platform_label = self._PLATFORM_LABELS.get(platform_key, platform_key)
                iteration_calls: Dict[str, LLMCall] = {}
                prompts = (
                    ("discovery", self._build_discovery_prompt(request)),
                    ("evaluation", self._build_evaluation_prompt(request)),
                )
                for prompt_type, prompt in prompts:
                    cache_key = self._cache_key(platform_key, prompt)
                    try:
                        call = self._invoke_client(
                            client=client,
                            task_id=task_id,
                            platform=platform_label,
                            platform_key=platform_key,
                            prompt_type=prompt_type,
                            prompt=prompt,
                            request=request,
                        )
                        strike_counts[platform_key] = 0
                        coverage[platform_key] = True
                        iteration_calls[prompt_type] = call
                        self._write_cache(cache_key, call)
                    except SensitiveContentError:
                        raise
                    except LLMClientError:
                        strike_counts[platform_key] += 1
                        cached_call = self._read_cache(cache_key)
                        if cached_call:
                            cache_note = "(来自缓存，已进入实时重试队列)"
                            iteration_calls[prompt_type] = replace(cached_call, cached=True)
                        if strike_counts[platform_key] >= 3:
                            active_clients.pop(platform_key, None)
                            break
                if not iteration_calls:
                    continue
                observations.append(
                    self._calls_to_observation(
                        iteration=len(observations) + 1,
                        platform=platform_label,
                        platform_key=platform_key,
                        calls=iteration_calls,
                        request=request,
                    )
                )
            if not active_clients:
                break

        degraded = not observations
        if degraded:
            return LLMRunResult(
                task_id=task_id,
                observations=[],
                coverage=coverage,
                cache_note=cache_note,
                degraded=True,
            )
        return LLMRunResult(
            task_id=task_id,
            observations=observations,
            coverage=coverage,
            cache_note=cache_note,
            degraded=False,
        )

    def _invoke_client(
        self,
        *,
        client: BaseChatClient,
        task_id: str,
        platform: str,
        platform_key: str,
        prompt_type: str,
        prompt: str,
        request: DiagnosisRequest,
    ) -> LLMCall:
        start = time.perf_counter()
        attempts = 3
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                response = client.create_chat_completion(messages=[{"role": "user", "content": prompt}])
                break
            except (requests.RequestException, RateLimitError, LLMClientError) as exc:  # pragma: no cover
                last_error = exc
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMClientError(str(exc)) from exc
        else:  # pragma: no cover
            raise LLMClientError(str(last_error))
        latency_ms = (time.perf_counter() - start) * 1000
        choices = response.get("choices")
        if not choices:
            raise LLMClientError("No choices returned")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if self._contains_sensitive_output(content):
            raise SensitiveContentError(SENSITIVE_BLOCK_MESSAGE)
        finish_reason = choices[0].get("finish_reason", "")
        mentions = self._extract_mentions(content)
        sentiment = self._score_sentiment(content)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        call = LLMCall(
            task_id=task_id,
            platform=platform,
            prompt_type=prompt_type,
            prompt_hash=prompt_hash,
            content=content,
            finish_reason=finish_reason,
            mentions=mentions,
            sentiment=sentiment,
            cached=False,
            latency_ms=latency_ms,
        )
        self.trace_store.record_raw(call)
        self._llm_logs.append(
            {
                "task_id": task_id,
                "platform": platform_key,
                "prompt_type": prompt_type,
                 "content": [content],
                 "mentions": mentions,
                 "sentiment": {"score": sentiment},
                "prompt_hash": prompt_hash,
                "response_json": response,
                "latency_ms": round(latency_ms, 2),
                "parser_version": self._parser_version,
            }
        )
        return call

    def _calls_to_observation(
        self,
        *,
        iteration: int,
        platform: str,
        platform_key: str,
        calls: Dict[str, LLMCall],
        request: DiagnosisRequest,
    ) -> LLMObservation:
        discovery = calls.get("discovery")
        evaluation = calls.get("evaluation")
        recommended = False
        competitor: Optional[str] = None
        if discovery:
            recommended = self._is_recommended(discovery.content, request)
            competitor = self._pick_competitor(discovery.mentions, request)
        sentiment = 0.0
        if evaluation:
            sentiment = evaluation.sentiment
        elif discovery:
            sentiment = discovery.sentiment
        tag = self._tag_from_sentiment(sentiment)
        cached = any(call.cached for call in calls.values())
        return LLMObservation(
            iteration=iteration,
            platform=platform,
            platform_key=platform_key,
            recommended=recommended,
            competitor=competitor,
            sentiment=sentiment,
            tag=tag,
            cached=cached,
        )

    def _build_discovery_prompt(self, request: DiagnosisRequest) -> str:
        description = self._sanitize_input(request.product_description)
        return f"推荐 5 款适合{description}的产品。"

    def _build_evaluation_prompt(self, request: DiagnosisRequest) -> str:
        company = self._sanitize_input(request.company_name)
        product = self._sanitize_input(request.product_name)
        return f"评价一下{company}的{product}怎么样？"

    def _sanitize_input(self, text: str) -> str:
        sanitized = self._EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        sanitized = self._PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
        sanitized = self._ADDRESS_RE.sub("[REDACTED_ADDRESS]", sanitized)
        return sanitized

    def _cache_key(self, platform: str, prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return f"{platform}:{digest}"

    def _write_cache(self, key: str, call: LLMCall) -> None:
        self._cache[key] = (time.time(), call)

    def _read_cache(self, key: str) -> Optional[LLMCall]:
        payload = self._cache.get(key)
        if not payload:
            return None
        ts, call = payload
        if time.time() - ts > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        return call

    def _is_recommended(self, content: str, request: DiagnosisRequest) -> bool:
        normalized = content.lower()
        return request.product_name.lower() in normalized or request.company_name.lower() in normalized

    def _pick_competitor(self, mentions: List[str], request: DiagnosisRequest) -> Optional[str]:
        normalized_company = request.company_name.lower()
        normalized_product = request.product_name.lower()
        for mention in mentions:
            lowered = mention.lower()
            if lowered not in {normalized_company, normalized_product}:
                return mention
        inline = self._inline_competitors(request)
        return inline[0] if inline else None

    def _score_sentiment(self, content: str) -> float:
        normalized = content.lower()
        score = 0.0
        for keyword, delta in self.positive_keywords.items():
            if keyword.lower() in normalized:
                score += delta
        for keyword, delta in self.negative_keywords.items():
            if keyword.lower() in normalized:
                score -= delta
        return max(-1.0, min(1.0, score))

    def _tag_from_sentiment(self, sentiment: float) -> str:
        if sentiment < -0.2:
            return self.negative_tags[0] if self.negative_tags else "体验波动"
        if sentiment < 0:
            return self.negative_tags[0]
        return "体验顺畅"

    def _extract_mentions(self, text: str) -> List[str]:
        return self._MENTION_RE.findall(text)

    def _inline_competitors(self, request: DiagnosisRequest) -> List[str]:
        deduped: Dict[str, None] = {}
        for candidate in self._MENTION_RE.findall(request.product_description):
            deduped.setdefault(candidate, None)
        if not deduped:
            for candidate in self.industry_competitors.get(request.industry, []):
                deduped.setdefault(candidate, None)
        return list(deduped.keys())

    def _contains_sensitive_output(self, content: str) -> bool:
        normalized = content.lower()
        return any(keyword.lower() in normalized for keyword in SENSITIVE_KEYWORDS)

    def _bootstrap_secrets_from_env(self) -> None:
        mapping = {
            "doubao": "DOUBAO_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        for name, env_var in mapping.items():
            value = os.getenv(env_var)
            if value and not self.secrets.has_key(name):
                self.secrets.register_key(name, value)

    def _build_doubao_client(self) -> Optional[DoubaoClient]:
        if not self.secrets.has_key("doubao"):
            return None
        return DoubaoClient(
            secrets=self.secrets,
            token_bucket=self._token_buckets["doubao"],
        )

    def _build_deepseek_client(self) -> Optional[DeepSeekClient]:
        if not self.secrets.has_key("deepseek"):
            return None
        return DeepSeekClient(
            secrets=self.secrets,
            token_bucket=self._token_buckets["deepseek"],
        )
