"""Makro haber koruması — FINAL v1.1.

ultra_plus'taki 13 satırlık taslağın (her zaman False döndüren hook) gerçek
implementasyonu. Forex Factory haftalık ekonomik takvimini çeker; yüksek
etkili USD olaylarının (FOMC, CPI, NFP, işsizlik...) ±buffer_minutes
penceresinde YENİ GİRİŞİ engeller. Açık pozisyonların stop/çıkış yönetimi
etkilenmez — koruma yalnızca giriş kapısıdır.

Davranış:
  - Veri kaynağı: FF haftalık JSON (anahtarsız, ücretsiz) + isteğe bağlı
    yerel olay dosyası (aynı formatta manuel olaylar).
  - Önbellek: refresh_seconds'ten sık ağ isteği yapılmaz.
  - Hata durumunda: eski veri kullanılır; hiç veri yoksa fail-open
    (fail_closed=True ise girişler engellenir).
  - Ağ çağrısı senkrondur; asyncio.to_thread ile çağrılmalıdır.
"""

from __future__ import annotations

import json
import time
import logging
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.config import NewsGuardConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MacroEvent:
    title: str
    country: str
    impact: str
    start_ms: int
    end_ms: int


def parse_calendar_events(
    rows: list, buffer_minutes: float,
    currencies: tuple[str, ...], impacts: tuple[str, ...],
) -> list[MacroEvent]:
    """FF takvim satırlarını MacroEvent listesine çevirir (bozuk satır atlanır)."""
    events: list[MacroEvent] = []
    buffer_ms = int(buffer_minutes * 60_000)
    currencies_up = {c.upper() for c in currencies}
    impacts_up = {i.upper() for i in impacts}
    for row in rows:
        if not isinstance(row, dict):
            continue
        country = str(row.get("country", "")).upper()
        impact = str(row.get("impact", "")).upper()
        if country not in currencies_up or impact not in impacts_up:
            continue
        raw_date = row.get("date")
        if not isinstance(raw_date, str) or not raw_date:
            continue
        try:
            dt = datetime.fromisoformat(raw_date)
        except ValueError:
            continue
        if dt.tzinfo is None:
            continue  # saat dilimsiz olay güvenilmez
        event_ms = int(dt.timestamp() * 1000)
        events.append(MacroEvent(
            title=str(row.get("title", "?")),
            country=country,
            impact=impact,
            start_ms=event_ms - buffer_ms,
            end_ms=event_ms + buffer_ms,
        ))
    return events


class NewsGuard:
    """Ekonomik takvim tabanlı giriş kapısı."""

    def __init__(self, config: NewsGuardConfig, fetch_json=None) -> None:
        self.config = config
        self._fetch_json = fetch_json or self._http_fetch_json
        self._events: list[MacroEvent] = []
        self._last_refresh_ms: int = 0
        self._last_success_ms: int = 0
        self._refresh_attempts = 0
        self._refresh_failures = 0
        self.blocks_count = 0

    # ------------------------------------------------------------------
    # Veri çekme
    # ------------------------------------------------------------------

    def _http_fetch_json(self, url: str):
        request = urllib.request.Request(
            url, headers={"User-Agent": "ACARBOT-FINAL/1.1 (paper bot)"},
        )
        with urllib.request.urlopen(
            request, timeout=self.config.fetch_timeout_seconds,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def refresh(self, now_ms: int) -> bool:
        """Takvimi tazele. True = yeni veri yüklendi."""
        refresh_ms = int(self.config.refresh_seconds * 1000)
        if self._last_refresh_ms and now_ms - self._last_refresh_ms < refresh_ms:
            return False
        self._last_refresh_ms = now_ms
        self._refresh_attempts += 1
        rows: list = []
        ok = False
        try:
            remote = self._fetch_json(self.config.calendar_url)
            if isinstance(remote, list):
                rows.extend(remote)
                ok = True
            else:
                logger.warning("Haber takvimi beklenmeyen biçim (liste değil)")
        except Exception as exc:  # noqa: BLE001
            self._refresh_failures += 1
            logger.warning("Haber takvimi alınamadı (eski veriyle devam): %s", exc)
        if self.config.local_events_file:
            try:
                local = json.loads(
                    Path(self.config.local_events_file).read_text(encoding="utf-8")
                )
                if isinstance(local, list):
                    rows.extend(local)
                    ok = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Yerel haber dosyası okunamadı: %s", exc)
        if ok:
            self._events = parse_calendar_events(
                rows, self.config.buffer_minutes,
                self.config.currencies, self.config.impacts,
            )
            self._last_success_ms = now_ms
            logger.info(
                "Haber koruması: %d olay yüklendi (±%.0f dk, %s/%s)",
                len(self._events), self.config.buffer_minutes,
                ",".join(self.config.currencies), ",".join(self.config.impacts),
            )
        return ok

    # ------------------------------------------------------------------
    # Karar
    # ------------------------------------------------------------------

    def blackout(self, now_ms: int) -> tuple[bool, str]:
        """(engellendi_mi, neden) döndürür."""
        if not self._events:
            if self.config.fail_closed and not self._last_success_ms:
                self.blocks_count += 1
                return True, "NEWS_GUARD_NO_DATA"
            return False, ""
        for event in self._events:
            if event.start_ms <= now_ms <= event.end_ms:
                self.blocks_count += 1
                return True, (
                    f"NEWS_GUARD:{event.country}:{event.title}"
                    f"@{datetime.fromtimestamp((event.start_ms + event.end_ms) / 2000, tz=timezone.utc).strftime('%H:%M')}UTC"
                )
        return False, ""

    def health(self, now_ms: int | None = None) -> tuple[bool, str]:
        """(zayıf_mı, neden). Koruma sessizce zayıfladıysa panelde görünür.

        Zayıf sayılır: hiç başarılı yükleme yok VEYA son başarı, tazeleme
        aralığının 3 katından eski. `fail_closed` kapalıyken bu durumda
        girişler ENGELLENMEZ (fail-open) — operatör bunu görmelidir.
        """
        if not self.config.enabled:
            return False, ""
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        if not self._last_success_ms:
            if self._refresh_attempts == 0:
                return False, ""
            mode = "girişler ENGELLENİR" if self.config.fail_closed else (
                "FAIL-OPEN: koruma fiilen KAPALI"
            )
            return True, f"takvim hiç yüklenemedi — {mode}"
        age_ms = now_ms - self._last_success_ms
        limit_ms = int(self.config.refresh_seconds * 1000) * 3
        if age_ms > limit_ms:
            return True, f"takvim {age_ms / 60000:.0f} dk bayat (eski veriyle devam)"
        return False, ""

    def status(self) -> dict:
        degraded, reason = self.health()
        return {
            "degraded": degraded,
            "degraded_reason": reason,
            "enabled": self.config.enabled,
            "events_loaded": len(self._events),
            "last_success_ms": self._last_success_ms,
            "refresh_attempts": self._refresh_attempts,
            "refresh_failures": self._refresh_failures,
            "blocks_count": self.blocks_count,
            "buffer_minutes": self.config.buffer_minutes,
            "fail_closed": self.config.fail_closed,
        }
