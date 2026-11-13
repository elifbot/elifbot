"""Cekirdek motor: islem akisi -> ozellikler -> giris/cikis kararlari -> broker.

Zaman disaridan verilir (now), boylece ayni kod canli akista ve simulasyonda calisir.
Karar sirasi her zaman: sinyal -> RISK MOTORU -> broker. Baska yol yok.
"""
from __future__ import annotations

import logging
import os
from collections import Counter

from .alerts import Alerter
from .brokers.base import Broker
from .config import Config
from .exits import decide_exit
from .features import SymbolState
from .models import Signal, Trade
from .risk import RiskManager
from .safety import SafetyMonitor
from .scoring import score_entry
from .storage import Storage

log = logging.getLogger("engine")


class Engine:
    def __init__(self, cfg: Config, brokers: dict[str, Broker], alerter: Alerter, storage: Storage,
                 safety: SafetyMonitor, control_dir: str = "data"):
        self.cfg = cfg
        self.brokers = brokers
        self.alerter = alerter
        self.storage = storage
        self.safety = safety
        self.risk = RiskManager(cfg, safety)
        self.states: dict[tuple[str, str], SymbolState] = {}
        self.dirty: set[tuple[str, str]] = set()
        self.stats: Counter = Counter()
        self.control_dir = control_dir
        self._pending_msgs: list[str] = []
        self._last_ctl_check = 0.0
        # Haber/makro/analist ajanlari icin kanca: f(signal) -> None (izin) | str (engel nedeni).
        self.entry_filters: list = []
        for b in brokers.values():
            b.on_event = self.on_event  # type: ignore[attr-defined]

    # ---- olaylar (broker -> motor)
    def on_event(self, kind: str, p: dict) -> None:
        self.stats[kind] += 1
        if kind == "exit":
            self.storage.trade(p, self.cfg.mode)
            self.risk.mark(p["exchange"], p["symbol"], p["closed_ts"])
            self.stats[f"exit:{p['reason']}"] += 1
            if self.cfg.alerts.notify_trades:
                self._pending_msgs.append(
                    f"KAPANDI {p['exchange']} {p['symbol']} {p['side']} net {p['pnl_net']:+.2f}$ ({p['reason']})")
        elif kind == "alert":
            self._pending_msgs.append(p["msg"])
        elif kind == "entry":
            self.risk.mark(p["exchange"], p["symbol"], p["ts"])
            if self.cfg.alerts.notify_trades:
                self._pending_msgs.append(
                    f"ACILDI {p['exchange']} {p['symbol']} {p['side']} @ {p['price']:.6g} stop {p['stop']:.6g}")

    # ---- veri girisi
    def on_trade(self, t: Trade) -> None:
        key = (t.exchange, t.symbol)
        st = self.states.get(key)
        if st is None:
            st = self.states[key] = SymbolState(self.cfg.scanner)
        st.add_trade(t.ts, t.price, t.usd, t.taker_buy)
        self.dirty.add(key)
        self.safety.touch(t.exchange, t.ts)
        b = self.brokers.get(t.exchange)
        if b is not None:
            b.on_trade(t)

    # ---- periyodik degerlendirme
    async def evaluate(self, now: float) -> None:
        for msg in self.safety.check(now):
            self._pending_msgs.append(msg)
            self.storage.event("safety", msg, now)
        await self._control_files(now)
        for b in self.brokers.values():
            await b.tick(now)

        keys = set(self.dirty)
        self.dirty.clear()
        for ex, b in self.brokers.items():
            keys.update((ex, s) for s in b.positions)

        for key in keys:
            ex, sym = key
            st = self.states.get(key)
            b = self.brokers.get(ex)
            if st is None or b is None:
                continue
            f = st.compute(now)
            pos = b.positions.get(sym)
            if pos is not None:
                await self._manage_position(b, pos, st, f, now)
            elif f is not None and not b.has_pending(sym):
                await self._try_entry(b, key, f, now)

        if self._pending_msgs:
            msgs, self._pending_msgs = self._pending_msgs, []
            for m in msgs:
                await self.alerter.send(m)

    async def _manage_position(self, b: Broker, pos, st: SymbolState, f, now: float) -> None:
        price = st.last_price
        pnl = b.unrealized(pos, price)
        pos.peak_pnl = max(pos.peak_pnl, pnl)
        x = self.cfg.exit
        if not pos.breakeven_done and pos.peak_pnl >= x.breakeven_activation_usd:
            new_stop = pos.entry_price * (1 + pos.side.sign * x.breakeven_buffer_pct / 100)
            await b.update_stop(pos, new_stop)
            pos.breakeven_done = True
        d = decide_exit(pos, f, pnl, now, self.cfg)
        if d is not None:
            reason, detail = d
            await b.close_position(pos, reason, now, price, detail)

    async def _try_entry(self, b: Broker, key, f, now: float) -> None:
        ex, sym = key
        res = score_entry(f, self.cfg.entry, self.cfg.scanner)
        if res is None:
            return
        side, score, reasons = res
        sig = Signal(exchange=ex, symbol=sym, side=side, score=score, price=f.price, ts=now, reasons=reasons)
        self.stats["signals"] += 1
        for flt in self.entry_filters:
            why = flt(sig)
            if why:
                self.stats[f"reject:filter:{why}"] += 1
                self.storage.signal(now, ex, sym, side.value, score, f.price, reasons, f"filtered:{why}")
                return
        out = self.risk.approve(sig, b.account(), list(b.positions.values()), now, b.has_symbol(sym))
        if isinstance(out, str):
            self.stats[f"reject:{out}"] += 1
            if out not in ("cooldown", "has_position"):
                self.storage.signal(now, ex, sym, side.value, score, f.price, reasons, f"rejected:{out}")
            return
        ok = await b.place_entry(out, now)
        self.stats["entry_requested" if ok else "entry_failed"] += 1
        self.storage.signal(now, ex, sym, side.value, score, f.price, reasons, "entered" if ok else "failed")
        if ok:
            self.risk.mark(ex, sym, now)

    # ---- elle kontrol dosyalari: data/PAUSE (dur), data/CLOSE_ALL (hepsini kapat)
    async def _control_files(self, now: float) -> None:
        if now - self._last_ctl_check < 2.0:
            return
        self._last_ctl_check = now
        pause = os.path.exists(os.path.join(self.control_dir, "PAUSE"))
        halted = ("*", "pause_file") in self.safety.halts
        if pause and not halted:
            self._pending_msgs.append(self.safety.halt("*", "pause_file", "data/PAUSE dosyasi var", manual=True))
        elif not pause and halted:
            m = self.safety.resume("*", "pause_file")
            if m:
                self._pending_msgs.append(m)
        close_all = os.path.join(self.control_dir, "CLOSE_ALL")
        if os.path.exists(close_all):
            for b in self.brokers.values():
                for pos in list(b.positions.values()):
                    st = self.states.get((b.exchange, pos.symbol))
                    px = st.last_price if st else pos.entry_price
                    await b.close_position(pos, "manual_close_all", now, px)
            try:
                os.remove(close_all)
            except OSError:
                pass
            self._pending_msgs.append("CLOSE_ALL calistirildi")

    # ---- ozet
    def summary(self) -> str:
        lines = []
        for ex, b in self.brokers.items():
            a = b.account()
            lines.append(f"{ex}: ozvarlik {a.equity:.2f}$ | bosta {a.available:.2f}$ | acik {a.open_positions} "
                         f"| bekleyen {a.pending} | bugun {a.realized_today:+.2f}$")
        s = self.stats
        filled = s["entry"]
        req = s["entry_requested"]
        lines.append(f"sinyal {s['signals']} | giris istendi {req} | dolan {filled} | iptal {s['entry_cancel']} "
                     f"| kapanan {s['exit']}")
        reasons = {k.split(':', 1)[1]: v for k, v in s.items() if k.startswith('exit:')}
        if reasons:
            lines.append("cikis nedenleri: " + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
        halts = self.safety.status()
        if halts:
            lines.append("DURDURMALAR: " + "; ".join(halts))
        return "\n".join(lines)
