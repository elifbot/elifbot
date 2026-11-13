"""PAPER motoru: sinyalleri sonraki mum açılışında doldurur, çıkışları kötümser yönetir.

Dolum kuralları (kasıtlı kötümser):
  • sinyal mum kapanışında üretilir, giriş SONRAKİ mumun açılışında (ileriye bakış yok)
  • giriş/çıkış market emri: kayma + yarım makas aleyhe; ücret her iki yönde taker
  • aynı mumda hem stop hem hedef görülürse STOP kazanır
  • açılış stop'un ötesindeyse (gap) dolum açılıştan olur
  • breakeven/iz süren stop mum KAPANDIKTAN sonra güncellenir (aynı mumda kullanılmaz)
"""
from __future__ import annotations

from collections import Counter
from typing import Callable, Optional

from .models import Bar, Config, Position, Signal, Trade
from .risk import (CircuitBreaker, KellyTracker, edge_ok, liq_distance_pct,
                   round_trip_cost_bps, size_position)
from .signals import SignalSource

FUNDING_MS = 8 * 3_600_000


class Engine:
    def __init__(self, cfg: Config, source: SignalSource,
                 on_event: Optional[Callable[[str, dict], None]] = None):
        self.cfg = cfg.validate()
        self.source = source
        self.on_event = on_event or (lambda kind, payload: None)
        self.balance = cfg.equity
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, Signal] = {}
        self.cooldown_until: dict[str, int] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple[int, float]] = []
        self.stats: Counter[str] = Counter()
        self.breaker = CircuitBreaker(cfg)
        self.kelly = KellyTracker()
        self.last_close: dict[str, float] = {}

    # ------------------------------------------------------------------ yardımcılar
    def _emit(self, kind: str, **payload) -> None:
        self.on_event(kind, payload)

    def _reject(self, why: str, **ctx) -> None:
        self.stats["REJECT_" + why] += 1
        self._emit("reject", reason=why, **ctx)

    def equity(self) -> float:
        eq = self.balance
        for s, p in self.positions.items():
            px = self.last_close.get(s, p.entry)
            eq += p.side * (px - p.entry) * p.qty - p.entry_fee + p.funding
        return eq

    def _slip(self) -> float:
        return (self.cfg.slip_bps + self.cfg.spread_bps / 2.0) / 10_000.0

    def gross(self) -> float:
        return sum(p.qty * p.entry for p in self.positions.values())

    # ------------------------------------------------------------------ ana adım
    def step(self, ts: int, bars: dict[str, Bar]) -> None:
        """Bir zaman damgasında kapanmış mumları işler (sembol sırası deterministiktir)."""
        for s, b in bars.items():
            self.last_close[s] = b.close

        # 1) mevcut pozisyonların çıkışları
        for s in sorted(bars):
            p = self.positions.get(s)
            if p is not None:
                self._manage(p, bars[s], ts)

        # 2) bekleyen girişleri doldur: yüksek skor önce
        due = [(abs(sig.score), s) for s, sig in self.pending.items() if s in bars]
        for _, s in sorted(due, key=lambda x: (-x[0], x[1])):
            sig = self.pending.pop(s)
            if self._fill(s, sig, bars[s], ts):
                p = self.positions.get(s)
                if p is not None:
                    self._manage(p, bars[s], ts)   # giriş mumunda da stop/hedef sınanır

        # 3) devre kesici + sermaye eğrisi
        eq = self.equity()
        self.equity_curve.append((ts, eq))
        ok, why = self.breaker.allow(ts, eq)

        # 4) yeni sinyaller
        for s in sorted(bars):
            if s in self.positions or s in self.pending:
                continue
            if ts < self.cooldown_until.get(s, 0):
                self.stats["SKIP_COOLDOWN"] += 1
                continue
            sig, reason = self.source.signal(s, ts)
            self.stats["EVAL_" + reason] += 1
            if sig is None:
                continue
            if not ok:
                self._reject(why, sym=s)
                continue
            if not edge_ok(sig.price, sig.atr, self.cfg):
                self._reject("EDGE_BELOW_COST", sym=s)
                continue
            g = self.cfg.breadth_guard
            if g > 0:
                br = self.source.breadth(ts)
                if br is not None and ((sig.side > 0 and br <= -g) or (sig.side < 0 and br >= g)):
                    self._reject("BREADTH", sym=s, breadth=br)
                    continue
            self.pending[s] = sig
            self.stats["SIGNALS"] += 1
            self._emit("signal", sym=s, side=sig.side, score=sig.score, ts=ts)

    # ------------------------------------------------------------------ giriş
    def _fill(self, sym: str, sig: Signal, bar: Bar, ts: int) -> bool:
        cfg = self.cfg
        ok, why = self.breaker.allow(ts, self.equity())
        if not ok:
            self._reject(why, sym=sym)
            return False
        if len(self.positions) >= cfg.max_positions:
            self._reject("MAX_POSITIONS", sym=sym)
            return False
        if sum(1 for p in self.positions.values() if p.side == sig.side) >= cfg.max_same_side:
            self._reject("MAX_SAME_SIDE", sym=sym)
            return False
        entry = bar.open * (1 + sig.side * self._slip())
        if abs(entry - sig.price) > cfg.max_drift_atr * sig.atr:
            self._reject("PRICE_DRIFT", sym=sym)
            return False
        stop_dist = cfg.stop_atr * sig.atr
        rp = self.kelly.risk_pct(cfg) if cfg.kelly else None
        qty, risk_usd, why = size_position(self.equity(), entry, stop_dist, cfg, rp)
        if qty <= 0:
            self._reject(why, sym=sym)
            return False
        notional = qty * entry
        if self.gross() + notional > cfg.max_gross_pct / 100.0 * self.equity():
            self._reject("MAX_GROSS", sym=sym)
            return False
        liq = liq_distance_pct(cfg)
        stop_pct = stop_dist / entry * 100.0
        if liq < cfg.min_liq_pct or liq < stop_pct * 3.0:
            self._reject("LIQ_TOO_CLOSE", sym=sym)
            return False
        fee = notional * cfg.taker_bps / 10_000.0
        p = Position(
            sym=sym, side=sig.side, entry=entry, qty=qty,
            stop=entry - sig.side * stop_dist, tp=entry + sig.side * cfg.tp_atr * sig.atr,
            atr=sig.atr, risk_usd=risk_usd, r_unit=stop_dist, open_ts=ts,
            last_funding_k=bar.ts // FUNDING_MS, votes=dict(sig.votes), score=sig.score,
            best=entry, entry_fee=fee, last_close=bar.close,
        )
        self.positions[sym] = p
        self.stats["OPENED"] += 1
        self._emit("open", sym=sym, side=p.side, entry=entry, qty=qty, stop=p.stop, tp=p.tp, ts=ts)
        return True

    # ------------------------------------------------------------------ yönetim / çıkış
    def _manage(self, p: Position, bar: Bar, ts: int) -> None:
        cfg = self.cfg
        # funding: 8 saatlik sınır geçildiyse (long öder, short alır)
        k = bar.ts // FUNDING_MS
        if k > p.last_funding_k:
            n = k - p.last_funding_k
            p.funding -= p.side * p.qty * bar.open * cfg.funding_bps_8h / 10_000.0 * n
            p.last_funding_k = k

        if p.side > 0:
            stop_hit = bar.open <= p.stop or bar.low <= p.stop
            tp_hit = bar.high >= p.tp
        else:
            stop_hit = bar.open >= p.stop or bar.high >= p.stop
            tp_hit = bar.low <= p.tp

        if stop_hit:                                   # stop her zaman önce (kötümser)
            raw = min(bar.open, p.stop) if p.side > 0 else max(bar.open, p.stop)
            self._close(p, raw * (1 - p.side * self._slip()), bar.ts, p.stop_kind)
            return
        if tp_hit:                                     # limit hedef: kayma yok, gap lehineyse açılıştan
            raw = max(bar.open, p.tp) if p.side > 0 else min(bar.open, p.tp)
            self._close(p, raw, bar.ts, "TARGET")
            return

        p.bars_held += 1
        p.last_close = bar.close
        fav = (bar.high if p.side > 0 else bar.low)
        p.best = max(p.best, fav) if p.side > 0 else min(p.best, fav)
        r_fav = p.side * (p.best - p.entry) / p.r_unit
        if r_fav >= cfg.breakeven_r:
            be = p.entry + p.side * p.entry * round_trip_cost_bps(cfg) / 10_000.0
            if (p.stop - be) * p.side < 0:
                p.stop, p.stop_kind = be, "BREAKEVEN"
        if r_fav >= cfg.trail_start_r:
            tr = p.best - p.side * cfg.trail_atr * p.atr
            if (tr - p.stop) * p.side > 0:
                p.stop, p.stop_kind = tr, "TRAIL"
        if p.bars_held >= cfg.max_hold_bars:
            self._close(p, bar.close * (1 - p.side * self._slip()), bar.ts, "TIME")

    def _close(self, p: Position, px: float, ts: int, reason: str) -> None:
        cfg = self.cfg
        exit_fee = p.qty * px * cfg.taker_bps / 10_000.0
        gross = p.side * (px - p.entry) * p.qty
        pnl = gross - p.entry_fee - exit_fee + p.funding
        self.balance += pnl
        t = Trade(sym=p.sym, side=p.side, open_ts=p.open_ts, close_ts=ts, entry=p.entry,
                  exit=px, qty=p.qty, pnl=pnl, r_mult=pnl / p.risk_usd if p.risk_usd else 0.0,
                  reason=reason, bars=p.bars_held, fees=p.entry_fee + exit_fee,
                  funding=p.funding, score=p.score, votes=p.votes)
        self.trades.append(t)
        self.positions.pop(p.sym, None)
        self.cooldown_until[p.sym] = ts + cfg.cooldown_bars * cfg.bar_ms
        self.breaker.on_trade(t)
        self.kelly.add(t.r_mult)
        self.stats["CLOSED_" + reason] += 1
        self._emit("close", sym=p.sym, pnl=round(pnl, 4), r=round(t.r_mult, 3), reason=reason, ts=ts)

    def finish(self, bars: dict[str, Bar], ts: int, force_close: bool = True) -> None:
        """Koşu sonu: açık pozisyonları kapanış fiyatından (END) kapatır; sonuçlar eksiksiz olsun."""
        if not force_close:
            return
        for s in list(self.positions):
            p = self.positions[s]
            px = bars[s].close if s in bars else self.last_close.get(s, p.entry)
            self._close(p, px * (1 - p.side * self._slip()), ts, "END")
