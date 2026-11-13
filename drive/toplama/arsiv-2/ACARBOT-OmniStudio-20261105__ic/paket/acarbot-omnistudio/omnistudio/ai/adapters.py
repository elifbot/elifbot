"""Gerçek YZ sağlayıcı adapter'ları — 4 protokol, 20 sağlayıcı.

Güvenlik/davranış kuralları:
  * Anahtar yoksa ağ çağrısı YAPILMAZ; `NotConfigured` döner.
  * Timeout, yeniden deneme ve devre kesici vardır.
  * Başarısızlık YZ onayı SAYILMAZ. Çağıran katman fail-closed davranır
    (v9.1'in kaldırdığı kör "fail-open" geri gelmez).
  * Yanıt katı JSON olarak ayrıştırılır; bozuk JSON reddedilir.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from ..core.clock import get_logger, mono
from .registry import ProviderSpec

log = get_logger("ai.adapter")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ProviderError(Exception):
    """Sağlayıcı çağrısı başarısız. Asla onay anlamına gelmez."""


class NotConfigured(ProviderError):
    """Anahtar yok — çağrı yapılmadı."""


def extract_json(text: str) -> dict[str, Any]:
    """Model çıktısından katı JSON çıkarır. Bulamazsa ProviderError."""
    if not text or not text.strip():
        raise ProviderError("empty_response")
    s = text.strip()
    m = _JSON_FENCE.search(s)
    if m:
        s = m.group(1).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise ProviderError("no_json_object") from None
        try:
            obj = json.loads(s[i:j + 1])
        except json.JSONDecodeError as e:
            raise ProviderError(f"malformed_json: {e}") from None
    if not isinstance(obj, dict):
        raise ProviderError("json_not_object")
    return obj


@dataclass
class CircuitBreaker:
    """Ardışık hatalarda sağlayıcıyı geçici devre dışı bırakır."""
    fail_threshold: int = 3
    cooldown_sec: float = 120.0
    failures: int = 0
    opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if mono() - self.opened_at >= self.cooldown_sec:
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_threshold:
            self.opened_at = mono()


@dataclass
class AdapterStats:
    calls: int = 0
    ok: int = 0
    errors: int = 0
    timeouts: int = 0
    skipped_unconfigured: int = 0
    skipped_circuit: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls, "ok": self.ok, "errors": self.errors,
            "timeouts": self.timeouts,
            "skipped_unconfigured": self.skipped_unconfigured,
            "skipped_circuit": self.skipped_circuit,
            "mean_latency_ms": round(self.total_latency_ms / self.ok, 2) if self.ok else 0.0,
            "max_latency_ms": round(self.max_latency_ms, 2),
        }


@dataclass
class ProviderAdapter:
    """Tek sağlayıcı için gerçek HTTP istemcisi."""
    spec: ProviderSpec
    timeout_sec: float = 6.0
    max_tokens: int = 700
    temperature: float = 0.1
    max_retries: int = 1
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    stats: AdapterStats = field(default_factory=AdapterStats)

    @property
    def available(self) -> bool:
        return self.spec.configured and not self.breaker.is_open

    async def complete_json(
        self, session: aiohttp.ClientSession, system: str, user: str,
    ) -> dict[str, Any]:
        """Katı JSON yanıt ister. Hata halinde ProviderError yükseltir."""
        if not self.spec.configured:
            self.stats.skipped_unconfigured += 1
            raise NotConfigured(f"{self.spec.provider_id}: {self.spec.env_key} tanımlı değil")
        if self.breaker.is_open:
            self.stats.skipped_circuit += 1
            raise ProviderError(f"{self.spec.provider_id}: devre kesici açık")

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.stats.calls += 1
            t0 = mono()
            try:
                raw = await self._dispatch(session, system, user)
                obj = extract_json(raw)
                dt = (mono() - t0) * 1000.0
                self.stats.ok += 1
                self.stats.total_latency_ms += dt
                self.stats.max_latency_ms = max(self.stats.max_latency_ms, dt)
                self.breaker.record_success()
                obj.setdefault("_provider", self.spec.provider_id)
                obj.setdefault("_model", self.spec.model())
                obj.setdefault("_latency_ms", round(dt, 2))
                return obj
            except asyncio.TimeoutError as e:
                self.stats.timeouts += 1
                last_err = e
                self.breaker.record_failure()
                log.warning("%s timeout (deneme %d)", self.spec.provider_id, attempt + 1)
            except (aiohttp.ClientError, ProviderError) as e:
                self.stats.errors += 1
                last_err = e
                self.breaker.record_failure()
                log.warning("%s hata: %s", self.spec.provider_id, str(e)[:160])
            if attempt < self.max_retries:
                await asyncio.sleep(0.35 * (attempt + 1))
        raise ProviderError(f"{self.spec.provider_id}: {type(last_err).__name__}: {last_err}")

    async def _dispatch(self, session: aiohttp.ClientSession, system: str, user: str) -> str:
        p = self.spec.protocol
        if p == "openai":
            return await self._openai(session, system, user)
        if p == "anthropic":
            return await self._anthropic(session, system, user)
        if p == "gemini":
            return await self._gemini(session, system, user)
        if p == "cohere":
            return await self._cohere(session, system, user)
        raise ProviderError(f"bilinmeyen protokol: {p}")

    async def _openai(self, session: aiohttp.ClientSession, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.spec.api_key()}",
                   "Content-Type": "application/json", **self.spec.extra_headers}
        payload: dict[str, Any] = {
            "model": self.spec.model(),
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.spec.supports_json and self.spec.provider_id not in {"perplexity", "openrouter"}:
            payload["response_format"] = {"type": "json_object"}
        async with session.post(
            f"{self.spec.base_url.rstrip('/')}/chat/completions",
            headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
        ) as r:
            body = await r.text()
            if r.status != 200:
                raise ProviderError(f"HTTP{r.status}: {body[:200]}")
            data = json.loads(body)
            return data["choices"][0]["message"]["content"] or ""

    async def _anthropic(self, session: aiohttp.ClientSession, system: str, user: str) -> str:
        headers = {"x-api-key": self.spec.api_key(),
                   "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        payload = {
            "model": self.spec.model(), "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": self.temperature, "max_tokens": self.max_tokens,
        }
        async with session.post(
            f"{self.spec.base_url.rstrip('/')}/messages",
            headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
        ) as r:
            body = await r.text()
            if r.status != 200:
                raise ProviderError(f"HTTP{r.status}: {body[:200]}")
            data = json.loads(body)
            return "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text")

    async def _gemini(self, session: aiohttp.ClientSession, system: str, user: str) -> str:
        url = (f"{self.spec.base_url.rstrip('/')}/models/"
               f"{self.spec.model()}:generateContent?key={self.spec.api_key()}")
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature, "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
        ) as r:
            body = await r.text()
            if r.status != 200:
                raise ProviderError(f"HTTP{r.status}: {body[:200]}")
            data = json.loads(body)
            cands = data.get("candidates") or []
            if not cands:
                raise ProviderError("gemini_no_candidates")
            parts = cands[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)

    async def _cohere(self, session: aiohttp.ClientSession, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.spec.api_key()}",
                   "Content-Type": "application/json"}
        payload = {
            "model": self.spec.model(),
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature, "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        async with session.post(
            f"{self.spec.base_url.rstrip('/')}/chat",
            headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
        ) as r:
            body = await r.text()
            if r.status != 200:
                raise ProviderError(f"HTTP{r.status}: {body[:200]}")
            data = json.loads(body)
            msg = data.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                return "".join(c.get("text", "") for c in content)
            return str(content or "")


def build_adapters(specs: list[ProviderSpec], timeout_sec: float = 6.0) -> list[ProviderAdapter]:
    return [ProviderAdapter(spec=s, timeout_sec=timeout_sec) for s in specs]