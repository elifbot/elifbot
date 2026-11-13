# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — Ana Birleşik Gerçek Zamanlı Tüm-Futures İşlem Motoru (engine.py)
================================================================================
Kapsadığı 4 Vadeli İşlem Segmenti (1.200+ Kontrat):
  1. Binance USDⓈ-M Vadeli İşlemler (USDT Perp + USDC Perp + Teslimatlı Kontratlar)
  2. Binance COIN-M Vadeli İşlemler (USD_PERP + Teslimatlı COIN-M Kontratlar)
  3. OKX Süresiz SWAP (USDT-SWAP + USDC-SWAP + USD-SWAP)
  4. OKX Vadeli FUTURES (Haftalık, İki Haftalık, Çeyreklik, İki Çeyreklik Kontratlar)

Tüm Sabit Kullanıcı Kuralları:
  - $1,000.00 Çapraz Marjin (CROSS — İzole Değil) Kasa
  - $50.00 Giriş × 10x Kaldıraç = $500.00 Büyüklük
  - Sınırsız Açık Pozisyon (max_positions = 0)
  - Kesin -$20.00 Net Zarar Kes (Komisyon + Kayma Dahil)
  - 5 Kademeli Otonom AI Kâr Motoru + 20 Denetçili AI Konsey + Atomik SQLite Defter
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from .ai_council import CouncilVerdict, OmegaAICouncil
from .config import OmegaConfig
from .contracts import CostModel, normalize_exchange_and_symbol
from .ledger import AtomicOmegaLedger, LedgerIntegrityReport
from .microstructure import OmegaFeatureSnapshot, OmegaSymbolTape
from .profit_engine import AutonomousProfitEngine, OmegaPosition


class AcarbotOmegaEngine:
    """Sıfırdan inşa edilmiş kurumsal ACARBOT OMEGA çekirdek motoru."""

    def __init__(
        self,
        cfg: Optional[OmegaConfig] = None,
        on_live_open: Optional[Callable[[OmegaPosition], None]] = None,
        on_live_close: Optional[Callable[[OmegaPosition, float, str], None]] = None,
    ) -> None:
        self.cfg = cfg or OmegaConfig()
        self.cfg.validate()

        self.lock = threading.RLock()
        self.cost_model = CostModel(self.cfg)
        self.council = OmegaAICouncil(self.cfg)
        self.profit_engine = AutonomousProfitEngine(self.cfg)
        self.ledger = AtomicOmegaLedger(
            db_path=self.cfg.sqlite_db_path,
            initial_equity_usd=self.cfg.initial_equity_usd,
        )

        self.on_live_open = on_live_open
        self.on_live_close = on_live_close

        self.tapes: Dict[str, OmegaSymbolTape] = {}
        self.positions: Dict[str, OmegaPosition] = {}
        self.active_symbol_keys: Dict[str, str] = {}     # "ex:sym" -> pos_id
        self.last_base_entry_ts: Dict[str, float] = {}   # base_asset -> ts (çift kontrat koruması)
        self.cooldown_until: Dict[str, float] = {}
        self.closed_trades: Deque[Dict[str, Any]] = deque(maxlen=400)
        self.events: Deque[Dict[str, Any]] = deque(maxlen=200)
        self.veto_counters: Dict[str, int] = {}

        self.realized_pnl_usd: float = 0.0
        self.total_ticks: int = 0
        self.trading_enabled: bool = True
        self.started_ts: float = time.time()

        self._log(
            "OMEGA_HAZIR",
            "ACARBOT OMEGA v1.0 aktif: $1,000 Çapraz Kasa | $50×10x | Sınırsız İşlem | "
            "-$20 Net SL | 20-Denetçili AI Konsey | 5-Kademeli Otonom Kâr | Atomik SQLite Defter.",
        )

    def _log(self, kind: str, text: str) -> None:
        self.events.appendleft(
            {
                "ts": round(time.time(), 3),
                "time": time.strftime("%H:%M:%S"),
                "kind": kind,
                "text": text,
            }
        )

    def unrealized_pnl_usd(self) -> float:
        return sum(p.net_pnl_usd for p in self.positions.values())

    def live_equity_usd(self) -> float:
        return self.cfg.initial_equity_usd + self.realized_pnl_usd + self.unrealized_pnl_usd()

    def used_margin_usd(self) -> float:
        return len(self.positions) * self.cfg.margin_per_trade_usd

    def ingest_ticks(self, ticks: List[Dict[str, Any]]) -> int:
        """Gerçek zamanlı borsa verilerini işler, açık pozisyonları yönetir ve yeni sinyalleri denetler."""
        opened = 0
        now_wall = time.time()

        with self.lock:
            for item in ticks:
                raw_ex = str(item.get("exchange") or "binance")
                raw_sym = str(item.get("symbol") or "")
                if not raw_sym:
                    continue
                px = float(item.get("price") or 0.0)
                if px <= 0:
                    continue

                ex, sym = normalize_exchange_and_symbol(raw_ex, raw_sym)
                ts = float(item.get("ts") or now_wall)
                if ts > 1e11:
                    ts /= 1000.0

                key = f"{ex}:{sym}"
                tape = self.tapes.get(key)
                if tape is None:
                    tape = OmegaSymbolTape(ex, sym, ref_price=px)
                    self.tapes[key] = tape

                tape.ingest(
                    ts=ts,
                    price=px,
                    quote_vol_24h=float(item.get("quote_vol_24h") or 0.0),
                    pct_24h=float(item.get("pct_24h") or 0.0),
                    kline_ts=int(item.get("kline_ts") or 0),
                    kline_q_usd=float(item["kline_q"]) if item.get("kline_q") is not None else -1.0,
                    kline_buy_usd=float(item["kline_buy_q"]) if item.get("kline_buy_q") is not None else -1.0,
                    explicit_delta_usd=float(item["delta_usd"]) if item.get("delta_usd") is not None else -1.0,
                    explicit_buy_usd=float(item["buy_usd"]) if item.get("buy_usd") is not None else -1.0,
                    spread_bps=float(item["spread_bps"]) if item.get("spread_bps") is not None else None,
                    funding_rate=float(item["funding_rate"]) if item.get("funding_rate") is not None else None,
                    oi_change_pct=float(item["oi_change_pct"]) if item.get("oi_change_pct") is not None else None,
                    book_imbalance=float(item["book_imbalance"]) if item.get("book_imbalance") is not None else None,
                    liquidation_pressure=float(item["liquidation_pressure"])
                    if item.get("liquidation_pressure") is not None
                    else None,
                )
                self.total_ticks += 1

                snap = tape.snapshot(self.cfg.burst_window_sec)

                # 1. Açık pozisyon varsa her tick'te -$20 SL ve 5 kademeli AI kâr kontrolü yap
                active_pid = self.active_symbol_keys.get(key)
                if active_pid and active_pid in self.positions:
                    pos = self.positions[active_pid]
                    dec = self.profit_engine.evaluate_tick(pos, tape.spec, snap, ts)
                    if dec.should_close:
                        self._execute_close(pos, dec.exit_price, dec.final_net_pnl_usd, dec.reason, ts)
                elif self.trading_enabled:
                    if self._evaluate_and_open(tape, snap, ts):
                        opened += 1

        return opened

    def _evaluate_and_open(self, tape: OmegaSymbolTape, snap: OmegaFeatureSnapshot, now_ts: float) -> bool:
        key = tape.key
        if key in self.active_symbol_keys:
            return False
        if self.cooldown_until.get(key, 0.0) > now_ts:
            return False
        if snap.quote_vol_24h > 0 and snap.quote_vol_24h < self.cfg.min_24h_vol_usd:
            return False
        if len(tape.ticks) < 3:
            return False

        # Aynı saniyede aynı baz coine (örn. BTCUSDT + BTCUSDC + BTC-USDT-SWAP) mükerrer girişi önle
        if self.cfg.deduplicate_base_asset_sec > 0:
            last_b = self.last_base_entry_ts.get(snap.base_asset, 0.0)
            if (now_ts - last_b) < self.cfg.deduplicate_base_asset_sec:
                return False

        # Not: max_positions == 0 -> Yapay adet sınırı YOK! Sınırsız işlem açılabilir.
        if self.cfg.max_positions > 0 and len(self.positions) >= self.cfg.max_positions:
            return False

        # Yapay adet sınırı değil; borsanın gerçek çapraz marjin yeterlilik kontrolü:
        # Serbest teminat yetmiyorsa emir borsada reddedilir -> önceden engelle (gerçekçi muhasebe).
        if self.cfg.enforce_margin_availability:
            equity = self.live_equity_usd()
            free_margin = equity - self.used_margin_usd()
            if free_margin < self.cfg.margin_per_trade_usd or (
                (self.used_margin_usd() + self.cfg.margin_per_trade_usd) > equity * self.cfg.margin_utilization_cap
            ):
                self.veto_counters["MARJIN_YETERSIZ_VETO"] = self.veto_counters.get("MARJIN_YETERSIZ_VETO", 0) + 1
                return False

        side, trigger_kind = self.council.detect_candidate_direction(snap)
        if side == 0:
            return False

        qty, eff_notional = tape.spec.compute_order_quantity(self.cfg.notional_per_trade_usd, snap.price)
        costs = self.cost_model.estimate(
            notional_usd=eff_notional,
            spread_bps=snap.spread_bps,
            funding_rate=snap.funding_rate or 0.0,
            side=side,
        )

        verdict: CouncilVerdict = self.council.evaluate(
            snap=snap,
            side=side,
            trigger_kind=trigger_kind,
            costs=costs,
            notional_usd=eff_notional,
        )
        if not verdict.approved:
            for v in verdict.veto_reasons:
                tag = v.split(" ", 1)[0]
                self.veto_counters[tag] = self.veto_counters.get(tag, 0) + 1
            return False

        hard_stop_px = self.cost_model.solve_exact_net_stop_price(
            spec=tape.spec,
            entry_price=snap.price,
            side=side,
            notional_usd=eff_notional,
            costs=costs,
        )
        safe_liq, est_liq_px = self.cost_model.verify_stop_before_liquidation(
            entry_price=snap.price,
            stop_price=hard_stop_px,
            side=side,
        )
        if not safe_liq:
            self.veto_counters["LIQ_BUFFER_VETO"] = self.veto_counters.get("LIQ_BUFFER_VETO", 0) + 1
            return False

        # Hacim çöküşü dönüş sinyalini tükettikten sonra zirve sayacını sıfırla
        if "HACIM_COKUSU" in trigger_kind:
            tape.peak_burst_mult_60s = 1.0

        pid = uuid.uuid4().hex[:12]
        intent_id = self.ledger.prepare_intent(pid, "OPEN", tape.exchange, tape.symbol)
        try:
            pos = OmegaPosition(
                id=pid,
                exchange=tape.exchange,
                symbol=tape.symbol,
                segment=tape.spec.segment,
                kind=tape.spec.kind,
                base_asset=snap.base_asset,
                side=side,
                qty=qty,
                entry_price=snap.price,
                mark_price=snap.price,
                margin_usd=self.cfg.margin_per_trade_usd,
                leverage=self.cfg.leverage,
                notional_usd=eff_notional,
                hard_stop_price=hard_stop_px,
                est_liquidation_price=round(est_liq_px, 8),
                roundtrip_fee_usd=costs.fee_only_usd,
                dynamic_floor_pnl_usd=-self.cfg.hard_stop_loss_usd,
                opened_ts=now_ts,
                trigger_type=trigger_kind,
                council_score=verdict.approval_score,
                edge_to_cost_ratio=verdict.edge_to_cost_ratio,
                net_pnl_usd=-costs.fee_only_usd,
                entry_snapshot=snap,
            )
            self.positions[pid] = pos
            self.active_symbol_keys[key] = pid
            self.last_base_entry_ts[snap.base_asset] = now_ts
            self.ledger.commit_open(intent_id, pos)

            if self.on_live_open and not self.cfg.paper_mode:
                self.on_live_open(pos)

            self._log(
                "OMEGA_GİRİŞ",
                f"[{pos.segment}] {pos.side_label} {pos.symbol} @ {pos.entry_price:.6g} | "
                f"Konsey: {verdict.auditor_votes_for}/20 ({verdict.approval_score:.2f}) | "
                f"Edge/Maliyet: {verdict.edge_to_cost_ratio:.2f}x | -$20 SL @ {pos.hard_stop_price:.6g}",
            )
            return True
        except Exception:
            self.ledger.abort_intent(intent_id)
            raise

    def _execute_close(
        self,
        pos: OmegaPosition,
        exit_price: float,
        final_net_pnl_usd: float,
        reason: str,
        now_ts: float,
    ) -> None:
        key = f"{pos.exchange}:{pos.symbol}"
        intent_id = self.ledger.prepare_intent(pos.id, "CLOSE", pos.exchange, pos.symbol)
        try:
            self.positions.pop(pos.id, None)
            self.active_symbol_keys.pop(key, None)
            self.cooldown_until[key] = now_ts + self.cfg.symbol_cooldown_sec
            self.realized_pnl_usd += final_net_pnl_usd

            rec = self.ledger.commit_close(intent_id, pos, exit_price, final_net_pnl_usd, reason, now_ts)
            self.closed_trades.appendleft(rec)

            # Online SGD Öğreniciyi güncelle
            self.council.learn_from_closed_trade(
                entry_snap=pos.entry_snapshot,
                side=pos.side,
                edge_ratio=pos.edge_to_cost_ratio,
                net_pnl_usd=final_net_pnl_usd,
            )

            if self.on_live_close and not self.cfg.paper_mode:
                self.on_live_close(pos, exit_price, reason)

            self._log(
                "OMEGA_ÇIKIŞ",
                f"[{pos.segment}] {pos.side_label} {pos.symbol} -> {reason} | "
                f"Net: {final_net_pnl_usd:+.2f}$ (Zirve: {pos.peak_pnl_usd:+.2f}$) | "
                f"Kasa: ${self.live_equity_usd():.2f}",
            )
        except Exception:
            self.ledger.abort_intent(intent_id)
            raise

    def verify_ledger(self) -> LedgerIntegrityReport:
        return self.ledger.verify_integrity()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            seg_counts = {"BINANCE_USDM": 0, "BINANCE_COINM": 0, "OKX_SWAP": 0, "OKX_FUTURES": 0}
            for t in self.tapes.values():
                seg_counts[t.spec.segment] = seg_counts.get(t.spec.segment, 0) + 1

            pnls = [float(c["net_pnl_usd"]) for c in self.closed_trades]
            wins = [x for x in pnls if x > 0]
            losses = [x for x in pnls if x <= 0]
            pf = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) < 0 else None

            return {
                "engine": "ACARBOT_OMEGA_v1.0",
                "universe": {
                    "total_contracts": len(self.tapes),
                    "segments": seg_counts,
                    "total_ticks": self.total_ticks,
                },
                "account": {
                    "margin_mode": "CROSS (ÇAPRAZ)",
                    "initial_equity_usd": self.cfg.initial_equity_usd,
                    "live_equity_usd": round(self.live_equity_usd(), 2),
                    "realized_pnl_usd": round(self.realized_pnl_usd, 2),
                    "unrealized_pnl_usd": round(self.unrealized_pnl_usd(), 2),
                    "margin_per_trade_usd": self.cfg.margin_per_trade_usd,
                    "leverage": self.cfg.leverage,
                    "used_margin_usd": round(self.used_margin_usd(), 2),
                    "open_count": len(self.positions),
                    "max_positions": "SINIRSIZ",
                    "closed_count": len(pnls),
                    "win_rate": round(len(wins) / len(pnls), 3) if pnls else 0.0,
                    "profit_factor": pf,
                },
                "ai_council": {
                    "samples_learned": self.council.samples_learned,
                    "learned_weights": {k: round(v, 4) for k, v in self.council.learned_weights.items()},
                    "veto_counts": dict(self.veto_counters),
                },
                "open_positions": [p.to_public_dict() for p in self.positions.values()],
                "closed_trades": list(self.closed_trades)[:50],
                "events": list(self.events)[:40],
            }

    def shutdown(self) -> None:
        self.ledger.close()


class OmegaMultiMirrorStreamer:
    """
    4 Vadeli İşlem Segmentinin tamamına (Binance USDⓈ-M + COIN-M + OKX SWAP + OKX FUTURES)
    sansür/engel aşan yedekli aynalarla (binance.info, binance.me, binance.vision, coinall.ltd, okx.com)
    bağlanan asenkron canlı veri akış istemcisi.
    """

    BIN_USDM_URLS = [
        "wss://fstream.binance.com/ws/!ticker@arr",
        "wss://fstream.binance.info/ws/!ticker@arr",
        "wss://fstream.binance.me/ws/!ticker@arr",
        "wss://data-stream.binance.vision/ws/!ticker@arr",
    ]
    BIN_COINM_URLS = [
        "wss://dstream.binance.com/ws/!ticker@arr",
        "wss://dstream.binance.me/ws/!ticker@arr",
    ]
    OKX_PUB_URLS = [
        "wss://ws.okx.com/ws/v5/public",
        "wss://ws.coinall.ltd/ws/v5/public",
        "wss://ws.okx.com:8443/ws/v5/public",
    ]

    def __init__(self, engine: AcarbotOmegaEngine) -> None:
        self.engine = engine
        self.running = False

    async def run(self, duration_sec: int = 3600) -> None:
        import aiohttp

        self.running = True
        tasks = [
            asyncio.create_task(self._binance_loop(aiohttp, self.BIN_USDM_URLS, "binance", coinm_only=False)),
            asyncio.create_task(self._binance_loop(aiohttp, self.BIN_COINM_URLS, "binance_coinm", coinm_only=True)),
            asyncio.create_task(self._okx_loop(aiohttp)),
        ]
        try:
            await asyncio.sleep(duration_sec)
        finally:
            self.running = False
            for t in tasks:
                t.cancel()

    async def _binance_loop(self, aiohttp: Any, urls: List[str], ex_tag: str, coinm_only: bool) -> None:
        idx = 0
        while self.running:
            url = urls[idx % len(urls)]
            is_vision = "binance.vision" in url
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=20, timeout=8) as ws:
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type.name != "TEXT":
                                continue
                            arr = json.loads(msg.data)
                            if not isinstance(arr, list):
                                continue
                            now = time.time()
                            batch = []
                            for t in arr:
                                s = t.get("s", "")
                                px = float(t.get("c") or 0.0)
                                if not s or px <= 0:
                                    continue
                                if coinm_only and "USD_" not in s:
                                    continue
                                if is_vision and not (s.endswith("USDT") or s.endswith("USDC")):
                                    continue
                                raw_q = float(t.get("q") or 0.0)
                                q24 = raw_q * px if coinm_only else raw_q
                                if is_vision and q24 < self.engine.cfg.min_24h_vol_usd:
                                    continue
                                batch.append(
                                    {
                                        "exchange": ex_tag,
                                        "symbol": s,
                                        "price": px,
                                        "pct_24h": float(t.get("P") or 0.0),
                                        "quote_vol_24h": q24,
                                        "ts": now,
                                    }
                                )
                            if batch:
                                self.engine.ingest_ticks(batch)
            except Exception:
                idx += 1
                await asyncio.sleep(2.5)

    async def _okx_loop(self, aiohttp: Any) -> None:
        idx = 0
        while self.running:
            url = self.OKX_PUB_URLS[idx % len(self.OKX_PUB_URLS)]
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=20, timeout=8) as ws:
                        await ws.send_json(
                            {
                                "op": "subscribe",
                                "args": [
                                    {"channel": "instruments", "instType": "SWAP"},
                                    {"channel": "instruments", "instType": "FUTURES"},
                                ],
                            }
                        )
                        subscribed = set()
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type.name != "TEXT" or msg.data == "pong":
                                continue
                            payload = json.loads(msg.data)
                            ch = (payload.get("arg") or {}).get("channel")
                            if ch == "instruments":
                                fresh = [
                                    r["instId"]
                                    for r in (payload.get("data") or [])
                                    if r.get("instId") and r["instId"] not in subscribed
                                ]
                                for s in fresh:
                                    subscribed.add(s)
                                for i in range(0, len(fresh), 50):
                                    args = [{"channel": "tickers", "instId": x} for x in fresh[i : i + 50]]
                                    await ws.send_json({"op": "subscribe", "args": args})
                                    await asyncio.sleep(0.08)
                            elif ch == "tickers":
                                rows = payload.get("data") or []
                                if rows:
                                    r = rows[0]
                                    last = float(r.get("last") or 0.0)
                                    open24 = float(r.get("open24h") or 0.0)
                                    vol_ccy = float(r.get("volCcy24h") or 0.0)
                                    if last > 0:
                                        pct = ((last / open24) - 1.0) * 100.0 if open24 > 0 else 0.0
                                        self.engine.ingest_ticks(
                                            [
                                                {
                                                    "exchange": "okx",
                                                    "symbol": r["instId"],
                                                    "price": last,
                                                    "pct_24h": pct,
                                                    "quote_vol_24h": vol_ccy * last,
                                                    "ts": time.time(),
                                                }
                                            ]
                                        )
            except Exception:
                idx += 1
                await asyncio.sleep(2.5)


class OmegaCrossMarginCCXTExecutor:
    """Gerçek Borsa Çapraz Marjin (CROSS, 10x, Linear + Inverse) Emir Yürütücüsü."""

    def __init__(self, cfg: OmegaConfig) -> None:
        self.cfg = cfg
        self._clients: Dict[str, Any] = {}

    def _client(self, exchange: str) -> Any:
        if exchange in self._clients:
            return self._clients[exchange]
        import ccxt

        if exchange == "binance":
            c = ccxt.binance(
                {
                    "apiKey": os.getenv("BINANCE_API_KEY", ""),
                    "secret": os.getenv("BINANCE_API_SECRET", ""),
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                }
            )
        elif exchange == "binance_coinm":
            c = ccxt.binancecoinm(
                {
                    "apiKey": os.getenv("BINANCE_API_KEY", ""),
                    "secret": os.getenv("BINANCE_API_SECRET", ""),
                    "enableRateLimit": True,
                }
            )
        elif exchange == "okx":
            c = ccxt.okx(
                {
                    "apiKey": os.getenv("OKX_API_KEY", ""),
                    "secret": os.getenv("OKX_API_SECRET", ""),
                    "password": os.getenv("OKX_PASSPHRASE", ""),
                    "enableRateLimit": True,
                }
            )
        else:
            raise ValueError(f"Desteklenmeyen borsa: {exchange}")
        c.load_markets()
        self._clients[exchange] = c
        return c

    def execute_open(self, pos: OmegaPosition) -> None:
        c = self._client(pos.exchange)
        # Kesinlikle İZOLE DEĞİL -> ÇAPRAZ (CROSS) Marjin ve 10x Kaldıraç zorla!
        try:
            c.set_margin_mode("cross", pos.symbol)
        except Exception:
            pass
        try:
            c.set_leverage(self.cfg.leverage, pos.symbol, {"mgnMode": "cross"} if pos.exchange == "okx" else {})
        except Exception:
            pass
        order_side = "buy" if pos.side > 0 else "sell"
        params = {"tdMode": "cross"} if pos.exchange == "okx" else {}
        c.create_order(pos.symbol, "market", order_side, pos.qty, None, params)

    def execute_close(self, pos: OmegaPosition, _exit_px: float, _reason: str) -> None:
        c = self._client(pos.exchange)
        order_side = "sell" if pos.side > 0 else "buy"
        params = {"tdMode": "cross", "reduceOnly": True} if pos.exchange == "okx" else {"reduceOnly": True}
        c.create_order(pos.symbol, "market", order_side, pos.qty, None, params)
