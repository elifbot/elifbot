"""RSS + opsiyonel CryptoPanic haber akışı, duygu skoru ve kriz vetosu."""
from __future__ import annotations

import asyncio
import calendar
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from .security import register_secret, sanitize_external_text, sanitize_url
from .sentiment_ai import FearGreedAnalyzer

_POSITIVE_RULES = (
    (r"\betf\b.*\bapprov", 45.0, "ETF"),
    (r"\bapprov", 30.0, "ONAY"),
    (r"\binstitutional\b|\binflow\b|\badoption\b", 25.0, "KURUMSAL"),
    (r"\bpartnership\b|\bupgrade\b|\bmainnet\b", 18.0, "GELİŞTİRME"),
    (r"\brally\b|\bsurge\b|\bbreakout\b|\ball[- ]time high\b", 20.0, "RALLİ"),
)

_NEGATIVE_RULES = (
    (r"\bhack(?:ed)?\b|\bexploit\b|\bdrained\b|\bbreach\b", -85.0, True, "KRİTİK"),
    (r"\bbankrupt(?:cy)?\b|\binsolven(?:t|cy)\b|\bhalt(?:ed)?\b", -90.0, True, "KRİTİK"),
    (r"\bsec\b.*\blawsuit\b|\bindict(?:ed|ment)\b|\bfraud\b", -65.0, True, "REGÜLASYON"),
    (r"\bban(?:ned)?\b|\bdelist(?:ed|ing)?\b", -45.0, False, "OLUMSUZ"),
    (r"\boutflow\b|\bcrash\b|\bliquidat|\bdump\b", -30.0, False, "SATIŞ"),
)


def score_text(title: str, summary: str = "") -> tuple[float, bool, list[str]]:
    """Haber başlığı ve özetinden (-100..+100) skor, aciliyet ve etiket üretir."""
    combined = f"{title} {summary}".lower()
    score = 0.0
    urgent = False
    tags: list[str] = []
    for pattern, weight, tag in _POSITIVE_RULES:
        if re.search(pattern, combined):
            score += weight
            if tag not in tags:
                tags.append(tag)
    for pattern, weight, is_urgent, tag in _NEGATIVE_RULES:
        if re.search(pattern, combined):
            score += weight
            urgent = urgent or is_urgent
            if tag not in tags:
                tags.append(tag)
    score = round(max(-100.0, min(100.0, score)), 1)
    return score, urgent, tags


@dataclass
class NewsItem:
    ts: float
    title: str
    source: str
    url: str
    score: float
    urgent: bool = False
    tags: list[str] = field(default_factory=list)
    fear_greed: float = 50.0
    ai_enriched: bool = False


class NewsEngine:
    """RSS ve CryptoPanic kaynaklarından haber toplayıp zaman-ağırlıklı duygu üretir."""

    def __init__(
        self,
        sources: list[str],
        poll_sec: float = 60.0,
        cryptopanic_key: str = "",
        *,
        fear_greed_on: bool = True,
        fear_veto_low: float = 15.0,
        greed_long_veto_high: float = 85.0,
        llm_url: str = "",
        llm_key: str = "",
        llm_model: str = "gpt-4o-mini",
        active_window_sec: float = 3600.0,
    ):
        self.sources = list(sources or [])
        self.poll_sec = max(5.0, float(poll_sec))
        self.cryptopanic_key = (cryptopanic_key or "").strip()
        if self.cryptopanic_key:
            register_secret(self.cryptopanic_key)
        self.fear_greed_on = bool(fear_greed_on)
        self.fear_veto_low = float(fear_veto_low)
        self.greed_long_veto_high = float(greed_long_veto_high)
        self.active_window_sec = float(active_window_sec)
        self.fg = FearGreedAnalyzer(llm_url=llm_url, llm_key=llm_key, llm_model=llm_model)
        self.items: deque[NewsItem] = deque(maxlen=200)
        self._seen: set[str] = set()
        self._veto_until: float = 0.0
        self._running = False

    def _register(
        self,
        title: str,
        source: str,
        url: str,
        score: float,
        urgent: bool,
        tags: list,
        published_ts: float | None = None,
    ) -> NewsItem:
        clean_title = sanitize_external_text(title, max_len=350)
        clean_source = sanitize_external_text(source, max_len=80)
        clean_url = sanitize_url(url)
        fg = self.fg.score_sync(clean_title) if self.fear_greed_on else 50.0
        if urgent:
            fg = min(fg, 8.0)
        now = time.time()
        event_ts = float(published_ts) if published_ts is not None else now
        # Gelecekten gelen bozuk tarihlerin haberi süresiz taze göstermesini önle.
        event_ts = min(event_ts, now)
        item = NewsItem(
            event_ts,
            clean_title,
            clean_source,
            clean_url,
            float(score),
            bool(urgent),
            list(tags),
            fg,
            False,
        )
        self.items.append(item)
        if urgent and event_ts + 30 * 60 > now:
            self._veto_until = max(self._veto_until, event_ts + 30 * 60)
        elif self.fear_greed_on and fg < self.fear_veto_low and event_ts + 15 * 60 > now:
            self._veto_until = max(self._veto_until, event_ts + 15 * 60)
        return item

    def push_item(self, title: str, source: str, url: str = "") -> NewsItem:
        score, urgent, tags = score_text(title, "")
        return self._register(title, source, url, score, urgent, tags)

    async def _poll_rss(self, feed_url: str) -> None:
        try:
            import aiohttp
            import feedparser

            async with aiohttp.ClientSession() as session:
                async with session.get(feed_url, timeout=12) as resp:
                    if resp.status != 200:
                        return
                    raw_xml = await resp.text(errors="replace")
            parsed = feedparser.parse(raw_xml)
            for e in parsed.entries[:25]:
                title = getattr(e, "title", "") or ""
                link = getattr(e, "link", "") or ""
                dedup = f"{title}:{link}"
                if not title or dedup in self._seen:
                    continue
                self._seen.add(dedup)
                raw_summary = getattr(e, "summary", "") or getattr(e, "description", "")
                summary = sanitize_external_text(raw_summary, max_len=500)
                score, urgent, tags = score_text(title, summary)
                published = getattr(e, "published_parsed", None) or getattr(
                    e, "updated_parsed", None
                )
                published_ts = calendar.timegm(published) if published else time.time()
                self._register(
                    title,
                    parsed.feed.get("title", feed_url),
                    sanitize_url(link),
                    score,
                    urgent,
                    tags,
                    published_ts=published_ts,
                )
        except Exception:
            pass

    async def _poll_cryptopanic(self) -> None:
        if not self.cryptopanic_key:
            return
        try:
            import aiohttp

            url = (
                "https://cryptopanic.com/api/v1/posts/"
                f"?auth_token={self.cryptopanic_key}&public=true"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=12) as resp:
                    if resp.status != 200:
                        return
                    payload = await resp.json(content_type=None)
            for p in payload.get("results", [])[:25]:
                title = p.get("title", "")
                dedup = f"cp:{p.get('id') or title}"
                if not title or dedup in self._seen:
                    continue
                self._seen.add(dedup)
                score, urgent, tags = score_text(title, "")
                votes = p.get("votes") or {}
                try:
                    net = int(votes.get("positive", 0)) - int(votes.get("negative", 0))
                    score = max(-95, min(95, score + net * 5))
                except Exception:
                    pass
                published_ts = time.time()
                try:
                    published_ts = datetime.fromisoformat(
                        str(p.get("published_at", "")).replace("Z", "+00:00")
                    ).timestamp()
                except (ValueError, TypeError):
                    pass
                self._register(
                    title,
                    "CryptoPanic",
                    sanitize_url(p.get("url", "")),
                    score,
                    urgent,
                    tags,
                    published_ts=published_ts,
                )
        except Exception:
            pass

    def mood(self) -> dict:
        now = time.time()
        fresh = [it for it in self.items if now - it.ts <= self.active_window_sec]
        if not fresh:
            latest_item = self.items[-1] if self.items else None
            return {
                "score": 0.0,
                "fear_greed": 50.0,
                "veto": now < self._veto_until,
                "veto_approaching": False,
                "long_veto": False,
                "count": 0,
                "latest": (
                    {
                        "title": latest_item.title,
                        "source": latest_item.source,
                        "score": latest_item.score,
                        "ts": latest_item.ts,
                    }
                    if latest_item
                    else None
                ),
            }
        w_sum = 0.0
        sc_sum = 0.0
        fg_sum = 0.0
        for it in fresh:
            age = max(0.0, now - it.ts)
            weight = max(0.15, 1.0 - age / max(1.0, self.active_window_sec))
            w_sum += weight
            sc_sum += it.score * weight
            fg_sum += it.fear_greed * weight
        avg_score = round(sc_sum / w_sum, 1) if w_sum > 0 else 0.0
        avg_fg = round(fg_sum / w_sum, 1) if w_sum > 0 else 50.0
        veto = (now < self._veto_until) or avg_score <= -70.0
        veto_approaching = (not veto) and (
            avg_score <= -40.0 or (self.fear_greed_on and avg_fg <= self.fear_veto_low + 8.0)
        )
        long_veto = bool(self.fear_greed_on and avg_fg >= self.greed_long_veto_high)
        latest_item = fresh[-1]
        return {
            "score": avg_score,
            "fear_greed": avg_fg,
            "veto": veto,
            "veto_approaching": veto_approaching,
            "long_veto": long_veto,
            "count": len(fresh),
            "latest": {
                "title": latest_item.title,
                "source": latest_item.source,
                "score": latest_item.score,
                "ts": latest_item.ts,
            },
        }

    async def poll_once(self) -> None:
        tasks = [self._poll_rss(url) for url in self.sources]
        if self.cryptopanic_key:
            tasks.append(self._poll_cryptopanic())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            await self.poll_once()
            await asyncio.sleep(self.poll_sec)

    def stop(self) -> None:
        self._running = False
