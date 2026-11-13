"""ACARBOT v2.0 — Emir idempotency, pozisyon mutabakatı, restart kurtarma.

Şartname madde 9 gereksinimleri:
  - Emir gönderiminde idempotency: aynı sinyal için aynı clientOrderId →
    borsa ikinci emri reddeder/tekilleştirir; yerel kayıt da tekrar gönderimi
    engeller.
  - Gerçek pozisyonları borsayla karşılaştırma: sembol/yön/miktar sapması
    raporlanır; `adopt_exchange_on_drift` açıksa uyarı ile birlikte borsa
    doğrusu kabul edilir (varsayılan: yalnızca rapor + alert).
  - Restart sonrası kurtarma: borsadaki açık emirler taranır, bayat giriş
    emirleri (max_order_age_s) İPTAL edilir; koruyucu stopu olmayan her
    pozisyon için sunucu tarafı STOP_MARKET kurulur.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from live.broker_clients import ExchangeOrder, ExchangePosition

logger = logging.getLogger(__name__)


class ExchangeAdapter(Protocol):
    """BinanceFuturesTestnet / OkxDemoTrading ortak yüzeyi (mutabakat için)."""

    def fetch_positions(self) -> list[ExchangePosition]: ...

    def fetch_open_orders(self) -> list[ExchangeOrder]: ...


# ---------------------------------------------------------------------------
# Idempotent emir kimlikleri
# ---------------------------------------------------------------------------

class IdempotentOrderIdFactory:
    """Deterministik clientOrderId üretir ve tekrar gönderimi engeller.

    id = ACB2-<sha1(symbol|side|signal_key)[:10]>
    Aynı (symbol, side, signal_key) tekrar üretilirse aynı id döner →
    borsa tarafında tekillik + yerel kayıtta mükerrer gönderim engeli.
    """

    def __init__(self) -> None:
        self._issued: set[str] = set()

    def order_id(self, symbol: str, side: str, signal_key: str) -> str:
        raw = f"{symbol}|{side}|{signal_key}"
        digest = hashlib.sha1(raw.encode()).hexdigest()[:10].upper()
        client_id = f"ACB2-{digest}"
        self._issued.add(client_id)
        return client_id

    def was_issued(self, client_id: str) -> bool:
        return client_id in self._issued


# ---------------------------------------------------------------------------
# Pozisyon mutabakatı
# ---------------------------------------------------------------------------

@dataclass
class DriftReport:
    matched: list[str] = field(default_factory=list)
    local_only: list[str] = field(default_factory=list)
    exchange_only: list[str] = field(default_factory=list)
    quantity_drift: list[dict] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.local_only or self.exchange_only or self.quantity_drift)

    def as_dict(self) -> dict:
        return {
            "matched": self.matched,
            "local_only": self.local_only,
            "exchange_only": self.exchange_only,
            "quantity_drift": self.quantity_drift,
            "has_drift": self.has_drift,
        }


class PositionReconciler:
    """Yerel paper/pozisyon tablosu ↔ borsa pozisyonları karşılaştırması."""

    def __init__(self, tolerance_qty: float = 1e-6) -> None:
        self.tolerance_qty = tolerance_qty

    def reconcile(
        self,
        local_positions: dict[str, tuple[str, float]],  # symbol → (side, qty)
        exchange_positions: list[ExchangePosition],
    ) -> DriftReport:
        report = DriftReport()
        exchange_by_symbol: dict[str, ExchangePosition] = {
            p.symbol: p for p in exchange_positions
        }
        for symbol, (side, qty) in local_positions.items():
            exchange = exchange_by_symbol.get(symbol)
            if exchange is None:
                report.local_only.append(symbol)
                continue
            if exchange.side != side:
                report.quantity_drift.append({
                    "symbol": symbol, "kind": "side_mismatch",
                    "local": side, "exchange": exchange.side,
                })
            elif abs(exchange.quantity - qty) > self.tolerance_qty:
                report.quantity_drift.append({
                    "symbol": symbol, "kind": "qty_mismatch",
                    "local": round(qty, 8),
                    "exchange": round(exchange.quantity, 8),
                })
            else:
                report.matched.append(symbol)
        for symbol in exchange_by_symbol:
            if symbol not in local_positions:
                report.exchange_only.append(symbol)
        return report


# ---------------------------------------------------------------------------
# Restart sonrası kurtarma
# ---------------------------------------------------------------------------

@dataclass
class RecoveryReport:
    canceled_stale_orders: list[str] = field(default_factory=list)
    stops_restored: list[str] = field(default_factory=list)
    stops_already_present: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "canceled_stale_orders": self.canceled_stale_orders,
            "stops_restored": self.stops_restored,
            "stops_already_present": self.stops_already_present,
            "notes": self.notes,
        }


class RestartRecovery:
    """Yeniden başlatmada borsa tarafını güvenli duruma getirir.

    1. Bayat giriş emirleri iptal edilir (reduce-only olmayan ve yaşı
       max_order_age_s'yi aşan her emir).
    2. Koruyucu stopu olmayan pozisyonlara sunucu tarafı STOP_MARKET kurulur
       (closePosition=true → reduce-only çıkış garantili).
    """

    def __init__(
        self,
        binance: "BinanceFuturesTestnet | None" = None,
        okx: "OkxDemoTrading | None" = None,
        max_order_age_s: float = 120.0,
        clock=None,
    ) -> None:
        self.binance = binance
        self.okx = okx
        self.max_order_age_s = max_order_age_s
        self.clock = clock or (lambda: int(time.time() * 1000))

    def recover_binance(self, stop_prices: dict[str, float]) -> RecoveryReport:
        report = RecoveryReport()
        if self.binance is None:
            report.notes.append("binance istemcisi yok")
            return report
        now_ms = self.clock()
        for order in self.binance.fetch_open_orders():
            age_s = (now_ms - order.updated_ms) / 1000.0
            if not order.reduce_only and age_s > self.max_order_age_s:
                try:
                    self.binance.cancel_all_orders(order.symbol)
                    report.canceled_stale_orders.append(order.symbol)
                except Exception as exc:  # noqa: BLE001
                    report.notes.append(f"iptal hatası {order.symbol}: {exc}")
        protected_symbols = {
            o.symbol for o in self.binance.fetch_open_orders() if o.reduce_only
        }
        for position in self.binance.fetch_positions():
            if position.symbol in protected_symbols:
                report.stops_already_present.append(position.symbol)
                continue
            stop_price = stop_prices.get(position.symbol)
            if stop_price is None:
                report.notes.append(
                    f"koruyucu stop kurulamadı ({position.symbol}): stop fiyatı yok"
                )
                continue
            try:
                self.binance.place_protective_stop(
                    position.symbol, position.side, stop_price,
                    f"ACB2-RST-{hashlib.sha1(position.symbol.encode()).hexdigest()[:8]}",
                )
                report.stops_restored.append(position.symbol)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"stop kurma hatası {position.symbol}: {exc}")
        return report


# ---------------------------------------------------------------------------
# Canlı eşleme (paper kararlarının testnet'e yansıtılması)
# ---------------------------------------------------------------------------

class LiveMirror:
    """Paper kararı → testnet emri eşlemesi (gözetimli yarı-canlı).

    Executor'un OPEN/CLOSE kayıtlarını besler; her yeni pozisyon için
    idempotent market emri + koruyucu stop, her kapanış için reduce-only
    market çıkış gönderir. Mükerrer kayıtlar (aynı client id) atlanır.
    """

    def __init__(self, binance: "BinanceFuturesTestnet") -> None:
        self.binance = binance
        self.ids = IdempotentOrderIdFactory()
        self.sent_entry_keys: set[str] = set()
        self.sent_exit_keys: set[str] = set()
        self.stop_prices: dict[str, float] = {}
        self.errors: list[str] = []

    def mirror_open(
        self, symbol: str, side: str, quantity: float,
        stop_loss: float, signal_key: str,
    ) -> list[str]:
        actions: list[str] = []
        key = f"open:{symbol}:{side}:{signal_key}"
        if key in self.sent_entry_keys:
            return actions
        client_id = self.ids.order_id(symbol, side, signal_key)
        try:
            self.binance.place_entry(symbol, side, quantity, client_id)
            self.sent_entry_keys.add(key)
            actions.append(f"entry:{client_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"entry {symbol}: {exc}")
            return actions
        stop_id = self.ids.order_id(symbol, side, f"stop:{signal_key}")
        try:
            self.binance.place_protective_stop(
                symbol, side, stop_loss, stop_id,
            )
            self.stop_prices[symbol] = stop_loss
            actions.append(f"stop:{stop_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"stop {symbol}: {exc}")
        return actions

    def mirror_close(
        self, symbol: str, side: str, quantity: float, signal_key: str,
    ) -> list[str]:
        actions: list[str] = []
        key = f"close:{symbol}:{side}:{signal_key}"
        if key in self.sent_exit_keys:
            return actions
        client_id = self.ids.order_id(symbol, side, f"exit:{signal_key}")
        try:
            self.binance.place_reduce_only_exit(
                symbol, side, quantity, client_id,
            )
            self.sent_exit_keys.add(key)
            actions.append(f"exit:{client_id}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"exit {symbol}: {exc}")
        return actions


# ---------------------------------------------------------------------------
# Acil durum
# ---------------------------------------------------------------------------

class EmergencyController:
    """Acil durum: TÜM emirleri iptal + TÜM pozisyonları reduce-only kapat.

    Hem Binance testnet hem OKX demo için çalışır; sonrasında yerel
    HARD_HALT callback'i çağrılır (pozisyonlar yerelde de kapatılır).
    """

    def __init__(
        self,
        binance: "BinanceFuturesTestnet | None" = None,
        okx: "OkxDemoTrading | None" = None,
        on_halt=None,
    ) -> None:
        self.binance = binance
        self.okx = okx
        self.on_halt = on_halt
        self.triggered = False

    def trigger(self, reason: str = "manual") -> dict:
        self.triggered = True
        result: dict[str, object] = {"reason": reason, "actions": [], "errors": []}
        if self.binance is not None:
            try:
                for position in self.binance.fetch_positions():
                    self.binance.cancel_all_orders(position.symbol)
                    result["actions"].append(f"cancel:{position.symbol}")
                for position in self.binance.fetch_positions():
                    self.binance.place_reduce_only_exit(
                        position.symbol,
                        position.side,
                        position.quantity,
                        f"ACB2-EMG-{hashlib.sha1((position.symbol + reason).encode()).hexdigest()[:8]}",
                    )
                    result["actions"].append(f"flatten:{position.symbol}")
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(str(exc))
        if self.okx is not None:
            try:
                for position in self.okx.fetch_positions():
                    self.okx.cancel_all_orders(position.symbol)
                    result["actions"].append(f"cancel:{position.symbol}")
                    self.okx.place_market(
                        position.symbol,
                        position.side,
                        position.quantity,
                        f"ACB2EMG{hashlib.sha1((position.symbol + reason).encode()).hexdigest()[:8]}",
                        reduce_only=True,
                    )
                    result["actions"].append(f"flatten:{position.symbol}")
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(str(exc))
        if callable(self.on_halt):
            try:
                self.on_halt(reason)
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"halt_cb: {exc}")
        logger.error("ACİL DURUM: %s | %s", reason, result)
        return result
