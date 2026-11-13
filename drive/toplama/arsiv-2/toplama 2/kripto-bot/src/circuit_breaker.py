"""Circuit Breaker (Acil Durum Sigortası) — Paranın ve hesabın güvenliğini koruyan ana sigorta.

Tetikleme Koşulları (Herhangi biri gerçekleşirse bot ACİL DURDURULUR / Emergency Kill-Switch):
  1) Ard arda 3 KİMLİK DOĞRULAMA veya YETKİ HATASI (401/403, Invalid API-Key, Signature, Permission)
     alınırsa → `Emergency Kill-Switch` devreye girer ve sistem kilitlenir (`system_locked = True`).
  2) Ard arda 3 emir hatası alınırsa (`max_consecutive_errors = 3`)
  3) Günlük zarar %5'i geçerse (`daily_max_loss_pct = 5.0`)
  4) Borsa WebSocket bağlantısı 10 saniyeden uzun süre koparsa (`max_ws_disconnect_sec = 10.0`)
  5) Ani Flash Crash (ör. saniyeler içinde >%8 çöküş) veya Manuel/Telegram Kill-Switch komutu
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .security import is_auth_or_permission_error, mask_secrets


class CircuitBreaker:
    def __init__(
        self,
        max_consecutive_errors: int = 3,
        daily_max_loss_pct: float = 5.0,
        max_ws_disconnect_sec: float = 10.0,
        flash_crash_pct: float = 8.0,
        max_consecutive_auth_errors: int = 3,
        state_store=None,
    ):
        self.max_consecutive_errors = max_consecutive_errors
        self.daily_max_loss_pct = daily_max_loss_pct
        self.max_ws_disconnect_sec = max_ws_disconnect_sec
        self.flash_crash_pct = flash_crash_pct
        self.max_consecutive_auth_errors = max_consecutive_auth_errors
        self.state_store = state_store

        self.consecutive_errors: int = 0
        self.consecutive_auth_errors: int = 0
        self.last_error_msg: str = ""
        self.daily_pnl_pct: float = 0.0
        self._day = datetime.now(timezone.utc).date()

        self.last_ws_ts: float = time.time()
        self.ws_monitoring_active: bool = False

        self.tripped: bool = False
        self.system_locked: bool = False
        self.trip_reason: str = ""
        self.tripped_at: float = 0.0
        self.paused: bool = False
        self._recent_prices: dict[str, tuple[float, float]] = {}

        self._sync_store()

    def _reset_day_if_needed(self):
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.daily_pnl_pct = 0.0

    def _sync_store(self):
        if self.state_store is not None:
            try:
                self.state_store.set_meta("circuit_breaker", self.snapshot())
            except Exception:
                pass

    def trip(self, reason: str, lock_system: bool = False) -> dict:
        """Sigortayı attırır (Emergency Kill-Switch aktif olur)."""
        safe_reason = mask_secrets(reason)
        if not self.tripped:
            self.tripped = True
            self.trip_reason = safe_reason
            self.tripped_at = time.time()
        if lock_system:
            self.system_locked = True
            self.trip_reason = safe_reason
        self._sync_store()
        return self.snapshot()

    def reset(self, force_unlock: bool = True):
        """Sigortayı sıfırlar ve botun tekrar çalışmasına izin verir."""
        if self.system_locked and not force_unlock:
            return
        self.tripped = False
        self.system_locked = False
        self.trip_reason = ""
        self.tripped_at = 0.0
        self.consecutive_errors = 0
        self.consecutive_auth_errors = 0
        self.last_error_msg = ""
        self.paused = False
        self.last_ws_ts = time.time()
        self._sync_store()

    def set_paused(self, paused: bool):
        self.paused = bool(paused)
        self._sync_store()

    # -- 1) Kimlik Doğrulama & Yetki Hatası Sigortası (3 Hata → Sistem Kilidi) --
    def record_auth_error(self, error: object = "") -> bool:
        """Borsa API kimlik doğrulama/yetki hatasını kaydeder (anahtarlar maskelenir).
        Ard arda 3 yetki hatasında Emergency Kill-Switch + Sistem Kilidi devreye girer."""
        clean_err = mask_secrets(error)
        self.consecutive_auth_errors += 1
        self.consecutive_errors += 1
        self.last_error_msg = clean_err[:120]
        if self.consecutive_auth_errors >= self.max_consecutive_auth_errors:
            self.trip(
                f"EMERGENCY KILL-SWITCH: ARD ARDA {self.consecutive_auth_errors} "
                f"KİMLİK DOĞRULAMA / YETKİ HATASI ({self.last_error_msg[:80]})",
                lock_system=True,
            )
            return True
        self._sync_store()
        return False

    # -- 2) Emir Hataları Denetimi ---------------------------------------------
    def record_order_error(self, error_msg: object = "") -> bool:
        """Emir hatası kaydeder. Yetki hatasıysa auth sayacını da artırır.
        Ard arda 3 hata olursa True (sigorta attı) döner."""
        if is_auth_or_permission_error(error_msg):
            return self.record_auth_error(error_msg)

        clean_err = mask_secrets(error_msg)
        self.consecutive_errors += 1
        self.last_error_msg = clean_err[:120]
        if self.consecutive_errors >= self.max_consecutive_errors:
            self.trip(
                f"ARD ARDA {self.consecutive_errors} EMİR HATASI "
                f"(son hata: {self.last_error_msg[:80]})"
            )
            return True
        self._sync_store()
        return False

    def record_order_success(self):
        """Başarılı emirde ardışık hata sayaçlarını sıfırlar."""
        if self.consecutive_errors > 0 or self.consecutive_auth_errors > 0:
            self.consecutive_errors = 0
            self.consecutive_auth_errors = 0
            self._sync_store()

    # -- 3) Günlük Zarar %5 Denetimi -------------------------------------------
    def record_trade_pnl(self, pnl_pct: float) -> bool:
        """Kapanan işlemin PnL yüzdesini işler. Günlük zarar %5'i geçerse sigorta atar."""
        self._reset_day_if_needed()
        self.daily_pnl_pct += float(pnl_pct)
        if self.daily_pnl_pct <= -self.daily_max_loss_pct:
            self.trip(
                f"GÜNLÜK ZARAR LİMİTİ AŞILDI: %{self.daily_pnl_pct:.2f} "
                f"(limit: -%{self.daily_max_loss_pct:.2f})"
            )
            return True
        self._sync_store()
        return False

    # -- 4) WebSocket 10 Saniye Kopma Denetimi ---------------------------------
    def heartbeat_ws(self, ts: float | None = None):
        """Her WebSocket mesajında veya pong yanıtında çağrılır."""
        self.ws_monitoring_active = True
        self.last_ws_ts = ts if ts is not None else time.time()

    def check_ws_health(self, now: float | None = None) -> bool:
        """WS bağlantısı 10 sn'den uzun süredir sessizse sigortayı attırır."""
        if not self.ws_monitoring_active:
            return False
        now = now if now is not None else time.time()
        gap = now - self.last_ws_ts
        if gap > self.max_ws_disconnect_sec:
            self.trip(
                f"BORSA WEBSOCKET BAĞLANTISI {gap:.1f} SANİYEDİR KOPTU "
                f"(limit: {self.max_ws_disconnect_sec:.1f} sn)"
            )
            return True
        return False

    # -- 5) Flash Crash Denetimi -----------------------------------------------
    def check_price_shock(self, symbol: str, price: float, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        prev = self._recent_prices.get(symbol)
        self._recent_prices[symbol] = (now, price)
        if prev is not None:
            prev_ts, prev_px = prev
            if 0 < (now - prev_ts) <= 15.0 and prev_px > 0:
                move_pct = abs(price - prev_px) / prev_px * 100.0
                if move_pct >= self.flash_crash_pct:
                    self.trip(
                        f"FLASH CRASH / ANİ FİYAT ŞOKU ({symbol} %{move_pct:.2f} hareket)"
                    )
                    return True
        return False

    def can_trade(self) -> tuple[bool, str]:
        self._reset_day_if_needed()
        self.check_ws_health()
        if self.system_locked:
            return False, f"🔒 SİSTEM KİLİTLENDİ (YETKİ HATASI): {self.trip_reason}"
        if self.tripped:
            return False, f"🚨 SİGORTA ATTI (CIRCUIT BREAKER): {self.trip_reason}"
        if self.paused:
            return False, "⏸️ Bot kullanıcı tarafından duraklatıldı (PAUSE)."
        return True, "OK"

    def snapshot(self) -> dict:
        self._reset_day_if_needed()
        ws_age = round(max(0.0, time.time() - self.last_ws_ts), 2)
        return {
            "tripped": self.tripped,
            "system_locked": self.system_locked,
            "trip_reason": self.trip_reason,
            "tripped_at": self.tripped_at,
            "paused": self.paused,
            "consecutive_errors": self.consecutive_errors,
            "max_consecutive_errors": self.max_consecutive_errors,
            "consecutive_auth_errors": self.consecutive_auth_errors,
            "max_consecutive_auth_errors": self.max_consecutive_auth_errors,
            "last_error_msg": self.last_error_msg,
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
            "daily_max_loss_pct": self.daily_max_loss_pct,
            "ws_silent_sec": ws_age,
            "max_ws_disconnect_sec": self.max_ws_disconnect_sec,
            "status": (
                "SİSTEM KİLİTLİ (AUTH KILL-SWITCH)"
                if self.system_locked
                else (
                    "ACİL DURDURULDU (KILL-SWITCH)"
                    if self.tripped
                    else ("DURAKLATILDI" if self.paused else "AKTİF & GÜVENLİ")
                )
            ),
        }
