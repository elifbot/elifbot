"""v4.0 — RSS haber ajanı: başlık taraması → yalnızca risk bayrağı (madde 19).

Ajan ASLA işlem AÇMAZ: "flag" modda yalnız log + rapor; "block" modda aktif
risk bayrağı YENİ GİRİŞİ engeller (opsiyonel; açık pozisyon yönetimi sürer).

Yöntem (dürüst):
  - RSS/XML başlıkları xml.etree ile ayrıştırılır (harici bağımlılık yok).
  - Pencere (vars. 45 dk) içindeki başlıklar anahtar kelime ağırlıklarıyla
    taranır; eşik (0.6) aşılırsa bayrak, bayrak TTL'i (vars. 90 dk) kadar
    yaşar.
  - Bu bir DUYARLILIK göstergesidir; doğal dil anlama değildir. Yanlış
    pozitifler olabilir → varsayılan mod "flag" (engellemez).
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import timezone
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
)

# (kalıp, ağırlık 0-1) — risk sözlüğü; pozitif haberler bayrak ÜRETMEZ
RISK_KEYWORDS: tuple[tuple[str, float], ...] = (
    (r"\bhack(?:ed|ing)?\b", 0.9),
    (r"\bexploit(?:ed|ing)?\b", 0.9),
    (r"\bbreach\b", 0.8),
    (r"\bban(?:s|ned|ning)?\b", 0.8),
    (r"\bdepeg(?:ged|ging)?\b", 0.8),
    (r"\blawsuit\b", 0.7),
    (r"\bsue[sd]?\b", 0.7),
    (r"\bcharges?\b", 0.7),
    (r"\binvestigat(?:ion|ing)\b", 0.6),
    (r"\boutage\b", 0.6),
    (r"\bfrozen?\b", 0.6),
    (r"\bwithdrawal (?:halt|pause)", 0.7),
    (r"\bliquidation(?:s)?\b", 0.6),
    (r"\bcrash(?:es|ed)?\b", 0.7),
    (r"\bemergency\b", 0.5),
)


def _default_fetcher(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (acarbot)"})
    with urlopen(request, timeout=10) as response:
        return response.read()


def parse_rss_titles(xml_bytes: bytes) -> list[tuple[str, int]]:
    """[(başlık, pubDate epoch ms)] — pubDate yoksa 0 (pencere dışı sayılır)."""
    titles: list[tuple[str, int]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return titles
    for item in root.iter():
        if not item.tag.rsplit("}", 1)[-1].lower().endswith("item"):
            continue
        title = pub = None
        for child in item:
            tag = child.tag.rsplit("}", 1)[-1].lower()
            if tag == "title" and child.text:
                title = child.text.strip()
            elif tag == "pubdate" and child.text:
                pub = child.text.strip()
        if title:
            ts_ms = 0
            if pub:
                try:
                    ts_ms = int(
                        parsedate_to_datetime(pub)
                        .astimezone(timezone.utc)
                        .timestamp() * 1000
                    )
                except (TypeError, ValueError):
                    ts_ms = 0
            titles.append((title, ts_ms))
    return titles


def risk_score(title: str) -> tuple[float, str]:
    """(en yüksek eşleşen ağırlık, eşleşen kalıp) — eşleşme yoksa (0.0, "")."""
    low = title.lower()
    best, pattern = 0.0, ""
    for regex, weight in RISK_KEYWORDS:
        if re.search(regex, low) and weight > best:
            best, pattern = weight, regex
    return best, pattern


class RssNewsAgent:
    """RSS başlık duyarlılığı — bilgi katmanı (işlem AÇMAZ)."""

    name = "rss_news"

    def __init__(
        self,
        mode: str = "flag",                        # "off" | "flag" | "block"
        feeds: tuple[str, ...] = DEFAULT_FEEDS,
        refresh_seconds: float = 600.0,
        window_minutes: float = 45.0,
        flag_ttl_minutes: float = 90.0,
        threshold: float = 0.6,
        fetcher=_default_fetcher,
        clock=None,
    ) -> None:
        self.mode = mode
        self.feeds = feeds
        self.refresh_seconds = max(float(refresh_seconds), 60.0)
        self.window_ms = window_minutes * 60_000.0
        self.flag_ttl_ms = flag_ttl_minutes * 60_000.0
        self.threshold = threshold
        self.fetcher = fetcher
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.flag_active: bool = False
        self.flag_reason: str = ""
        self.flag_until_ms: int = 0
        self._last_refresh_ms: int = 0
        self.blocks_count = 0
        self.last_titles: list[str] = []

    # -- Çalıştırma ----------------------------------------------------------

    def tick(self, now_ms: int | None = None) -> None:
        if self.mode == "off":
            return
        now_ms = int(now_ms if now_ms is not None else self.clock())
        if now_ms - self._last_refresh_ms < self.refresh_seconds * 1000:
            return
        self._last_refresh_ms = now_ms
        best_score, best_title = 0.0, ""
        titles: list[str] = []
        for feed in self.feeds:
            try:
                rows = parse_rss_titles(self.fetcher(feed))
            except Exception as exc:  # noqa: BLE001 — tek feed hatası ölümcül değil
                logger.debug("RSS okunamadı (%s): %s", feed, exc)
                continue
            for title, ts_ms in rows:
                titles.append(title)
                if not ts_ms or now_ms - ts_ms > self.window_ms:
                    continue  # pubDate yok veya pencere dışı
                score, pattern = risk_score(title)
                if score >= self.threshold and score > best_score:
                    best_score, best_title = score, f"{title} [{pattern}]"
        self.last_titles = titles[:20]
        if best_score >= self.threshold:
            self.flag_active = True
            self.flag_reason = best_title
            self.flag_until_ms = now_ms + int(self.flag_ttl_ms)
            logger.warning(
                "HABER AJANI RİSK BAYRAĞI: %s (ağırlık %.1f, %d dk geçerli)",
                best_title, best_score, int(self.flag_ttl_ms / 60_000),
            )

    def _expire(self, now_ms: int) -> None:
        if self.flag_active and now_ms > self.flag_until_ms:
            self.flag_active = False
            self.flag_reason = ""

    # -- Kapı + rapor ----------------------------------------------------------

    def entry_block(self, now_ms: int) -> str | None:
        self._expire(now_ms)
        if self.mode != "block" or not self.flag_active:
            return None
        self.blocks_count += 1
        return f"haber ajanı risk bayrağı: {self.flag_reason}"

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "flag_active": self.flag_active,
            "flag_reason": self.flag_reason,
            "flag_until_ms": self.flag_until_ms,
            "feeds": list(self.feeds),
            "blocks_count": self.blocks_count,
        }
