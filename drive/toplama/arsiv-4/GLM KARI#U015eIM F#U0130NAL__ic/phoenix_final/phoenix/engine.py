"""PHOENIX FINAL motoru: sinyal → sonraki mum açılışında giriş → kötümser çıkış yönetimi.

Dolum kuralları (sentez-bot'un kasıtlı kötümserliği):
  • sinyal KAPALI mum kapanışında üretilir, giriş SONRAKİ mumun AÇILIŞINDA dolar
  • giriş/çıkışta kayma + yarım makas aleyhe; ücret her iki yönde taker
  • aynı mumda hem stop hem hedef görünürse STOP kazanır
  • açılış stop'un ötesindeyse (gap) dolum açılıştan olur (daha kötü fiyat)
  • breakeven / iz süren stop mum KAPANDIKTAN sonra güncellenir

Çıkış yönetimi (FUSION_PRO + Phoenix):
  • tp1: +1R'de %35 kısmi kâr, stop başaboya çekilir
  • runner: 1.8×ATR iz süren stop + orijinal hedef
  • max_hold mum süresi dolunca TIME çıkışı
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

import pandas as pd

from .models import Bar, Position, Signal, Trade
from .risk import (CircuitBreaker, edge_ok, liq_distance_pct, round_trip_cost_bps,
                   size_position)

FUNDING_MS = 8 * 3_600_000
log = logging.getLogger("phoenix.engine")


class SignalSource(Protocol):
    def signal(self, sym: str, ts: pd.Timestamp) -> tuple[Optional[Signal], str]: ...
    def breadth(self, ts: pd.Timestamp) -> Optional[float]: ...


class Engine:
    def __init__(self, cfg, source: SignalSource, bar_ms: float,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 base_equity: float | None = None):
        self.cfg = cfg
        self.source = source
        self.bar_ms = bar_ms
        self.on_event = on_event or (lambda kind, payload: None)
        self.balance = base_equity if base_equity is not None else cfg.risk.paper_equity
        self.base_equity = self.balance
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, Signal] = {}
        self.cooldown_until: dict[str, pd.Timestamp] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple[pd.Timestamp, float]] = []
        self.stats: Counter[str] = Counter()
        self.breaker = CircuitBreaker(cfg, self.base_equity)
        self.last_close: dict[str, float] = {}

    # ------------------------------------------------------------- yardımcılar
    def _emit(self, kind: str, **payload) -> None:
        self.on_event(kind, payload)

    def _reject(self, why: str, **ctx) -> None:
        self.stats["REJECT_" + why] += 1
        self._emit("reject", reason=why, **ctx)

    def equity(self) -> float:
        eq = self.balance
        for s, p in self.positions.items():
            px = self.last_close.get(s, p.entry)
            eq += p.side * (px - p.entry) * p.qty - p.entry_fee + p.funding - p.partial_realized
        return eq

    def gross(self) -> float:
        return sum(p.qty * p.entry for p in self.positions.values())

    def _slip(self) -> float:
        return (self.cfg.risk.slip_bps + self.cfg.risk.spread_bps / 2.0) / 10_000.0

    # ------------------------------------------------------------- ana adım
    def step(self, ts: pd.Timestamp, bars: dict[str, Bar]) -> None:
        """Bir zaman damgasında KAPANMIŞ mumları işler (sembol sırası determinist)."""
        for s, b in bars.items():
            self.last_close[s] = b.close

        # 1) açık pozisyonların çıkışları
        for s in sorted(bars):
            p = self.positions.get(s)
            if p is not None:
                self._manage(p, bars[s], ts)

        # 2) bekleyen girişleri doldur (yüksek skor önce)
        due = sorted(((abs(sig.score), s) for s, sig in self.pending.items() if s in bars),
                     key=lambda x: (-x[0], x[1]))
        for _, s in due:
            sig = self.pending.pop(s)
            if self._fill(s, sig, bars[s], ts):
                p = self.positions.get(s)
                if p is not None:
                    self._manage(p, bars[s], ts)  # giriş mumunda da stop/hedef sınanır

        # 3) sermaye eğrisi + kesici durumu
        eq = self.equity()
        self.equity_curve.append((ts, eq))
        ok, why = self.breaker.allow(ts, eq)

        # 4) yeni sinyaller
        for s in sorted(bars):
            if s in self.positions or s in self.pending:
                continue
            if ts < self.cooldown_until.get(s, pd.Timestamp.min.tz_localize("UTC")):
                self.stats["SKIP_COOLDOWN"] += 1
                continue
            sig, reason = self.source.signal(s, ts)
            self.stats["EVAL_" + reason] += 1
            if sig is None or sig.side == 0 or sig.vetoes:
                if sig is not None and sig.vetoes:
                    self.stats["VETO_" + sig.vetoes[0]] += 1
                continue
            if not ok:
                self._reject(why, sym=s)
                continue
            if not edge_ok(sig.price, sig.atr, self.cfg):
                self._reject("EDGE_BELOW_COST", sym=s)
                continue
            g = self.cfg.strategy.side_gap  # breadth koruması: piyasa ters yönse giriş yok
            br = self.source.breadth(ts)
            if br is not None and ((sig.side > 0 and br <= -0.35) or (sig.side < 0 and br >= 0.35)):
                self._reject("BREADTH", sym=s, breadth=br)
                continue
            self.pending[s] = sig
            self.stats["SIGNALS"] += 1
            self._emit("signal", sym=s, side=sig.side, score=sig.score, ts=str(ts))

    # ------------------------------------------------------------- giriş
    def _fill(self, sym: str, sig: Signal, bar: Bar, ts: pd.Timestamp) -> bool:
        cfg = self.cfg
        ok, why = self.breaker.allow(ts, self.equity())
        if not ok:
            self._reject(why, sym=sym)
            return False
        if len(self.positions) >= cfg.risk.max_positions:
            self._reject("MAX_POSITIONS", sym=sym)
            return False
        if sum(1 for p in self.positions.values() if p.side == sig.side) >= cfg.risk.max_same_side:
            self._reject("MAX_SAME_SIDE", sym=sym)
            return False
        entry = bar.open * (1 + sig.side * self._slip())
        if abs(entry - sig.price) > 0.5 * sig.atr:
            self._reject("PRICE_DRIFT", sym=sym)
            return False
        stop_dist = cfg.exit.stop_atr * sig.atr
        atrp = sig.atr / entry * 100.0
        qty, risk_usd, lev, rwhy = size_position(self.equity(), entry, stop_dist, atrp, cfg)
        if qty <= 0:
            self._reject(rwhy, sym=sym)
            return False
        notional = qty * entry
        if self.gross() + notional > cfg.risk.max_gross_pct / 100.0 * self.equity():
            self._reject("MAX_GROSS", sym=sym)
            return False
        liq = liq_distance_pct(lev, cfg)
        stop_pct = stop_dist / entry * 100.0
        if liq < cfg.risk.min_liq_pct or liq < stop_pct * 3.0:
            self._reject("LIQ_TOO_CLOSE", sym=sym)
            return False
        fee = notional * cfg.risk.taker_bps / 10_000.0
        p = Position(
            sym=sym, side=sig.side, entry=entry, qty=qty, qty0=qty,
            stop=entry - sig.side * stop_dist,
            tp=entry + sig.side * cfg.exit.tp_r * stop_dist,
            atr=sig.atr, risk_usd=risk_usd, r_unit=stop_dist, open_ts=ts,
            last_funding_k=int(bar.ts_ms // FUNDING_MS), votes=dict(sig.votes), score=sig.score,
            best=entry, entry_fee=fee, lev=lev, partial_realized=0.0,
        )
        self.positions[sym] = p
        self.stats["OPENED"] += 1
        self._emit("open", sym=sym, side=p.side, entry=round(entry, 6), qty=qty,
                   stop=round(p.stop, 6), tp=round(p.tp, 6), lev=lev, ts=str(ts))
        return True

    # ------------------------------------------------------------- yönetim / çıkış
    def _manage(self, p: Position, bar: Bar, ts: pd.Timestamp) -> None:
        cfg = self.cfg
        # funding: 8 saatlik sınır geçildiyse (long öder, short alır)
        k = int(bar.ts_ms // FUNDING_MS)
        if k > p.last_funding_k:
            n = k - p.last_funding_k
            p.funding -= p.side * p.qty * bar.open * cfg.risk.funding_bps_8h / 10_000.0 * n
            p.last_funding_k = k

        if p.side > 0:
            stop_hit = bar.open <= p.stop or bar.low <= p.stop
            tp_hit = bar.high >= p.tp
        else:
            stop_hit = bar.open >= p.stop or bar.high >= p.stop
            tp_hit = bar.low <= p.tp

        if stop_hit:  # stop her zaman önce (kötümser)
            raw = min(bar.open, p.stop) if p.side > 0 else max(bar.open, p.stop)
            self._close(p, raw * (1 - p.side * self._slip()), ts, p.stop_kind)
            return
        if tp_hit:  # limit hedef: kayma yok, gap lehineyse açılıştan dolar
            raw = max(bar.open, p.tp) if p.side > 0 else min(bar.open, p.tp)
            self._close(p, raw, ts, "TARGET")
            return

        p.bars_held += 1
        p.last_close = bar.close
        fav = bar.high if p.side > 0 else bar.low
        p.best = max(p.best, fav) if p.side > 0 else min(p.best, fav)
        r_fav = p.side * (p.best - p.entry) / p.r_unit

        # kısmi kâr: +1R'de %35 sat, stop başaboya (FUSION_PRO tp1)
        if not p.tp1_done and r_fav >= cfg.exit.tp1_r:
            frac = min(max(cfg.exit.tp1_fraction, 0.0), 0.9)
            part = p.qty * frac
            be = p.entry + p.side * p.entry * round_trip_cost_bps(cfg) / 10_000.0
            gross = p.side * (bar.close - p.entry) * part
            fee = part * bar.close * cfg.risk.taker_bps / 10_000.0
            p.partial_realized += gross - fee
            p.qty -= part
            p.tp1_done = True
            if (be - p.stop) * p.side > 0:
                p.stop, p.stop_kind = be, "BREAKEVEN"
            self._emit("tp1", sym=p.sym, frac=frac, at=str(ts))

        if r_fav >= cfg.exit.breakeven_r and p.stop_kind in ("STOP", "BREAKEVEN"):
            be = p.entry + p.side * p.entry * round_trip_cost_bps(cfg) / 10_000.0
            if (be - p.stop) * p.side > 0:
                p.stop, p.stop_kind = be, "BREAKEVEN"
        if p.tp1_done:  # runner iz süren stop (FUSION_PRO trailing)
            tr = p.best - p.side * cfg.exit.trail_atr * p.atr
            if (tr - p.stop) * p.side > 0:
                p.stop, p.stop_kind = tr, "TRAIL"
        if p.bars_held >= cfg.exit.max_hold_bars:
            self._close(p, bar.close * (1 - p.side * self._slip()), ts, "TIME")

    def _close(self, p: Position, px: float, ts: pd.Timestamp, reason: str) -> None:
        cfg = self.cfg
        exit_fee = p.qty * px * cfg.risk.taker_bps / 10_000.0
        gross = p.side * (px - p.entry) * p.qty
        pnl = gross - p.entry_fee - exit_fee + p.funding + p.partial_realized
        self.balance += pnl
        t = Trade(sym=p.sym, side=p.side, open_ts=str(p.open_ts), close_ts=str(ts),
                  entry=p.entry, exit=px, qty=p.qty, pnl=pnl,
                  r_mult=pnl / p.risk_usd if p.risk_usd else 0.0, reason=reason,
                  bars=p.bars_held, fees=p.entry_fee + exit_fee, funding=p.funding,
                  score=p.score, votes=p.votes, lev=p.lev)
        self.trades.append(t)
        self.positions.pop(p.sym, None)
        self.cooldown_until[p.sym] = pd.Timestamp(ts) + pd.Timedelta(
            milliseconds=self.cfg.risk.cooldown_bars * self.bar_ms)
        self.breaker.on_close(ts, pnl, self.bar_ms)
        self.stats["CLOSED_" + reason] += 1
        self._emit("close", sym=p.sym, pnl=round(pnl, 4), r=round(t.r_mult, 3), reason=reason, ts=str(ts))

    def finish(self, bars: dict[str, Bar], ts: pd.Timestamp, force_close: bool = True) -> None:
        """Koşu sonu: açık pozisyonları kapanıştan (END) kapat; sonuçlar eksiksiz olsun."""
        if not force_close:
            return
        for s in list(self.positions):
            p = self.positions[s]
            px = bars[s].close if s in bars else self.last_close.get(s, p.entry)
            self._close(p, px * (1 - p.side * self._slip()), ts, "END")

    # ------------------------------------------------------------- durum kalıcılığı (AcarBot fikri)
    def save_state(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        state = {
            "balance": self.balance,
            "positions": {s: asdict(p) for s, p in self.positions.items()},
            "breaker": {"consec": self.breaker.consec, "day": self.breaker.day,
                        "day_start": self.breaker.day_start, "trips": dict(self.breaker.trips)},
        }
        Path(path).write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")

    def load_state(self, path: str | Path) -> bool:
        f = Path(path)
        if not f.exists():
            return False
        try:
            state = json.loads(f.read_text(encoding="utf-8"))
            self.balance = float(state["balance"])
            for s, d in state.get("positions", {}).items():
                d["open_ts"] = pd.Timestamp(d["open_ts"])
                p = Position(**{k: v for k, v in d.items() if k in Position.__dataclass_fields__})
                self.positions[s] = p
            self.breaker.consec = int(state.get("breaker", {}).get("consec", 0))
            log.info("durum yüklendi: %d pozisyon, bakiye=%.2f", len(self.positions), self.balance)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("durum yüklenemedi: %s", e)
            return False
