"""Acil Durum Sigortası (Circuit Breaker) & Kimlik Doğrulama Kill-Switch."""
from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import datetime, timezone

from .security import is_auth_or_permission_error, mask_secrets, safe_exception_msg


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().split(":", 1)[0]


class CircuitBreaker:
    """Ardışık hata, günlük zarar, WS kopması ve kapsam-duyarlı flash-crash koruması."""

    def __init__(
        self,
        max_consecutive_errors: int = 3,
        daily_max_loss_pct: float = 5.0,
        max_ws_disconnect_sec: float = 10.0,
        flash_crash_pct: float = 8.0,
        max_consecutive_auth_errors: int = 3,
        state_store=None,
        max_ws_silence_sec: float | None = None,
        global_shock_symbols: Iterable[str] | None = None,
        symbol_shock_cooldown_sec: float = 900.0,
    ):
        self.max_consecutive_errors = max(1, int(max_consecutive_errors))
        self.daily_max_loss_pct = abs(float(daily_max_loss_pct))
        ws_sec = max_ws_silence_sec if max_ws_silence_sec is not None else max_ws_disconnect_sec
        self.max_ws_disconnect_sec = max(1.0, float(ws_sec))
        self.flash_crash_pct = abs(float(flash_crash_pct))
        self.max_consecutive_auth_errors = max(1, int(max_consecutive_auth_errors))
        self.state_store = state_store
        self.global_shock_symbols: set[str] | None = (
            {_norm_symbol(s) for s in global_shock_symbols if _norm_symbol(s)}
            if global_shock_symbols is not None
            else None
        )
        self.symbol_shock_cooldown_sec = max(10.0, float(symbol_shock_cooldown_sec))

        self.consecutive_errors: int = 0
        self.consecutive_auth_errors: int = 0
        self.last_error_msg: str = ""
        self.daily_pnl_pct: float = 0.0
        self._day = datetime.now(timezone.utc).date()

        self.last_ws_ts: float = time.time()
        self.ws_monitoring_active: bool = False
        self._ws_alerted: bool = False

        self.tripped: bool = False
        self.system_locked: bool = False
        self.trip_reason: str = ""
        self.tripped_at: float = 0.0
        self.paused: bool = False
        self._recent_prices: dict[str, tuple[float, float]] = {}
        self._symbol_shocks: dict[str, tuple[float, float]] = {}

        self._restore_store()
        self._sync_store()

    def _restore_store(self) -> None:
        """Kill-switch ve günlük zarar durumunu restart sonrasında geri yükler."""
        if self.state_store is None or not hasattr(self.state_store, "get_meta"):
            return
        saved = self.state_store.get_meta("circuit_breaker", {}) or {}
        if not isinstance(saved, dict):
            return
        self.tripped = bool(saved.get("tripped", False))
        self.system_locked = bool(saved.get("system_locked", False))
        self.trip_reason = mask_secrets(saved.get("trip_reason", ""))
        self.tripped_at = float(saved.get("tripped_at", 0.0) or 0.0)
        self.paused = bool(saved.get("paused", False))
        self.consecutive_errors = max(0, int(saved.get("consecutive_errors", 0)))
        self.consecutive_auth_errors = max(0, int(saved.get("consecutive_auth_errors", 0)))
        self.last_error_msg = mask_secrets(saved.get("last_error_msg", ""))[:120]
        if saved.get("day") == self._day.isoformat():
            self.daily_pnl_pct = float(saved.get("daily_pnl_pct", 0.0))

    def _reset_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.daily_pnl_pct = 0.0

    def _sync_store(self) -> None:
        if self.state_store is None or not hasattr(self.state_store, "set_meta"):
            return
        try:
            self.state_store.set_meta("circuit_breaker", self.snapshot())
        except Exception:
            pass

    def trip(self, reason: str, *, lock_system: bool = False) -> None:
        self.tripped = True
        if lock_system:
            self.system_locked = True
        self.trip_reason = mask_secrets(reason)
        self.tripped_at = time.time()
        self._sync_store()

    def reset(self) -> None:
        self.tripped = False
        self.system_locked = False
        self.trip_reason = ""
        self.tripped_at = 0.0
        self.consecutive_errors = 0
        self.consecutive_auth_errors = 0
        self.last_error_msg = ""
        self.paused = False
        self.last_ws_ts = time.time()
        self._ws_alerted = False
        # Eski fiyat çiftleri reset sonrasında yapay bir şok üretmesin.
        self._recent_prices.clear()
        self._symbol_shocks.clear()
        self._sync_store()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._sync_store()

    def pause(self) -> None:
        self.set_paused(True)

    def resume(self) -> None:
        self.set_paused(False)

    def manual_trip(self, reason: str = "MANUEL ACİL DURDURMA") -> None:
        self.trip(reason, lock_system=True)

    def status(self) -> dict:
        return self.snapshot()

    def can_trade(self) -> tuple[bool, str]:
        self._reset_day_if_needed()
        if self.system_locked:
            return False, f"SİSTEM KİLİTLİ: {self.trip_reason}"
        if self.tripped:
            return False, f"SİGORTA ATIK: {self.trip_reason}"
        if self.paused:
            return False, "BOT DURAKLATILDI"
        return True, "OK"

    def is_symbol_in_shock(self, symbol: str, now: float | None = None) -> tuple[bool, str]:
        """Tekil altcoin şok molasında olan pariteleri yeni girişlere karşı korur."""
        norm = _norm_symbol(symbol)
        entry = self._symbol_shocks.get(norm)
        if entry is None:
            return False, ""
        ts_now = now if now is not None else time.time()
        until_ts, move_pct = entry
        if ts_now >= until_ts:
            self._symbol_shocks.pop(norm, None)
            return False, ""
        rem = max(1, int(until_ts - ts_now))
        return True, f"altcoin fiyat şoku molası (%{move_pct:.2f}, kalan {rem}sn)"

    # -- 1) Emir / Yetki Hataları ----------------------------------------------
    def record_order_success(self) -> None:
        if self.consecutive_errors or self.consecutive_auth_errors:
            self.consecutive_errors = 0
            self.consecutive_auth_errors = 0
            self._sync_store()

    def record_auth_error(self, err: BaseException | str) -> bool:
        clean_err = safe_exception_msg(err) if isinstance(err, BaseException) else mask_secrets(err)
        self.consecutive_auth_errors += 1
        self.consecutive_errors += 1
        self.last_error_msg = clean_err[:120]
        if self.consecutive_auth_errors >= self.max_consecutive_auth_errors:
            was_locked = self.system_locked
            self.trip(
                f"EMERGENCY KILL-SWITCH: ARD ARDA {self.consecutive_auth_errors} "
                f"KİMLİK DOĞRULAMA / YETKİ HATASI ({self.last_error_msg[:80]})",
                lock_system=True,
            )
            return not was_locked
        self._sync_store()
        return False

    def record_order_error(self, err: BaseException | str) -> bool:
        if isinstance(err, BaseException) and is_auth_or_permission_error(err):
            return self.record_auth_error(err)
        clean_err = safe_exception_msg(err) if isinstance(err, BaseException) else mask_secrets(err)
        self.consecutive_errors += 1
        self.last_error_msg = clean_err[:120]
        if self.consecutive_errors >= self.max_consecutive_errors:
            was_tripped = self.tripped
            self.trip(
                f"ARD ARDA {self.consecutive_errors} EMİR HATASI "
                f"(son hata: {self.last_error_msg[:80]})"
            )
            return not was_tripped
        self._sync_store()
        return False

    # -- 2) Günlük Zarar Sigortası ---------------------------------------------
    def record_trade_pnl(self, pnl_pct: float) -> bool:
        self._reset_day_if_needed()
        self.daily_pnl_pct += float(pnl_pct)
        if self.daily_pnl_pct <= -self.daily_max_loss_pct:
            was_tripped = self.tripped
            self.trip(
                f"GÜNLÜK ZARAR LİMİTİ AŞILDI: %{self.daily_pnl_pct:.2f} "
                f"(limit: -%{self.daily_max_loss_pct:.2f})"
            )
            return not was_tripped
        self._sync_store()
        return False

    # -- 3) WebSocket Kalp Atışı -----------------------------------------------
    def heartbeat_ws(self, ts: float | None = None) -> None:
        """Her WebSocket mesajında veya pong yanıtında çağrılır."""
        self.ws_monitoring_active = True
        self.last_ws_ts = ts if ts is not None else time.time()
        self._ws_alerted = False

    def check_ws_health(self, now: float | None = None) -> bool:
        """WS bağlantısı 10 sn'den uzun süredir sessizse sigortayı attırır."""
        if not self.ws_monitoring_active or self.tripped or self._ws_alerted:
            return False
        now = now if now is not None else time.time()
        gap = now - self.last_ws_ts
        if gap > self.max_ws_disconnect_sec:
            self._ws_alerted = True
            self.trip(
                f"BORSA WEBSOCKET BAĞLANTISI {gap:.1f} SANİYEDİR KOPTU "
                f"(limit: {self.max_ws_disconnect_sec:.1f} sn)"
            )
            return True
        return False

    # -- 5) Flash Crash Denetimi (Global BTC/ETH vs Tekil Altcoin İzolasyonu) ---
    def evaluate_price_shock(
        self, symbol: str, price: float, now: float | None = None
    ) -> dict:
        """Fiyat şokunu global (tüm portföy) veya tekil parite kapsamında değerlendirir."""
        if self.tripped or price <= 0:
            return {"triggered": False, "scope": "none", "move_pct": 0.0, "reason": ""}
        now = now if now is not None else time.time()
        prev = self._recent_prices.get(symbol)
        self._recent_prices[symbol] = (now, price)
        if prev is None:
            return {"triggered": False, "scope": "none", "move_pct": 0.0, "reason": ""}
        prev_ts, prev_px = prev
        if prev_px <= 0 or (now - prev_ts) > 60.0:
            return {"triggered": False, "scope": "none", "move_pct": 0.0, "reason": ""}
        move_pct = abs(price - prev_px) / prev_px * 100.0
        if move_pct < self.flash_crash_pct:
            return {"triggered": False, "scope": "none", "move_pct": move_pct, "reason": ""}

        norm = _norm_symbol(symbol)
        is_global = (
            self.global_shock_symbols is None
            or norm in self.global_shock_symbols
        )
        if is_global:
            self.trip(
                f"FLASH CRASH / ANİ FİYAT ŞOKU ({symbol} %{move_pct:.2f} hareket, "
                f"limit %{self.flash_crash_pct:.1f})"
            )
            return {
                "triggered": True,
                "scope": "global",
                "move_pct": move_pct,
                "reason": self.trip_reason,
            }

        existing = self._symbol_shocks.get(norm)
        if existing is not None and now < existing[0]:
            return {"triggered": False, "scope": "none", "move_pct": move_pct, "reason": ""}
        self._symbol_shocks[norm] = (now + self.symbol_shock_cooldown_sec, move_pct)
        reason = (
            f"ALTCOIN ANİ FİYAT ŞOKU ({symbol} %{move_pct:.2f} hareket, "
            f"limit %{self.flash_crash_pct:.1f})"
        )
        return {
            "triggered": True,
            "scope": "symbol",
            "move_pct": move_pct,
            "reason": reason,
        }

    def check_price_shock(self, symbol: str, price: float, now: float | None = None) -> bool:
        """Geriye dönük uyumlu global fiyat şoku kontrolü."""
        res = self.evaluate_price_shock(symbol, price, now=now)
        return bool(res.get("triggered") and res.get("scope") == "global")

    def snapshot(self) -> dict:
        self._reset_day_if_needed()
        now = time.time()
        ws_age = round(max(0.0, now - self.last_ws_ts), 1)
        active_symbol_shocks = {
            sym: round(move, 2)
            for sym, (until, move) in list(self._symbol_shocks.items())
            if now < until
        }
        return {
            "tripped": self.tripped,
            "system_locked": self.system_locked,
            "trip_reason": self.trip_reason,
            "reason": self.trip_reason,
            "tripped_at": self.tripped_at,
            "paused": self.paused,
            "consecutive_errors": self.consecutive_errors,
            "consecutive_auth_errors": self.consecutive_auth_errors,
            "last_error_msg": self.last_error_msg,
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
            "daily_max_loss_pct": self.daily_max_loss_pct,
            "day": self._day.isoformat(),
            "ws_silent_sec": ws_age,
            "max_ws_disconnect_sec": self.max_ws_disconnect_sec,
            "global_shock_symbols": (
                sorted(self.global_shock_symbols)
                if self.global_shock_symbols is not None
                else None
            ),
            "active_symbol_shocks": active_symbol_shocks,
            "status": (
                "KİLİTLİ"
                if self.system_locked
                else "SİGORTA ATIK"
                if self.tripped
                else "DURAKLATILDI"
                if self.paused
                else "AKTİF"
            ),
        }
