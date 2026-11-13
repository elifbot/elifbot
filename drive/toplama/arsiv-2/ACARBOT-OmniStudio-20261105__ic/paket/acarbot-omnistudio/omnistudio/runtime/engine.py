"""Ana motor — gerçek veri → dedektör → kapılar → 20 YZ konseyi → PAPER icra.

AKIŞ
  universe → warmup(REST mum) → WS tick + periyodik quote/mum
    → SpikeDetector → EntryPolicy(kapılar) → RiskManager(portföy+boyut)
    → AICouncil(20 üye) → PaperExecutor(sanal dolum) → StateStore + JSONL

SÜRE PROTOKOLÜ
  warmup → active(duration_sec) → drain(drain_sec) → final
  Süre monotonic ölçülür. Boşluk varsa COMPLETED değil DISCONTINUOUS.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from ..ai.council import AICouncil
from ..ai.registry import registry_status
from ..core.clock import (ContinuityEngine, JsonlLogger, Stopwatch, get_logger,
                          mono, now_ms, setup_logging)
from ..core.config import Config
from ..core.types import (Candle, Decision, GateResult, Mode, RunState, Signal,
                          Tick)
from ..execution.live_guard import mode_banner
from ..execution.paper import PaperExecutor
from ..market.data import MarketData, WSFeed
from ..risk.manager import RiskManager
from ..state.store import StateStore
from ..strategy import indicators
from ..strategy.detector import SpikeDetector
from ..strategy.policy import EntryPolicy, closed_bar_key
from .supervisor import TaskSupervisor

log = get_logger("engine")


class Engine:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.run_id = config.run.run_id or now_ms_str()
        self.out = Path(config.run.out_dir) / self.run_id
        self.out.mkdir(parents=True, exist_ok=True)
        setup_logging(config.run.log_level, self.out / "console.log")

        self.state = RunState.STARTING
        self.detector = SpikeDetector(config.detector)
        self.policy = EntryPolicy(config.policy)
        self.risk = RiskManager(config.risk)
        self.executor = PaperExecutor(self.risk, config.paper)
        self.council = AICouncil(config.council)
        self.supervisor = TaskSupervisor()
        self.continuity = ContinuityEngine()
        self.store = StateStore(self.out / "state.db", fresh=config.run.fresh_state)
        self.decisions_log = JsonlLogger(self.out / "decisions.jsonl")
        self.events_log = JsonlLogger(self.out / "events.jsonl")
        self.health_log = JsonlLogger(self.out / "health.jsonl")

        self.market: MarketData | None = None
        self.session: aiohttp.ClientSession | None = None
        self.feeds: list[WSFeed] = []
        self.candles_1m: dict[str, list[Candle]] = {}
        self.candles_15m: dict[str, list[Candle]] = {}
        self.atr_by_symbol: dict[str, float] = {}
        self.symbols_by_venue: dict[str, list[str]] = {}
        self.funding_cache: dict[str, dict[str, float]] = {}
        self._quote_cursor: dict[str, int] = {}

        self.timers = {k: Stopwatch(k) for k in (
            "tick_total", "detector_eval", "policy_eval", "council_eval",
            "execution", "state_write", "candle_refresh", "quote_refresh",
            "breadth_update")}
        self.counters = {"ticks": 0, "signals": 0, "decisions": 0,
                         "accepted": 0, "rejected": 0, "council_vetoes": 0,
                         "risk_blocks": 0, "quote_ok": 0, "quote_fail": 0}
        self.started_mono: float = 0.0
        self.active_start_mono: float = 0.0
        self.drain_start_mono: float = 0.0
        self.finished_mono: float = 0.0
        self._stop = asyncio.Event()
        self._pending_council = 0
        self.drain_closed: list[str] = []

    # ---------------- yaşam döngüsü ----------------
    async def run(self) -> dict[str, Any]:
        log.info("=" * 68)
        log.info("AI OmniStudio — run %s", self.run_id)
        log.info(mode_banner(self.cfg.run.mode))
        if self.cfg.run.filters_relaxed:
            log.warning("TANI PROFILI: '%s' — eşikler GEVŞETILDI. Bu koşu doğal "
                        "strateji kanıtı DEĞILDIR; yalnız aç/kapat yaşam "
                        "döngüsünü doğrular.", self.cfg.run.profile)
        else:
            log.info("Profil: natural — üretim eşikleri, gevşetme yok")
        log.info("Konsey modu: %s (%d üye, %d anahtarlı)",
                 self.council.mode, len(self.council.specs),
                 len(self.council.live_specs))
        log.info("=" * 68)

        self.store.acquire_lease()
        self.cfg.save(self.out / "config.json")
        self.store.set_meta("run_id", self.run_id)
        self.store.set_meta("mode", self.cfg.run.mode.value)
        self.store.set_meta("started_ms", now_ms())
        self.store.set_meta("ai_registry", registry_status())
        self.store.set_meta("acceptance_criteria", self._criteria())
        self.events_log.write("RUN_START", run_id=self.run_id,
                              mode=self.cfg.run.mode.value,
                              council_mode=self.council.mode)

        self.started_mono = mono()
        self.continuity.start()
        timeout = aiohttp.ClientTimeout(total=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            self.session = session
            self.market = MarketData(session, self.cfg.run.venues,
                                     rest_rps=self.cfg.run.rest_rps)
            probe = await self.market.probe_all()
            self.store.set_meta("venue_probe", probe)
            self.events_log.write("VENUE_PROBE", **probe)
            if not self.market.reachable_venues:
                self.state = RunState.FAILED
                log.error("Hiçbir gerçek veri ucu erişilebilir değil — koşul başlatılmadı")
                return await self._finalize("NO_REACHABLE_MARKET_DATA")

            self.supervisor.register_heartbeat("strategy_cycle", 30.0)
            # Mum yenileme aralığı 45s ise 45s eşik YANLIŞ ALARM üretir:
            # çevrim süresi = bekleme + ağ işlem süresi. Eşik aralıktan
            # türetilir ve ağ payı eklenir.
            data_stale = max(45.0, self.cfg.run.candle_refresh_sec * 2.0 + 30.0)
            self.supervisor.register_heartbeat("data_progress", data_stale)
            log.info("Heartbeat eşikleri: strategy_cycle=30s, data_progress=%.0fs",
                     data_stale)
            self.supervisor.spawn("universe_warmup", self._task_warmup())
            self.supervisor.spawn("market_poll", self._task_market_poll())
            self.supervisor.spawn("strategy_cycle", self._task_strategy())
            self.supervisor.spawn("supervision", self._task_supervision())
            for venue in self.market.reachable_venues:
                if self.cfg.run.use_websocket:
                    self.supervisor.spawn(f"ws_{venue}", self._task_ws(venue))
            await self._wait_finish()
            result = await self._finalize()
        return result

    def _criteria(self) -> dict[str, Any]:
        """Koşu BAŞLAMADAN kaydedilen başarı ölçütleri (sonradan değiştirilmez)."""
        return {
            "declared_before_run": True,
            "duration_sec": self.cfg.run.duration_sec,
            "drain_sec": self.cfg.run.drain_sec,
            "success": {
                "time_protocol": "active_window_completed",
                "no_task_failures": True,
                "no_continuity_gap": True,
                "http_error_rate_max_pct": 5.0,
            },
            "not_claimed": [
                "Kârlılık kanıtı", "Yürütme güvenilirliği onayı",
                "Gerçek para uygunluğu", "Kesintisiz uptime garantisi",
            ],
            "forced_trades": False,
            "profile": self.cfg.run.profile,
            "filters_loosened": self.cfg.run.filters_relaxed,
            "old_db_inherited": False,
            "evidence_class": ("LIFECYCLE_DIAGNOSTIC_NOT_NATURAL"
                               if self.cfg.run.filters_relaxed
                               else "NATURAL_PAPER"),
        }

    async def _wait_finish(self) -> None:
        total = self.cfg.run.warmup_sec + self.cfg.run.duration_sec + self.cfg.run.drain_sec
        end = self.started_mono + total
        while not self._stop.is_set():
            if self.supervisor.fatal.is_set():
                self.state = RunState.FAILED
                break
            elapsed = mono() - self.started_mono
            if self.state in (RunState.STARTING, RunState.WARMUP) and self.candles_1m:
                if elapsed >= self.cfg.run.warmup_sec:
                    self.state = RunState.ACTIVE
                    self.active_start_mono = mono()
                    log.info("ACTIVE başladı — hedef %.0fs", self.cfg.run.duration_sec)
                    self.events_log.write("PHASE_ACTIVE", elapsed_sec=round(elapsed, 3))
            if (self.state is RunState.ACTIVE and self.active_start_mono
                    and mono() - self.active_start_mono >= self.cfg.run.duration_sec):
                self.state = RunState.DRAINING
                self.drain_start_mono = mono()
                log.info("DRAIN başladı — yeni giriş yok, %.0fs", self.cfg.run.drain_sec)
                self.events_log.write("PHASE_DRAIN")
            if mono() >= end:
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    # ---------------- görevler ----------------
    async def _task_warmup(self) -> None:
        """Sembol evreni + geçmiş mum yüklemesi. Sonra periyodik yenileme."""
        assert self.market and self.session
        self.state = RunState.WARMUP
        for venue in self.market.reachable_venues:
            try:
                syms = (self.cfg.run.symbols_override or
                        await self.market.universe(venue, self.cfg.run.symbols_per_venue))
                self.symbols_by_venue[venue] = syms
                log.info("%s: %d sembol yüklendi", venue, len(syms))
            except Exception as e:
                log.warning("%s evren alınamadı: %s", venue, str(e)[:120])
                self.symbols_by_venue[venue] = []
        await self._refresh_candles(initial=True)
        self.events_log.write("WARMUP_DONE",
                              symbols=sum(len(v) for v in self.symbols_by_venue.values()),
                              candle_series=len(self.candles_1m))
        # görev bitmez: periyodik mum yenilemeyi sürdürür
        while not self._stop.is_set():
            await asyncio.sleep(self.cfg.run.candle_refresh_sec)
            await self._refresh_candles(initial=False)

    async def _refresh_candles(self, initial: bool = False) -> None:
        assert self.market
        with self.timers["candle_refresh"]:
            sem = asyncio.Semaphore(6)

            async def one(venue: str, sym: str) -> None:
                async with sem:
                    try:
                        cs = await self.market.candles(
                            venue, sym, self.cfg.run.candle_interval,
                            self.cfg.run.candle_limit)
                        if not cs:
                            return
                        key = f"{venue}:{sym}"
                        self.candles_1m[key] = cs
                        a = indicators.atr(cs, 14)
                        if a:
                            self.atr_by_symbol[sym] = a
                        if initial:
                            self.detector.seed_minute_candles(venue, sym, cs)
                        else:
                            st = self.detector.state(venue, sym)
                            last = cs[-1]
                            st.last_volume_ms = max(st.last_volume_ms, last.open_ms)
                            st.vol_24h_usd = sum(c.quote_volume for c in cs[-60:]) * 24.0
                        if self.cfg.policy.require_mtf and initial:
                            try:
                                c15 = await self.market.candles(venue, sym, "15m", 80)
                                if c15:
                                    self.candles_15m[key] = c15
                            except Exception:
                                pass
                    except Exception as e:
                        log.debug("mum alınamadı %s %s: %s", venue, sym, str(e)[:80])

            jobs = [one(v, s) for v, syms in self.symbols_by_venue.items() for s in syms]
            if jobs:
                await asyncio.gather(*jobs)
            self.supervisor.beat("data_progress")

    async def _task_market_poll(self) -> None:
        """Quote + funding tazeleme. WS olmayan ortamda tick yerine geçer."""
        assert self.market
        while not self._stop.is_set():
            with self.timers["quote_refresh"]:
                sem = asyncio.Semaphore(8)

                async def one(venue: str, sym: str) -> None:
                    async with sem:
                        q = await self.market.quote(venue, sym)
                        if q:
                            self.executor.on_quote(q)
                            self.counters["quote_ok"] += 1
                            if not self.cfg.run.use_websocket and self.cfg.run.rest_tick_fallback:
                                t = Tick(venue, sym, q.mid, 0.0, q.ts_ms, False)
                                self._on_tick(t)
                        else:
                            self.counters["quote_fail"] += 1

                # Bütçe: her çevrimde sınırlı sayıda sembol, döngüsel tarama.
                # Açık pozisyonlar HER çevrimde tazelenir (risk için zorunlu).
                quota = self.cfg.run.quote_symbols_per_cycle
                # Position alanı "exchange" (venue değil). Açık pozisyon
                # varken bu satır AttributeError verip quote görevini
                # öldürürdü; regresyon testiyle korunuyor.
                open_syms = {(getattr(p, "exchange", ""), p.symbol)
                             for p in self.executor.positions.values()
                             if getattr(p, "closed_ms", None) in (None, 0)}
                picked: list[tuple[str, str]] = []
                for v, syms in self.symbols_by_venue.items():
                    pri = [(v, x) for x in syms if (v, x) in open_syms]
                    rest = [x for x in syms if (v, x) not in open_syms]
                    take = max(0, quota - len(pri))
                    if rest and take:
                        i = self._quote_cursor.get(v, 0)
                        sel = [rest[(i + k) % len(rest)] for k in range(min(take, len(rest)))]
                        self._quote_cursor[v] = (i + take) % len(rest)
                        pri += [(v, x) for x in sel]
                    picked += pri
                jobs = [one(v, x) for v, x in picked]
                if jobs:
                    await asyncio.gather(*jobs)
                # funding — seyrek
                if self.counters["quote_ok"] and int(mono()) % 60 < 5:
                    for v, syms in self.symbols_by_venue.items():
                        for s in syms[:10]:
                            f = await self.market.funding(v, s)
                            self.funding_cache[f"{v}:{s}"] = f
            await asyncio.sleep(self.cfg.run.quote_refresh_sec)

    async def _task_ws(self, venue: str) -> None:
        assert self.session
        # evren hazır olana kadar bekle
        for _ in range(120):
            if self.symbols_by_venue.get(venue):
                break
            await asyncio.sleep(0.5)
        syms = self.symbols_by_venue.get(venue) or []
        if not syms:
            log.warning("%s için sembol yok; WS başlatılmadı", venue)
            while not self._stop.is_set():
                await asyncio.sleep(1.0)
            return
        feed = WSFeed(venue, syms, self._on_tick, self.market.health[venue])
        self.feeds.append(feed)
        try:
            await feed.run(self.session)
        finally:
            feed.stop()

    async def _task_strategy(self) -> None:
        """Açık pozisyon yönetimi + periyodik genişlik + equity kaydı."""
        while not self._stop.is_set():
            if self.state in (RunState.ACTIVE, RunState.DRAINING):
                with self.timers["execution"]:
                    closed = self.executor.manage_open(now_ms(), self.atr_by_symbol)
                for pid in closed:
                    p = self.executor.positions.get(pid)
                    if p:
                        self.store.write_position(p)
                        self.events_log.write("POSITION_CLOSED", **p.to_dict())
                        if self.state is RunState.DRAINING:
                            self.drain_closed.append(pid)
                eq = self.executor.equity_snapshot()
                self.store.write_equity(eq["realized_equity"], eq["unrealized"],
                                        eq["open_positions"])
                with self.timers["breadth_update"]:
                    self.detector.update_breadth()
            self.supervisor.beat("strategy_cycle")
            await asyncio.sleep(1.0)

    async def _task_supervision(self) -> None:
        """Süreklilik, heartbeat, lease ve sağlık kaydı."""
        while not self._stop.is_set():
            ev = self.continuity.beat(1.0)
            if ev:
                self.supervisor.raise_alarm(ev.kind, ev.detail)
                self.events_log.write(ev.kind, **ev.to_dict())
            self.supervisor.check_heartbeats()
            self.store.renew_lease()   # hata yutulmaz -> görev ölümü
            snap = self.health_snapshot()
            self.health_log.write("HEALTH", **snap)
            self.store.commit()
            await asyncio.sleep(1.0)

    # ---------------- tick hattı ----------------
    def _on_tick(self, tick: Tick) -> None:
        """WS callback — senkron, hızlı olmalı. Ağır iş async göreve atılır."""
        self.counters["ticks"] += 1
        with self.timers["tick_total"]:
            self.executor.on_tick(tick)
            with self.timers["detector_eval"]:
                sig = self.detector.feed_tick(tick)
            if sig is None:
                return
            self.counters["signals"] += 1
            self.events_log.write("SIGNAL", **sig.to_dict())
            if self.state is not RunState.ACTIVE:
                self.events_log.write("SIGNAL_IGNORED_PHASE", state=self.state.value,
                                      symbol=sig.symbol)
                return
            if self.supervisor.entries_halted:
                return
            if self.cfg.run.mode is Mode.OBSERVE:
                return
            # async karar hattını bloke etmeden başlat
            asyncio.create_task(self._handle_signal(sig))

    async def _handle_signal(self, sig: Signal) -> None:
        decision_id = f"dec_{uuid.uuid4().hex[:16]}"
        t0 = mono()
        key = f"{sig.exchange}:{sig.symbol}"
        quote = self.executor.quotes.get(sig.symbol)
        c1 = self.candles_1m.get(key, [])
        c15 = self.candles_15m.get(key)
        funding = self.funding_cache.get(key)

        with self.timers["policy_eval"]:
            ok, gates, metrics = self.policy.evaluate(sig, quote, c1, c15, funding)
        decision = Decision(
            decision_id=decision_id, ts_ms=sig.ts_ms, exchange=sig.exchange,
            symbol=sig.symbol,
            closed_bar_key=metrics.get("closed_bar_key",
                                       closed_bar_key(sig.symbol, sig.ts_ms)),
            candidate_side=metrics.get("entry_side", sig.side.value), gates=gates,
        )
        self.counters["decisions"] += 1

        if not ok:
            decision.accepted = False
            decision.reject_code = decision.first_reject
            self.counters["rejected"] += 1
            self._record(decision, t0)
            return

        # portföy riski
        from ..core.types import Side
        side = Side(metrics["entry_side"])
        rgates = self.risk.check_portfolio(sig.symbol, side,
                                          self.executor.open_positions)
        decision.gates.extend(rgates)
        if any(not g.passed for g in rgates):
            decision.accepted = False
            decision.reject_code = decision.first_reject
            self.counters["risk_blocks"] += 1
            self.counters["rejected"] += 1
            self._record(decision, t0)
            return

        # 20 YZ konseyi
        with self.timers["council_eval"]:
            verdict = await self.council.evaluate(sig, metrics, self.session)
        decision.ai_council = verdict.to_dict()
        if not verdict.approved and self.cfg.council.veto_enabled:
            decision.gates.append(GateResult(
                "ai_council", False, verdict.reject_code or "COUNCIL_REJECT",
                verdict.reason, verdict.score, self.cfg.council.min_consensus_score))
            decision.accepted = False
            decision.reject_code = decision.first_reject
            self.counters["council_vetoes"] += 1
            self.counters["rejected"] += 1
            self._record(decision, t0)
            return

        # boyut + emir
        atr_abs = self.atr_by_symbol.get(sig.symbol)
        if not atr_abs:
            decision.gates.append(GateResult("sizing", False, "ATR_MISSING",
                                             "ATR yok, boyut hesaplanamadı"))
            decision.accepted = False
            decision.reject_code = "ATR_MISSING"
            self.counters["rejected"] += 1
            self._record(decision, t0)
            return
        plan = self.risk.plan(side, sig.price, atr_abs)
        if plan is None:
            decision.gates.append(GateResult("sizing", False, "SIZE_TOO_SMALL",
                                             "Hesaplanan boyut minimumun altında"))
            decision.accepted = False
            decision.reject_code = "SIZE_TOO_SMALL"
            self.counters["rejected"] += 1
            self._record(decision, t0)
            return

        with self.timers["execution"]:
            order = self.executor.submit_entry(
                sig.symbol, sig.exchange, side, plan, sig.signal_id,
                decision.closed_bar_key, sig.ts_ms)
        if order is None:
            decision.gates.append(GateResult("order_submit", False, "SUBMIT_REJECTED",
                                             "Quote yok veya pending limiti"))
            decision.accepted = False
            decision.reject_code = "SUBMIT_REJECTED"
            self.counters["rejected"] += 1
            self._record(decision, t0)
            return

        decision.accepted = True
        decision.order_id = order.order_id
        self.counters["accepted"] += 1
        with self.timers["state_write"]:
            self.store.write_order(order)
        self.events_log.write("ORDER_SUBMITTED", **order.to_dict())
        self._record(decision, t0)

    def _record(self, d: Decision, t0: float) -> None:
        d.latency_ms = (mono() - t0) * 1000.0
        with self.timers["state_write"]:
            self.store.write_decision(d)
        self.decisions_log.write("DECISION", **d.to_dict())

    # ---------------- sağlık / final ----------------
    def health_snapshot(self) -> dict[str, Any]:
        eq = self.executor.equity_snapshot()
        return {
            "run_id": self.run_id, "state": self.state.value,
            "mode": self.cfg.run.mode.value,
            "elapsed_mono_sec": round(mono() - self.started_mono, 3) if self.started_mono else 0.0,
            "counters": dict(self.counters),
            "detector": self.detector.summary(),
            "council_mode": self.council.mode,
            "equity": eq,
            "continuity": self.continuity.summary(),
            "entries_halted": self.supervisor.entries_halted,
            "task_failures": dict(self.supervisor.failures),
            "market": self.market.health_report() if self.market else {},
        }

    async def _finalize(self, forced_reason: str = "") -> dict[str, Any]:
        self.finished_mono = mono()
        log.info("Kapanış: görevler durduruluyor")
        self.supervisor.begin_shutdown()
        for f in self.feeds:
            f.stop()
        # Drain'de açık pozisyonları kapat (yalnız normal kapanışta)
        if self.state in (RunState.ACTIVE, RunState.DRAINING, RunState.COMPLETED):
            for p in list(self.executor.open_positions):
                self.executor.close_position(p, "RUN_END_DRAIN")
                self.store.write_position(p)
                self.events_log.write("POSITION_CLOSED_DRAIN", **p.to_dict())
        await self.supervisor.cancel_all()

        if forced_reason:
            self.state = RunState.FAILED
        elif self.supervisor.failures:
            self.state = RunState.FAILED
        elif not self.continuity.is_continuous:
            self.state = RunState.DISCONTINUOUS
        else:
            self.state = RunState.COMPLETED

        for p in self.executor.positions.values():
            self.store.write_position(p)
        self.store.commit()

        active = ((self.drain_start_mono or self.finished_mono)
                  - (self.active_start_mono or self.started_mono))
        result = {
            "run_id": self.run_id,
            "version": "1.0.0",
            "mode": self.cfg.run.mode.value,
            "run_status": self.state.value,
            "profile": self.cfg.run.profile,
            "filters_relaxed": self.cfg.run.filters_relaxed,
            "evidence_class": ("LIFECYCLE_DIAGNOSTIC_NOT_NATURAL"
                               if self.cfg.run.filters_relaxed
                               else "NATURAL_PAPER"),
            "forced_reason": forced_reason,
            "real_money_approved": False,
            "real_orders_sent": 0,
            "timing": {
                "total_monotonic_sec": round(self.finished_mono - self.started_mono, 3),
                "active_sec_estimated": round(max(0.0, active), 3),
                "drain_sec": self.cfg.run.drain_sec,
                "active_window_completed": bool(
                    self.active_start_mono and
                    (self.drain_start_mono or self.finished_mono) - self.active_start_mono
                    >= self.cfg.run.duration_sec - 1.0),
                "note": ("Monotonic ölçüm. Süreksizlik varsa COMPLETED yazılmaz. "
                         "Bütün VM durduğunda gözlemci de durur; uptime garantisi yok."),
            },
            "acceptance_criteria": self._criteria(),
            "counters": dict(self.counters),
            "detector": self.detector.summary(),
            "policy": self.policy.state.summary(),
            "execution": self.executor.summary(),
            "ai_council": self.council.status(),
            "ai_registry": registry_status(),
            "market_data": self.market.health_report() if self.market else {},
            "continuity": self.continuity.summary(),
            "supervision": self.supervisor.summary(),
            "state_store": self.store.summary(),
            "timers": {k: t.stats() for k, t in self.timers.items()},
            "ws": [{"venue": f.venue, "messages": f.health.ws_messages,
                    "reconnects": f.health.ws_reconnects,
                    "json_parse_calls": f.json_parse_calls,
                    "json_parse_sec": round(f.json_parse_sec, 4)} for f in self.feeds],
            "honesty": {
                "data": "REAL_MARKET_DATA",
                "orders": "PAPER_ONLY_NO_EXCHANGE_ORDERS",
                "ai_mode": self.council.mode,
                "profitability_claim": False,
                "note": ("Küçük PAPER örneklemi kârlılık veya yürütme güvenilirliği "
                         "kanıtı değildir. Açık unrealized gerçekleşmiş kâr değildir. "
                         "Stop mesafesi maksimum zarar garantisi değildir."),
            },
        }
        (self.out / "SONUC.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.set_meta("final_status", result["run_status"])
        self.store.set_meta("result_summary", {
            "counters": result["counters"], "equity": result["execution"]["equity"]})
        self.events_log.write("RUN_END", status=result["run_status"])
        for lg in (self.decisions_log, self.events_log, self.health_log):
            lg.close()
        self.store.close()
        log.info("Run bitti: %s — %s", result["run_status"], self.out)
        return result


def now_ms_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")