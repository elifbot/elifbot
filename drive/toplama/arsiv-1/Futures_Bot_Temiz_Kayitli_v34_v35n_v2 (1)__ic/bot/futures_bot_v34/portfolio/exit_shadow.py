"""Aynı pozisyon tikleri üzerinde alternatif çıkışları salt-izleme simüle eder.

Gölge durumlar gerçek portföye emir/karar vermez. Amaç, geçmiş MFE zirvelerinden
varsayımsal kâr uydurmak yerine kuralların o anda nasıl kapanacağını ölçmektir.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShadowVariant:
    name: str
    tp_pct: float
    sl_pct: float
    activation_mfe_pct: float | None = None
    trailing_distance_pct: float | None = None
    breakeven: bool = False

    def __post_init__(self) -> None:
        if self.tp_pct <= 0 or self.sl_pct <= 0:
            raise ValueError("TP/SL pozitif olmalı")
        if self.breakeven and self.trailing_distance_pct is not None:
            raise ValueError("breakeven ve trailing birlikte olamaz")
        if self.breakeven or self.trailing_distance_pct is not None:
            if self.activation_mfe_pct is None or self.activation_mfe_pct < 0:
                raise ValueError("aktivasyon MFE değeri gerekli")
        if self.trailing_distance_pct is not None and self.trailing_distance_pct <= 0:
            raise ValueError("trailing mesafesi pozitif olmalı")


def default_variants(tp_pct: float, sl_pct: float) -> tuple[ShadowVariant, ...]:
    """Küçük, önceden tanımlı araştırma seti; optimum oldukları iddia edilmez."""
    return (
        ShadowVariant("baseline", tp_pct, sl_pct),
        ShadowVariant("tp_100", 1.00, sl_pct),
        ShadowVariant("tp_075", 0.75, sl_pct),
        ShadowVariant("be_075", tp_pct, sl_pct, activation_mfe_pct=0.75, breakeven=True),
        ShadowVariant("trail_050_075", tp_pct, sl_pct,
                      activation_mfe_pct=0.75, trailing_distance_pct=0.50),
        ShadowVariant("trail_050_100", tp_pct, sl_pct,
                      activation_mfe_pct=1.00, trailing_distance_pct=0.50),
    )


@dataclass
class _State:
    variant: ShadowVariant
    entry_price: float
    stop_price: float
    take_profit_price: float
    peak_price: float
    is_open: bool = True
    activated: bool = False
    stop_kind: str = "initial"
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    closed_at: int | None = None
    exit_price: float | None = None
    reason: str | None = None
    close_source: str | None = None
    gross_pnl: float | None = None
    exit_fee: float | None = None
    realized_pnl: float | None = None
    last_price: float = 0.0
    last_ts: int = 0


class ShadowPosition:
    """Bir gerçek paper pozisyonuna bağlı bağımsız alternatif çıkış durumları."""

    def __init__(self, exchange: str, symbol: str, side: str, entry_price: float,
                 qty_base: float, entry_fee: float, opened_at: int, *,
                 fee_rate: float, variants: tuple[ShadowVariant, ...]) -> None:
        if side not in ("LONG", "SHORT") or entry_price <= 0 or qty_base <= 0:
            raise ValueError("geçersiz gölge pozisyon")
        if not variants or len({v.name for v in variants}) != len(variants):
            raise ValueError("gölge varyant adları benzersiz olmalı")
        self.exchange = exchange
        self.symbol = symbol
        self.side = side
        self.entry_price = float(entry_price)
        self.qty_base = float(qty_base)
        self.entry_fee = float(entry_fee)
        self.opened_at = int(opened_at)
        self.fee_rate = float(fee_rate)
        self.states: dict[str, _State] = {}
        for v in variants:
            if side == "LONG":
                stop = entry_price * (1 - v.sl_pct / 100)
                tp = entry_price * (1 + v.tp_pct / 100)
            else:
                stop = entry_price * (1 + v.sl_pct / 100)
                tp = entry_price * (1 - v.tp_pct / 100)
            self.states[v.name] = _State(v, entry_price, stop, tp, entry_price,
                                         last_price=entry_price, last_ts=opened_at)

    def _ret(self, price: float) -> float:
        yon = 1.0 if self.side == "LONG" else -1.0
        return (price / self.entry_price - 1.0) * 100.0 * yon

    def _breakeven_stop(self) -> float:
        """Giriş ve tahmini çıkış taker ücreti sonrası yaklaşık tam net sıfır."""
        fee_per_base = self.entry_fee / self.qty_base
        if self.side == "LONG":
            return (self.entry_price + fee_per_base) / (1 - self.fee_rate)
        return (self.entry_price - fee_per_base) / (1 + self.fee_rate)

    def mark(self, price: float, ts_ms: int) -> None:
        """MFE/MAE ve stopları günceller; burada kapanış kararı verilmez."""
        if not (price > 0):
            return
        for st in self.states.values():
            if not st.is_open:
                continue
            if st.last_ts == ts_ms and st.last_price == price:
                continue
            ret = self._ret(price)
            st.mfe_pct = max(st.mfe_pct, ret)
            st.mae_pct = max(st.mae_pct, -ret)
            if self.side == "LONG":
                st.peak_price = max(st.peak_price, price)
            else:
                st.peak_price = min(st.peak_price, price)
            v = st.variant
            if v.activation_mfe_pct is not None and st.mfe_pct >= v.activation_mfe_pct:
                st.activated = True
                if v.breakeven:
                    candidate = self._breakeven_stop()
                    st.stop_kind = "breakeven_stop"
                elif v.trailing_distance_pct is not None:
                    if self.side == "LONG":
                        candidate = st.peak_price * (1 - v.trailing_distance_pct / 100)
                    else:
                        candidate = st.peak_price * (1 + v.trailing_distance_pct / 100)
                    st.stop_kind = "trailing_stop"
                else:
                    candidate = st.stop_price
                # Stop yalnızca pozisyon lehine hareket eder (ratchet).
                if self.side == "LONG":
                    st.stop_price = max(st.stop_price, candidate)
                else:
                    st.stop_price = min(st.stop_price, candidate)
            st.last_price = price
            st.last_ts = ts_ms

    def _close(self, st: _State, price: float, ts_ms: int,
               reason: str, source: str) -> None:
        gross = ((price - self.entry_price) * self.qty_base if self.side == "LONG"
                 else (self.entry_price - price) * self.qty_base)
        exit_fee = abs(self.qty_base * price) * self.fee_rate
        st.is_open = False
        st.closed_at = int(ts_ms)
        st.exit_price = float(price)
        st.reason = reason
        st.close_source = source
        st.gross_pnl = gross
        st.exit_fee = exit_fee
        st.realized_pnl = gross - self.entry_fee - exit_fee

    def evaluate(self, price: float, ts_ms: int) -> None:
        """Gerçek botla aynı çıkış turunda mevcut fiyattan kapanışları uygular."""
        self.mark(price, ts_ms)
        for st in self.states.values():
            if not st.is_open:
                continue
            if self.side == "LONG":
                stop_hit = price <= st.stop_price
                tp_hit = price >= st.take_profit_price
            else:
                stop_hit = price >= st.stop_price
                tp_hit = price <= st.take_profit_price
            if stop_hit:
                reason = "stop_loss" if st.stop_kind == "initial" else st.stop_kind
                self._close(st, price, ts_ms, reason, "rule")
            elif tp_hit:
                self._close(st, price, ts_ms, "take_profit", "rule")

    def finish(self, price: float, ts_ms: int, actual_reason: str) -> None:
        """Gerçek pozisyon kapandığında hâlâ açık alternatifleri aynı fiyattan kapat."""
        self.mark(price, ts_ms)
        for st in self.states.values():
            if st.is_open:
                self._close(st, price, ts_ms, actual_reason, "actual_finish")

    def rows(self) -> list[dict]:
        if any(st.is_open for st in self.states.values()):
            raise ValueError("gölge pozisyon henüz kapatılmadı")
        rows = []
        for st in self.states.values():
            v = st.variant
            rows.append({
                "exchange": self.exchange, "symbol": self.symbol, "side": self.side,
                "opened_at": self.opened_at, "closed_at": st.closed_at,
                "variant": v.name, "reason": st.reason, "close_source": st.close_source,
                "entry_price": self.entry_price, "exit_price": st.exit_price,
                "qty_base": self.qty_base, "entry_fee": self.entry_fee,
                "exit_fee": st.exit_fee, "gross_pnl": st.gross_pnl,
                "realized_pnl": st.realized_pnl, "mfe_pct": st.mfe_pct,
                "mae_pct": st.mae_pct, "activated": int(st.activated),
                "final_stop_price": st.stop_price, "tp_pct": v.tp_pct,
                "sl_pct": v.sl_pct, "activation_mfe_pct": v.activation_mfe_pct,
                "trailing_distance_pct": v.trailing_distance_pct,
                "breakeven": int(v.breakeven),
            })
        return rows
