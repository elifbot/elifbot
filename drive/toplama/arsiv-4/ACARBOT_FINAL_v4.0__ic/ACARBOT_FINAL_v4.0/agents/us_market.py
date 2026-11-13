"""v4.0 — ABD piyasası ajanı: SPX / Nasdaq / DXY / VIX → risk-on/off (madde 18).

Veri kaynağı: Yahoo Finance chart API (anahtar gerektirmez, yalnız okur).
  ^GSPC (S&P 500), ^IXIC (Nasdaq), DX-Y.NYB (Dollar Index), ^VIX (Volatilite)

Kurallar (deterministik, şeffaf):
  risk_off : VIX ≥ 25  VEYA  (SPX günlük ≤ -%1.5 VE Nasdaq ≤ -%2.0)
  risk_on  : VIX ≤ 18 VE SPX günlük ≥ 0
  neutral  : aradaki her durum

Ajan ASLA işlem açmaz: "flag" modda bayrak loglanır/raporlanır; "block"
modda risk_off bayrağı taze iken YENİ GİRİŞ engellenir (açık pozisyonların
stopları her koşulda çalışır). Veri alınamazsa bayrak "unavailable" olur ve
fail-open ilerler (yanlış veriyle engel yapılmaz).
"""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

SYMBOLS = {"spx": "^GSPC", "nasdaq": "^IXIC", "dxy": "DX-Y.NYB", "vix": "^VIX"}


def _default_fetcher(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (acarbot)"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _yahoo_daily(url_symbol: str, fetcher) -> tuple[float, float] | None:
    """(son kapanış, önceki kapanış) — 1 günlük mumlardan. Hata → None."""
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(url_symbol)}?range=5d&interval=1d"
    )
    payload = fetcher(url)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    closes = ((result[0] or {}).get("indicators") or {}).get("quote") or [{}]
    raw = closes[0].get("close") or []
    clean = [float(c) for c in raw if c is not None]
    if len(clean) < 2:
        return None
    return clean[-1], clean[-2]


class USMarketAgent:
    """SPX/Nasdaq/DXY/VIX risk-on/off filtresi (bilgi katmanı)."""

    name = "us_market"

    def __init__(
        self,
        mode: str = "flag",                       # "off" | "flag" | "block"
        refresh_seconds: float = 600.0,
        fetcher=_default_fetcher,
        clock=None,
    ) -> None:
        self.mode = mode
        self.refresh_seconds = max(float(refresh_seconds), 60.0)
        self.fetcher = fetcher
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.flag: str = "unavailable"            # risk_on|risk_off|neutral|unavailable
        self.reason: str = "henüz veri yok"
        self.details: dict[str, float] = {}
        self._last_refresh_ms: int = 0
        self.blocks_count = 0

    # -- Çalıştırma ----------------------------------------------------------

    def tick(self, now_ms: int | None = None) -> None:
        """Bayrağı tazeler (guards_refresher'dan periyodik çağrılır)."""
        if self.mode == "off":
            return
        now_ms = int(now_ms if now_ms is not None else self.clock())
        if now_ms - self._last_refresh_ms < self.refresh_seconds * 1000:
            return
        self._last_refresh_ms = now_ms
        try:
            spx = _yahoo_daily(SYMBOLS["spx"], self.fetcher)
            nq = _yahoo_daily(SYMBOLS["nasdaq"], self.fetcher)
            vix = _yahoo_daily(SYMBOLS["vix"], self.fetcher)
            dxy = _yahoo_daily(SYMBOLS["dxy"], self.fetcher)
        except Exception as exc:  # noqa: BLE001 — veri hatası fail-open
            self.flag = "unavailable"
            self.reason = f"veri alınamadı: {exc}"
            logger.warning("ABD piyasası ajanı: %s", self.reason)
            return
        if not (spx and nq and vix and dxy):
            self.flag = "unavailable"
            self.reason = "eksik seri (en az 2 günlük kapanış gerekli)"
            return
        spx_ret = spx[0] / spx[1] - 1.0
        nq_ret = nq[0] / nq[1] - 1.0
        dxy_ret = dxy[0] / dxy[1] - 1.0
        vix_level = vix[0]
        self.details = {
            "spx_ret_1d_pct": round(spx_ret * 100.0, 2),
            "nasdaq_ret_1d_pct": round(nq_ret * 100.0, 2),
            "dxy_ret_1d_pct": round(dxy_ret * 100.0, 2),
            "vix": round(vix_level, 2),
        }
        if vix_level >= 25.0 or (spx_ret <= -0.015 and nq_ret <= -0.02):
            self.flag = "risk_off"
            self.reason = (
                f"VIX {vix_level:.1f} | SPX {spx_ret*100:+.2f}% | "
                f"NDX {nq_ret*100:+.2f}%"
            )
        elif vix_level <= 18.0 and spx_ret >= 0.0:
            self.flag = "risk_on"
            self.reason = (
                f"VIX {vix_level:.1f} | SPX {spx_ret*100:+.2f}%"
            )
        else:
            self.flag = "neutral"
            self.reason = (
                f"VIX {vix_level:.1f} | SPX {spx_ret*100:+.2f}% | "
                f"DXY {dxy_ret*100:+.2f}%"
            )
        logger.info("ABD PİYASASI: %s (%s)", self.flag, self.reason)

    # -- Kapı + rapor ----------------------------------------------------------

    def entry_block(self, now_ms: int) -> str | None:
        """'block' modda taze risk_off bayrağı yeni girişi engeller."""
        if self.mode != "block" or self.flag != "risk_off":
            return None
        fresh_s = self.refresh_seconds * 2.0 / 1000.0 * 1000.0  # 2 tazeleme döngüsü
        if now_ms - self._last_refresh_ms > fresh_s:
            return None  # bayat bayrak → fail-open
        self.blocks_count += 1
        return f"ABD piyasası ajanı: risk_off ({self.reason})"

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "flag": self.flag,
            "reason": self.reason,
            "details": dict(self.details),
            "blocks_count": self.blocks_count,
        }
