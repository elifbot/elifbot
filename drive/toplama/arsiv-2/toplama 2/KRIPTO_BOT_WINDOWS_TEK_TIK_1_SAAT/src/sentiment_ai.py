"""Korku/Açgözlülük ve opsiyonel LLM destekli haber duygu analizi."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time

from .security import register_secret, sanitize_external_text

_BULLISH_WORDS = {
    "approved": 18.0,
    "approval": 16.0,
    "etf": 14.0,
    "bullish": 14.0,
    "adoption": 12.0,
    "partnership": 10.0,
    "surge": 12.0,
    "rally": 12.0,
    "inflow": 12.0,
    "record": 8.0,
    "upgrade": 8.0,
    "accumulate": 10.0,
    "onay": 16.0,
    "ralli": 12.0,
}

_BEARISH_WORDS = {
    "hack": -28.0,
    "hacked": -28.0,
    "exploit": -26.0,
    "bankrupt": -30.0,
    "bankruptcy": -30.0,
    "insolvent": -28.0,
    "ban": -22.0,
    "banned": -22.0,
    "lawsuit": -16.0,
    "sec": -10.0,
    "crash": -22.0,
    "outflow": -12.0,
    "delist": -20.0,
    "fraud": -24.0,
    "halt": -18.0,
    "iflas": -28.0,
    "çöküş": -22.0,
}


class FearGreedAnalyzer:
    """Yerel sözlük + opsiyonel harici LLM API ile 0..100 Korku/Açgözlülük skoru."""

    def __init__(
        self,
        llm_url: str = "",
        llm_key: str = "",
        llm_model: str = "gpt-4o-mini",
        cache_ttl_sec: float = 1800.0,
    ):
        self.llm_url = llm_url.strip()
        self.llm_key = llm_key.strip()
        self.llm_model = llm_model.strip() or "gpt-4o-mini"
        self.cache_ttl_sec = float(cache_ttl_sec)
        self._cache: dict[str, tuple[float, float]] = {}
        if self.llm_key:
            register_secret(self.llm_key)

    def score_sync(self, text: str) -> float:
        """0 (aşırı korku) .. 100 (aşırı açgözlülük), 50 = nötr."""
        clean = sanitize_external_text(text, max_len=500).lower()
        if not clean:
            return 50.0
        key = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_ttl_sec:
            return cached[1]

        tokens = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", clean)
        delta = 0.0
        for tok in tokens:
            delta += _BULLISH_WORDS.get(tok, 0.0)
            delta += _BEARISH_WORDS.get(tok, 0.0)
        score = max(0.0, min(100.0, round(50.0 + delta, 1)))
        self._cache[key] = (now, score)
        return score

    async def score_async(self, text: str) -> float:
        base = self.score_sync(text)
        if not self.llm_url or not self.llm_key:
            return base
        try:
            import aiohttp

            headers = {
                "Authorization": f"Bearer {self.llm_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return only a number from 0 (extreme fear) to 100 (extreme greed).",
                    },
                    {"role": "user", "content": sanitize_external_text(text, max_len=400)},
                ],
                "temperature": 0.0,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.llm_url, headers=headers, json=payload, timeout=8
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        raw = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content", "")
                        )
                        match = re.search(r"\d+(?:\.\d+)?", str(raw))
                        if match:
                            val = float(match.group(0))
                            return max(0.0, min(100.0, round(val, 1)))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        return base

    def analyze(self, text: str) -> dict:
        """Metinden -100..+100 duygu skoru ve kritik panik vetosu üretir."""
        clean = sanitize_external_text(text, max_len=500).lower()
        tokens = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", clean)
        negations = {"not", "no", "denied", "false", "fake", "yalan", "değil", "yok"}
        critical_terms = {"hacked", "exploit", "stolen", "halted", "bankrupt", "iflas"}
        delta = 0.0
        veto = False
        for idx, tok in enumerate(tokens):
            prev_neg = any(t in negations for t in tokens[max(0, idx - 3) : idx])
            next_neg = any(t in negations for t in tokens[idx + 1 : idx + 3])
            negated = prev_neg or next_neg
            w = _BULLISH_WORDS.get(tok, 0.0) + _BEARISH_WORDS.get(tok, 0.0)
            if negated:
                w *= -0.35
            delta += w
            if tok in critical_terms and not negated:
                veto = True
        score = max(-100.0, min(100.0, round(delta * 2.0, 1)))
        if veto:
            score = min(score, -55.0)
        return {"score": score, "veto": veto}


AISentimentAnalyzer = FearGreedAnalyzer
