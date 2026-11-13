"""Anlık kripto haber motoru — RSS + CryptoPanic + korku/açgözlülük psikolojisi
+ Girdi Doğrulama (Input Sanitization) ve Gizli Anahtar Maskeleme.

  - CoinDesk, Cointelegraph, Decrypt, Bitcoin Magazine RSS akışları (anahtarsız)
  - CryptoPanic API (ücretsiz anahtarla daha hızlı + oylu haberler)
  - GİRDİ DOĞRULAMA: Dışarıdan gelen tüm başlık/özet/URL verileri
    `sanitize_external_text` ve `sanitize_url` ile HTML/script/SQL/prompt
    enjeksiyonlarından temizlendikten sonra işlenir.
  - Etki sözlüğü (Türkçe + İngilizce): hack, ETF onayı, listeleme, SEC davası...
  - KORKU/AÇGÖZLÜLÜK skoru (0..100): yerel yapay zekâ motoru + opsiyonel LLM API
  - VETO katmanları:
      • KRİTİK olay (hack/iflas/delist...) → TÜM yeni işlemler 30 dk durur
      • Aşırı KORKU (panik, skor<15)     → TÜM yeni işlemler 15 dk durur
      • Aşırı AÇGÖZLÜLÜK (skor>85)       → yeni LONG'lar durur (zirve kovalanmaz)
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass, field

from .security import sanitize_external_text, sanitize_url
from .sentiment_ai import FearGreedEngine

URGENT_NEGATIVE = [
    "hack", "hacked", "exploit", "stolen", "çalındı", "saldırı", "attack",
    "sec dava", "sec lawsuit", "lawsuit", "dava açıldı", "delist", "delisted",
    "listeden çıkar", "bankrupt", "iflas", "insolvent", "rug pull", "rugpull",
    "freeze withdrawal", "çekimleri durdur", "yasak", "banned", "ban ",
    "ceza", "fine", "milyar dolarlık ceza", "çöküş", "collapse", "depeg",
    "sabitliğini kaybetti", "dolandırıcılık", "fraud", "scam", "ponzi",
    "tutuklandı", "arrested", "soruşturma", "investigation", "kapatıldı", "shutdown",
]

POSITIVE_STRONG = [
    "etf onay", "etf approval", "etf approved", "onaylandı", "approved",
    "listeleme", "listing", "listed on", "listelendi", "coinbase list",
    "binance list", "ortaklık", "partnership", "partnered",
    "yakım", "burn", "burned", "kurumsal alım", "institutional",
    "benimseme", "adoption", "rekor", "record", "all-time high", "ath",
    "artış", "surge", "rally", "ralli", "yükseliş", "boğa", "bullish",
    "faiz indirimi", "rate cut", "teşvik", "stimulus",
]

NEGATIVE = [
    "düşüş", "drop", "dump", "plunge", "crash", "ayı", "bearish",
    "satış baskısı", "selling pressure", "korku", "fear", "panik", "panic",
    "çıkış", "outflow", "geri çekilme", "pullback", "düzeltme", "correction",
    "faiz artırımı", "rate hike", "şahin", "hawkish", "riskten kaçış",
]

POSITIVE_MILD = [
    "büyüme", "growth", "genişleme", "expansion", "lansman", "launch",
    "mainnet", "upgrade", "yükseltme", "güncelleme", "destek", "support",
    "entegrasyon", "integration", "fon topladı", "raised", "funding round",
]


@dataclass
class NewsItem:
    ts: float
    title: str
    source: str
    url: str
    score: float
    urgent: bool
    tags: list = field(default_factory=list)
    fear_greed: float = 50.0
    fg_source: str = "yerel"
    llm_done: bool = False


def score_text(title: str, body: str = "") -> tuple[float, bool, list]:
    """Başlık + özet metnini önce sanitize eder, ardından skorlar."""
    clean_title = sanitize_external_text(title, max_len=400)
    clean_body = sanitize_external_text(body, max_len=600)
    text = f"{clean_title} {clean_body}".lower()
    tags: list[str] = []

    for kw in URGENT_NEGATIVE:
        if kw in text:
            tags.append(f"KRİTİK:{kw}")
            return -90.0, True, tags

    score = 0.0
    for kw in POSITIVE_STRONG:
        if kw in text:
            score += 30
            tags.append(f"+{kw}")
    for kw in POSITIVE_MILD:
        if kw in text:
            score += 10
            tags.append(f"+{kw}")
    for kw in NEGATIVE:
        if kw in text:
            score -= 15
            tags.append(f"-{kw}")

    if re.search(r"\$\s?\d{2,}", text) and score > 0:
        score += 10
    score = max(-80.0, min(80.0, score))
    return score, False, tags


class NewsEngine:
    def __init__(
        self,
        feeds: list[str],
        poll_sec: int = 30,
        cryptopanic_key: str = "",
        history_max: int = 200,
        fear_greed_on: bool = True,
        fear_veto_low: float = 15.0,
        greed_long_veto_high: float = 85.0,
        llm_url: str = "",
        llm_key: str = "",
        llm_model: str = "",
    ):
        self.feeds = feeds
        self.poll_sec = poll_sec
        self.cp_key = cryptopanic_key
        self.items: deque[NewsItem] = deque(maxlen=history_max)
        self._seen: set[str] = set()
        self._veto_until = 0.0
        self._running = False
        self.fear_greed_on = fear_greed_on
        self.fear_veto_low = fear_veto_low
        self.greed_long_veto_high = greed_long_veto_high
        self.fg = FearGreedEngine(llm_url, llm_key, llm_model)

    def _weighted_fg(self, now: float) -> float:
        if not self.fear_greed_on or not self.items:
            return 50.0
        weighted, wsum = 0.0, 0.0
        for it in self.items:
            age_min = (now - it.ts) / 60
            if age_min > 120:
                continue
            w = 1.0 / (1.0 + age_min / 15.0)
            weighted += it.fear_greed * w
            wsum += w
        return weighted / wsum if wsum else 50.0

    def mood(self) -> dict:
        """Piyasa haber ruhu: skor + korku/açgözlülük + veto katmanları."""
        now = time.time()
        fg = round(self._weighted_fg(now), 1)
        if not self.items:
            return {
                "score": 0.0,
                "veto": False,
                "veto_long": False,
                "veto_short": False,
                "veto_approaching": False,
                "fear_greed": fg,
                "count": 0,
                "latest": None,
            }
        weighted, wsum = 0.0, 0.0
        for it in self.items:
            age_min = (now - it.ts) / 60
            if age_min > 120:
                continue
            w = 1.0 / (1.0 + age_min / 15.0)
            weighted += it.score * w
            wsum += w
        score = weighted / wsum if wsum else 0.0

        if self.fear_greed_on and fg < self.fear_veto_low:
            self._veto_until = max(self._veto_until, now + 15 * 60)
        veto = now < self._veto_until
        veto_long = veto or (self.fear_greed_on and fg > self.greed_long_veto_high)
        # Veto yaklaşımı: panik sınırına yakın (fg < 24) veya sert negatif haber akışı (score <= -35)
        veto_approaching = (
            veto
            or (self.fear_greed_on and (fg <= self.fear_veto_low + 8 or fg >= self.greed_long_veto_high - 5))
            or score <= -35.0
        )

        latest = self.items[-1]
        return {
            "score": round(score, 1),
            "veto": veto,
            "veto_long": veto_long,
            "veto_short": veto,
            "veto_approaching": veto_approaching,
            "fear_greed": fg,
            "count": len(self.items),
            "latest": {
                "title": latest.title,
                "source": latest.source,
                "score": latest.score,
                "urgent": latest.urgent,
                "fear_greed": latest.fear_greed,
            },
        }

    def _register(
        self,
        title: str,
        source: str,
        url: str,
        score: float,
        urgent: bool,
        tags: list,
    ) -> NewsItem:
        clean_title = sanitize_external_text(title, max_len=350)
        clean_source = sanitize_external_text(source, max_len=80)
        clean_url = sanitize_url(url)
        fg = self.fg.score_sync(clean_title) if self.fear_greed_on else 50.0
        if urgent:
            fg = min(fg, 8.0)
        item = NewsItem(
            time.time(),
            clean_title,
            clean_source,
            clean_url,
            score,
            urgent,
            tags,
            fg,
            "yerel",
            False,
        )
        self.items.append(item)
        if urgent:
            self._veto_until = time.time() + 30 * 60
        elif self.fear_greed_on and fg < self.fear_veto_low:
            self._veto_until = time.time() + 15 * 60
        return item

    def push_item(self, title: str, source: str, url: str = "") -> NewsItem:
        clean_title = sanitize_external_text(title, max_len=350)
        score, urgent, tags = score_text(clean_title)
        return self._register(clean_title, source, url, score, urgent, tags)

    async def _fetch_rss(self, session, feed_url: str):
        try:
            import feedparser

            async with session.get(feed_url, timeout=20) as resp:
                raw = await resp.text()
            parsed = feedparser.parse(raw)
            for e in parsed.entries[:15]:
                raw_title = getattr(e, "title", "")
                raw_link = getattr(e, "link", "")
                title = sanitize_external_text(raw_title, max_len=350)
                link = sanitize_url(raw_link)
                key = link or title
                if not title or key in self._seen:
                    continue
                self._seen.add(key)
                raw_summary = getattr(e, "summary", "") or getattr(e, "description", "")
                summary = sanitize_external_text(raw_summary, max_len=500)
                score, urgent, tags = score_text(title, summary)
                self._register(
                    title,
                    parsed.feed.get("title", feed_url),
                    link,
                    score,
                    urgent,
                    tags,
                )
        except Exception:
            pass

    async def _fetch_cryptopanic(self, session):
        if not self.cp_key:
            return
        try:
            url = (
                f"https://cryptopanic.com/api/v1/posts/?auth_token={self.cp_key}"
                f"&public=true&kind=news"
            )
            async with session.get(url, timeout=20) as resp:
                data = await resp.json()
            for p in data.get("results", [])[:20]:
                pid = str(p.get("id"))
                if pid in self._seen:
                    continue
                self._seen.add(pid)
                title = sanitize_external_text(p.get("title", ""), max_len=350)
                votes = p.get("votes", {})
                score, urgent, tags = score_text(title)
                try:
                    net = int(votes.get("positive", 0)) - int(votes.get("negative", 0))
                    score = max(-95, min(95, score + net * 5))
                except Exception:
                    pass
                self._register(
                    title, "CryptoPanic", sanitize_url(p.get("url", "")), score, urgent, tags
                )
        except Exception:
            pass

    async def _enrich_loop(self):
        """LLM zenginleştirmesi: arka planda, işlem hızını asla kesmez."""
        while self._running:
            try:
                if self.fg.llm.enabled:
                    pending = [
                        it
                        for it in list(self.items)[-12:]
                        if not it.llm_done and not it.urgent
                    ]
                    for it in pending[:4]:
                        val, src = await self.fg.ascore(sanitize_external_text(it.title))
                        it.fear_greed, it.fg_source, it.llm_done = val, src, True
            except Exception:
                pass
            await asyncio.sleep(20)

    async def run_forever(self):
        import aiohttp

        self._running = True
        enrich = asyncio.create_task(self._enrich_loop())
        try:
            async with aiohttp.ClientSession() as session:
                while self._running:
                    await asyncio.gather(
                        *(self._fetch_rss(session, f) for f in self.feeds),
                        self._fetch_cryptopanic(session),
                    )
                    await asyncio.sleep(self.poll_sec)
        finally:
            enrich.cancel()

    def stop(self):
        self._running = False
