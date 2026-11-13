"""KRIPTO-BOT v7.2 — Karanlık Temalı Gerçek Zamanlı Komuta & İzleme Paneli (Web UI).

İki çalışma modu:
  1. `ProductionBotHub` (varsayılan): Ana botun `bot_state.db` durumunu salt-okunur okur,
     kontrol eylemlerini (`kill_switch`, `toggle_pause`, `reset_breaker`, `run_gc`, `close_symbol`)
     SQLite `command_queue` üzerinden güvenli biçimde ana bota iletir.
  2. `LiveBotHub` (`DASHBOARD_DEMO=1`): İzole `dashboard_demo.db` üzerinde sentetik akışla
     tüm alt sistemleri (indikatör, order-flow, VPVR, ML, risk, executor) canlı simüle eder.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import math
import os
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from aiohttp import web

from .alerts import MultiChannelAlerter
from .arbitrage import ArbitrageEngine
from .circuit_breaker import CircuitBreaker
from .config import BASE_DIR, load_config
from .exchanges import PaperBroker
from .executor import Executor
from .equity_reporting import safe_unrealized, equity_or_none
from .health import build_health_payload, build_prometheus_metrics
from .indicators import Indicators, indicator_score
from .ml_predictor import MLPredictor
from .moneyflow import MoneyFlow
from .news import NewsEngine
from .risk import Position, RiskManager
from .security import mask_secrets, register_secret, safe_exception_msg
from .sizing import PositionSizer
from .state_store import StateStore
from .strategy import Strategy


class DashboardSimBroker:
    """Demo paneli için ağ bağlantısı gerektirmeyen sanal borsa bağdaştırıcısı."""

    mode = "paper"
    paper_funding_enabled = False

    def __init__(self, balance_usdt: float = 10_000.0):
        self.paper = PaperBroker(balance_usdt=balance_usdt)
        self.prices: dict[str, float] = {
            "BTC/USDT": 68_500.0,
            "ETH/USDT": 3_450.0,
            "SOL/USDT": 165.0,
        }
        self._default_primary = "binance"
        self._active_primary = "binance"
        self.failover_count = 0
        self._timeouts = {"binance": 0, "okx": 0}
        self._degraded_until = {"binance": 0.0, "okx": 0.0}

    @property
    def primary(self) -> str:
        if time.time() >= self._degraded_until.get(self._default_primary, 0.0):
            self._active_primary = self._default_primary
        return self._active_primary

    def choose_symbol_exchange(self, symbol: str, preferred: str | None = None) -> str:
        return preferred or self.primary

    def exchange_health_snapshot(self) -> dict:
        now = time.time()
        return {
            "active_primary": self.primary,
            "default_primary": self._default_primary,
            "failover_active": self.primary != self._default_primary,
            "failover_count": self.failover_count,
            "exchanges": {
                name: {
                    "healthy": now >= self._degraded_until.get(name, 0.0),
                    "consecutive_timeouts": self._timeouts.get(name, 0),
                    "total_timeouts": self._timeouts.get(name, 0),
                    "cooldown_remaining_sec": round(
                        max(0.0, self._degraded_until.get(name, 0.0) - now), 1
                    ),
                }
                for name in ("binance", "okx")
            },
        }

    async def fetch_balance_usdt(self) -> float:
        return self.paper.balance

    async def fetch_price(self, symbol: str, exchange: str | None = None) -> float:
        return float(self.prices.get(symbol, 100.0))

    async def fetch_open_positions(self, exchange: str | None = None) -> list[dict]:
        return []

    async def market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        exchange: str | None = None,
        reduce_only: bool = False,
    ) -> dict:
        px = price_hint or self.prices.get(symbol, 100.0)
        return self.paper.market_order(
            symbol,
            side,
            qty,
            px,
            exchange=exchange or self.primary,
            reduce_only=reduce_only,
        )

    async def execute_entry(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        prefer_maker: bool = True,
        timeout: float = 4.0,
        exchange: str | None = None,
        expected_price: float | None = None,
        leverage: int | None = None,
        order_type: str | None = None,
    ) -> dict:
        if order_type is not None:
            prefer_maker = str(order_type).lower() != "market"
        px = price_hint or self.prices.get(symbol, 100.0)
        if expected_price and abs(px - expected_price) / max(expected_price, 1e-9) * 100.0 > 0.30:
            return self.paper.chase_order(
                symbol, side, qty, expected_price, px, 0.30, exchange=exchange or self.primary
            )
        if prefer_maker:
            return self.paper.maker_order(symbol, side, qty, px, exchange=exchange or self.primary)
        return self.paper.market_order(symbol, side, qty, px, exchange=exchange or self.primary)

    async def place_protection(
        self,
        symbol: str,
        pos_side: str,
        qty: float,
        stop_price: float,
        tp_price: float | None = None,
        exchange: str | None = None,
    ) -> dict:
        prot = {
            "native": True,
            "tur": "paper-stop",
            "stop": stop_price,
            "tp": tp_price,
            "exchange": exchange or self.primary,
            "ids": ["demo-prot"],
        }
        self.paper.protections[symbol] = prot
        return prot

    async def replace_protection(
        self,
        symbol: str,
        pos_side: str,
        qty: float,
        stop_price: float,
        old_prot: dict | None = None,
        exchange: str | float | None = None,
        tp_price: float | None = None,
    ) -> dict:
        if isinstance(exchange, (int, float)):
            tp_price = float(exchange)
            ex_arg = None
        else:
            ex_arg = exchange
        return await self.place_protection(
            symbol, pos_side, qty, stop_price, tp_price=tp_price, exchange=ex_arg
        )

    async def cancel_protection(self, symbol: str, prot: dict | None) -> bool:
        self.paper.protections.pop(symbol, None)
        return True


class LiveBotHub:
    """Dashboard için tüm modülleri canlı koşturan merkez (Demo / Sentetik Mod)."""

    demo = True

    def __init__(self, db_path: str | Path | None = None):
        cfg = load_config()
        self.cfg = cfg
        g, r, sn = cfg["genel"], cfg["risk"], cfg["sinyal"]
        pf = cfg.get("para_akisi", {})
        bz = cfg.get("boyutlandirma", {})
        self.symbols: list[str] = list(
            g.get("semboller", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        )[:6]
        for base_sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            if base_sym not in self.symbols:
                self.symbols.append(base_sym)
        self.leverage: int = int(g.get("kaldıraç", 10) or 10)
        self.capital_pct: float = float(r.get("kasa_giris_yuzde", 10.0))

        self.store = StateStore(db_path or (BASE_DIR / "dashboard_demo.db"))
        self.breaker = CircuitBreaker(
            max_consecutive_errors=3,
            daily_max_loss_pct=float(r.get("gunluk_max_zarar_yuzde", 5.0)),
            max_ws_silence_sec=60.0,
        )
        self.alerter = MultiChannelAlerter()
        self.broker = DashboardSimBroker(
            balance_usdt=float(cfg.get("paper", {}).get("bakiye", 1_000.0))
        )
        self.risk = RiskManager(
            stop_loss_pct=float(r.get("stop_loss_yuzde", 5.0)),
            stop_model=r.get("stop_modeli", "fiyat_yuzde"),
            margin_stop_fraction=float(r.get("marj_zarar_orani", 0.80)),
            margin_stop_liq_buffer=float(r.get("marj_stop_likidasyon_tamponu", 0.85)),
            lock_trigger_pct=float(r.get("kar_kilit_tetikleyici", 10.0)),
            lock_level_pct=float(r.get("kar_kilit_seviyesi", 5.0)),
            trail_pct=float(r.get("trailing_yuzde", 5.0)),
            daily_max_loss_pct=float(r.get("gunluk_max_zarar_yuzde", 5.0)),
            capital_pct_per_entry=self.capital_pct,
            leverage=self.leverage,
            unlimited_pyramiding=bool(r.get("sinirsiz_ekleme", False)),
            pyramid_min_profit_pct=0.25,
            pair_rescue_enabled=bool(r.get("capraz_kurtarma", False)),
            rescue_min_loser_pct=0.5,
            dynamic_leverage_enabled=bool(r.get("dinamik_kaldirac", False)),
            atr_high_volatility_pct=float(r.get("atr_yuksek_oynaklik_yuzde", 1.5)),
            atr_extreme_volatility_pct=float(r.get("atr_asiri_oynaklik_yuzde", 3.0)),
            max_layers=int(r.get("max_kademe", 1)),
        )
        self.strategy = Strategy(
            w_ind=sn.get("agirlik_indikator", 0.40),
            w_flow=sn.get("agirlik_para_akisi", 0.30),
            w_news=sn.get("agirlik_haber", 0.15),
            long_th=sn.get("long_esik", 55),
            short_th=sn.get("short_esik", -55),
            exit_th=sn.get("cikis_esik", 15),
            w_ml=sn.get("agirlik_ml", 0.15),
            orderflow_filter=bool(sn.get("orderflow_onayi", True)),
            runner_exit=bool(cfg.get("cikis", {}).get("kosan_kar", True)),
        )
        self.sizer = PositionSizer(
            mode=bz.get("mod", "sabit_usdt"),
            capital_pct=self.capital_pct,
            leverage=self.leverage,
            fixed_margin_usdt=float(bz.get("sabit_marj_usdt", 50.0)),
            stats_path=BASE_DIR / "kelly_stats.json",
        )
        self.logs: deque[dict] = deque(maxlen=80)
        self.executor = Executor(
            self.broker,
            self.risk,
            self.strategy,
            sizer=self.sizer,
            order_type="maker",
            maker_timeout=2.0,
            alert=self._log_alert,
            protection_on=True,
            state_store=self.store,
            circuit_breaker=self.breaker,
            trade_plan_cfg=cfg.get("islem_plani", {}),
            runner_exit_cfg=cfg.get("cikis", {}),
        )
        self.executor.add_cooldown_sec = 2.0

        self.flows = {
            s: MoneyFlow(
                s,
                whale_usdt=100_000,
                liq_squeeze_usdt=50_000,
                book_depth_levels=20,
                divergence_min_price_pct=float(pf.get("divergence_min_fiyat_yuzde", 0.05)),
                absorption_min_usdt=float(pf.get("absorption_min_usdt", 25_000)),
                absorption_ratio=float(pf.get("absorption_oran", 1.5)),
                vpvr_window_sec=int(pf.get("vpvr_pencere_saniye", 21_600)),
                vpvr_bins=int(pf.get("vpvr_bin", 48)),
            )
            for s in self.symbols
        }
        self.ml_models = {
            s: MLPredictor(horizon=3, min_train_bars=60, retrain_every=20)
            for s in self.symbols
        }
        self.arb = ArbitrageEngine(
            min_net_spread_pct=0.08,
            fee_per_leg_pct=0.05,
            trade_notional_usdt=500.0,
            state_store=self.store,
        )
        self.news = NewsEngine([], fear_greed_on=False)
        self.live_scores: dict[str, dict] = {}
        self._candles: dict[str, pd.DataFrame] = {}
        self._tick_n: int = 0
        self._rng = np.random.default_rng(42)
        self._bootstrap_demo_state()

    async def _log_alert(self, msg: str) -> None:
        clean = mask_secrets(str(msg))
        self.logs.appendleft({"ts": time.strftime("%H:%M:%S"), "text": clean[:240]})

    def _bootstrap_demo_state(self) -> None:
        base_prices = {
            "BTC/USDT": 68_500.0,
            "ETH/USDT": 3_450.0,
            "SOL/USDT": 165.0,
        }
        now = time.time()
        for idx, s in enumerate(self.symbols):
            p0 = base_prices.get(s, 50.0 + idx * 15.0)
            self.broker.prices[s] = p0
            rets = self._rng.normal(0.0003, 0.003, size=120)
            closes = p0 * np.cumprod(1.0 + rets)
            opens = np.roll(closes, 1)
            opens[0] = p0
            highs = np.maximum(opens, closes) * (1.0 + np.abs(rets) * 0.6 + 0.001)
            lows = np.minimum(opens, closes) * (1.0 - np.abs(rets) * 0.6 - 0.001)
            vols = self._rng.uniform(80.0, 450.0, size=120)
            self._candles[s] = pd.DataFrame(
                {
                    "ts": [now - (120 - i) * 300 for i in range(120)],
                    "open": opens,
                    "high": highs,
                    "low": lows,
                    "close": closes,
                    "volume": vols,
                }
            )
            self.executor.set_mtf_trend(
                s,
                {"trend": "BULLISH", "score": 25.0, "allow_long": True, "allow_short": False},
            )

        if not self.executor.positions:
            btc_px = float(self._candles["BTC/USDT"]["close"].iloc[-1])
            self.broker.prices["BTC/USDT"] = btc_px
            qty_btc, info_btc = self.sizer.size(
                self.broker.paper.balance, btc_px, btc_px * 0.95
            )
            entry_btc = round(btc_px * 0.988, 2)
            pos_btc = Position(
                symbol="BTC/USDT",
                side="LONG",
                entry=entry_btc,
                qty=qty_btc,
                stop=self.risk.initial_stop("LONG", entry_btc, self.leverage),
                leverage=self.leverage,
                margin_usdt=info_btc["margin_usdt"],
                layers=1,
                last_add_price=btc_px,
            )
            self.executor.positions["BTC/USDT"] = pos_btc
            self.executor.last_prices["BTC/USDT"] = btc_px
            self.broker.paper.sync_position("BTC/USDT", "LONG", qty_btc)
            self.store.save_position(pos_btc, "binance")

            if "SOL/USDT" in self.symbols:
                sol_px = float(self._candles["SOL/USDT"]["close"].iloc[-1])
                self.broker.prices["SOL/USDT"] = sol_px
                qty_sol, info_sol = self.sizer.size(
                    self.broker.paper.balance, sol_px, sol_px * 0.95
                )
                entry_sol = round(sol_px * 0.994, 4)
                pos_sol = Position(
                    symbol="SOL/USDT",
                    side="LONG",
                    entry=entry_sol,
                    qty=qty_sol,
                    stop=self.risk.initial_stop("LONG", entry_sol, self.leverage),
                    leverage=self.leverage,
                    margin_usdt=info_sol["margin_usdt"],
                    layers=1,
                    last_add_price=sol_px,
                )
                self.executor.positions["SOL/USDT"] = pos_sol
                self.executor.last_prices["SOL/USDT"] = sol_px
                self.broker.paper.sync_position("SOL/USDT", "LONG", qty_sol)
                self.store.save_position(pos_sol, "binance")

        asyncio.run_coroutine_threadsafe if False else None
        self.logs.appendleft(
            {"ts": time.strftime("%H:%M:%S"), "text": "🚀 Demo komuta paneli hazır."}
        )
        # İlk anlık skor ve equity anlık görüntüsünü hazırla
        for s in self.symbols:
            df = self._candles[s]
            px = float(df["close"].iloc[-1])
            self.flows[s].add_trade(px, 1.5, False)
            self.flows[s].update_book([(px * 0.9995, 5.0)], [(px * 1.0005, 4.0)])
            ind = indicator_score(df)
            ml_res = self.ml_models[s].predict(df)
            flow_snap = self.flows[s].snapshot()
            combined = self.strategy.combine(
                ind["score"],
                flow_snap["score"],
                0.0,
                ml_res["score"],
                market_context={**ind.get("snapshot", {}), "cvd_slope": flow_snap["cvd_slope"]},
            )
            self.live_scores[s] = {
                "symbol": s,
                **ind.get("snapshot", {}),
                "price": round(px, 4),
                "total": combined["total"],
                "signal": combined["signal"],
                "raw_signal": combined.get("raw_signal", combined["signal"]),
                "entry_allowed": combined.get("entry_allowed", True),
                "entry_block_reason": combined.get("entry_block_reason", ""),
                "indikator": round(ind["score"], 1),
                "para_akisi": flow_snap["score"],
                "haber": 0.0,
                "ml_skor": ml_res["score"],
                "ml_prob_up": round(ml_res["prob_up"] * 100.0, 1),
                "ml_backend": ml_res["backend"],
                "mtf_trend": "BULLISH",
                "mtf_score": 25.0,
                "bid_ask_ratio": flow_snap["bid_ask_ratio"],
                "wall_signal": flow_snap["wall_signal"],
                "squeeze": flow_snap["squeeze"],
                "oi": flow_snap["open_interest"],
                "oi_change_pct": flow_snap["oi_change_pct"],
                "oi_signal": flow_snap["oi_signal"],
                "oi_flow_confirmation": flow_snap["oi_flow_confirmation"],
                "cvd_slope": flow_snap["cvd_slope"],
                "cvd_divergence": flow_snap["cvd_divergence"],
                "absorption": flow_snap["absorption"],
                "orderflow_veto": combined.get("orderflow_veto", ""),
                "vpvr_poc": flow_snap["vpvr_poc"],
                "vpvr_vah": flow_snap["vpvr_vah"],
                "vpvr_val": flow_snap["vpvr_val"],
                "vpvr_trades": flow_snap["vpvr_trades"],
                "vpvr_coverage_sec": flow_snap["vpvr_coverage_sec"],
                "vpvr_warm": flow_snap["vpvr_warm"],
                "short_liq_usdt": flow_snap["short_liq_usdt"],
                "long_liq_usdt": flow_snap["long_liq_usdt"],
            }
            self.arb.update_quote("binance", s, px * 0.9998, px * 1.0002)
            self.arb.update_quote("okx", s, px * 1.0004, px * 1.0008)
        unreal, known = safe_unrealized(self.executor)
        if known:
            self.store.record_equity(self.broker.paper.balance,
                                     self.broker.paper.balance + unreal,
                                     len(self.executor.positions))
        self._sync_health_meta()

    def _sync_health_meta(self) -> None:
        self.breaker.heartbeat_ws()
        bal = self.broker.paper.balance
        unreal, _ = safe_unrealized(self.executor)
        self.store.set_meta("circuit_breaker", self.breaker.status())
        self.store.set_meta(
            "bot_status",
            {
                "ts": time.time(),
                "mode": "DEMO",
                "primary_exchange": self.broker.primary,
                "balance_usdt": bal,
                "equity_usdt": equity_or_none(bal, unreal),
                "unrealized_usdt": unreal,
                "open_positions": len(self.executor.positions),
                "exchange_health": self.broker.exchange_health_snapshot(),
                "circuit_breaker": self.breaker.status(),
            },
        )

    async def step_tick(self) -> None:
        self._tick_n += 1
        mood = self.news.mood()
        fg = 55.0
        for s in self.symbols:
            df = self._candles[s]
            prev_px = float(df["close"].iloc[-1])
            shock = float(self._rng.normal(0.00015, 0.0018))
            new_px = round(max(0.0001, prev_px * (1.0 + shock)), 4)
            self.broker.prices[s] = new_px
            df.iloc[-1, df.columns.get_loc("close")] = new_px
            df.iloc[-1, df.columns.get_loc("high")] = max(
                float(df["high"].iloc[-1]), new_px
            )
            df.iloc[-1, df.columns.get_loc("low")] = min(
                float(df["low"].iloc[-1]), new_px
            )

            atr_s = Indicators.atr(df["high"], df["low"], df["close"], 14)
            atr_v = float(atr_s.iloc[-1]) if pd.notna(atr_s.iloc[-1]) else new_px * 0.01
            if s not in self.executor._atr or self._tick_n % 5 == 0:
                self.executor.set_atr(s, atr_v)
                lookback = int(self.cfg.get("islem_plani", {}).get("swing_mum", 20))
                structure = df.tail(lookback)
                self.executor.set_market_structure(
                    s, float(structure["low"].min()), float(structure["high"].max())
                )
            dyn_lev, lev_why = self.executor.get_dynamic_leverage(s, new_px)

            is_sell = shock < -0.0002
            qty_tick = max(0.01, float(self._rng.uniform(500.0, 8_000.0)) / new_px)
            self.flows[s].add_trade(new_px, qty_tick, is_sell)
            self.flows[s].update_book(
                [(new_px * (1.0 - 0.0003 * (i + 1)), 2.5) for i in range(10)],
                [(new_px * (1.0 + 0.0003 * (i + 1)), 2.2) for i in range(10)],
            )
            await self.executor.on_price_tick(s, new_px)

            ind = indicator_score(df)
            ml_res = self.ml_models[s].predict(df)
            flow_snap = self.flows[s].snapshot()
            await self.executor.maybe_orderflow_exit(s, new_px, flow_snap)
            fg_tilt = fg - 50.0
            news_blended = round(mood["score"] * 0.7 + fg_tilt * 0.6, 1)
            combined = self.strategy.combine(
                ind["score"],
                flow_snap["score"],
                news_blended,
                ml_res["score"],
                market_context={
                    **ind.get("snapshot", {}),
                    "cvd_slope": flow_snap.get("cvd_slope", 0.0),
                    "cvd_divergence": flow_snap.get("cvd_divergence", "YOK"),
                    "absorption": flow_snap.get("absorption", "YOK"),
                    "oi_signal": flow_snap.get("oi_signal", "NOTR"),
                },
            )
            mtf_cur = self.executor.get_mtf_trend(s)
            if not isinstance(mtf_cur, dict):
                mtf_cur = {"trend": str(mtf_cur or "NEUTRAL"), "score": 0.0}

            self.live_scores[s] = {
                "symbol": s,
                **ind.get("snapshot", {}),
                "price": new_px,
                "total": combined["total"],
                "signal": combined["signal"],
                "raw_signal": combined.get("raw_signal", combined["signal"]),
                "entry_allowed": combined.get("entry_allowed", True),
                "entry_block_reason": combined.get("entry_block_reason", ""),
                "indikator": round(ind["score"], 1),
                "para_akisi": flow_snap["score"],
                "haber": news_blended,
                "ml_skor": ml_res["score"],
                "ml_prob_up": round(ml_res["prob_up"] * 100.0, 1),
                "ml_backend": ml_res["backend"],
                "dynamic_leverage": dyn_lev,
                "leverage_reason": lev_why,
                "mtf_trend": mtf_cur.get("trend", "NEUTRAL"),
                "mtf_score": mtf_cur.get("score", 0.0),
                "bid_ask_ratio": flow_snap.get("bid_ask_ratio", 1.0),
                "wall_signal": flow_snap.get("wall_signal", "DENGELI"),
                "squeeze": flow_snap.get("squeeze", "YOK"),
                "oi": flow_snap.get("open_interest", 0.0),
                "oi_change_pct": flow_snap.get("oi_change_pct", 0.0),
                "oi_signal": flow_snap.get("oi_signal", "NOTR"),
                "oi_flow_confirmation": flow_snap.get("oi_flow_confirmation", "CVD_VERI_YOK"),
                "cvd_slope": flow_snap.get("cvd_slope", 0.0),
                "cvd_divergence": flow_snap.get("cvd_divergence", "YOK"),
                "absorption": flow_snap.get("absorption", "YOK"),
                "orderflow_veto": combined.get("orderflow_veto", ""),
                "vpvr_poc": flow_snap.get("vpvr_poc", 0.0),
                "vpvr_vah": flow_snap.get("vpvr_vah", 0.0),
                "vpvr_val": flow_snap.get("vpvr_val", 0.0),
                "vpvr_trades": flow_snap.get("vpvr_trades", 0),
                "vpvr_coverage_sec": flow_snap.get("vpvr_coverage_sec", 0.0),
                "vpvr_warm": flow_snap.get("vpvr_warm", False),
                "short_liq_usdt": flow_snap.get("short_liq_usdt", 0.0),
                "long_liq_usdt": flow_snap.get("long_liq_usdt", 0.0),
            }
            self.arb.update_quote("binance", s, new_px * 0.9998, new_px * 1.0002)
            self.arb.update_quote("okx", s, new_px * 1.0005, new_px * 1.0009)

        bal = self.broker.paper.balance
        unreal, known = safe_unrealized(self.executor)
        if known:
            self.store.record_equity(bal, bal + unreal, len(self.executor.positions))
        self._sync_health_meta()

    def build_state_payload(self) -> dict:
        bal = round(self.broker.paper.balance, 2)
        unreal, _ = safe_unrealized(self.executor)
        unreal = round(unreal, 2) if unreal is not None else None
        raw_equity = equity_or_none(bal, unreal)
        equity = round(raw_equity, 2) if raw_equity is not None else None
        start_bal = self.broker.paper.start_balance
        total_ret = round((equity / start_bal - 1.0) * 100.0, 2) if equity is not None and start_bal > 0 else None

        open_rows = []
        for sym, pos in self.executor.positions.items():
            px = self.executor.last_prices.get(sym) if self.executor._fresh_local_quote(sym) else None
            pnl_pct = round(self.risk.profit_pct(pos, px), 2) if px is not None else None
            roe_pct = round(self.risk.roe_pct(pos, px), 1) if px is not None else None
            pnl_usd = round(self.risk.pnl_usdt(pos, px), 2) if px is not None else None
            open_rows.append(
                {
                    "symbol": sym,
                    "side": pos.side,
                    "entry": round(pos.entry, 4),
                    "price": round(px, 4) if px is not None else None,
                    "qty": round(pos.qty, 6),
                    "leverage": pos.leverage,
                    "margin_usdt": round(pos.margin_usdt, 2),
                    "notional_usdt": round(pos.entry * pos.qty, 2),
                    "layers": pos.layers,
                    "stop": round(pos.stop, 4),
                    "locked_profit": pos.locked_profit,
                    "trade_plan": self.executor.get_trade_plan(sym),
                    "pnl_pct": pnl_pct,
                    "roe_pct": roe_pct,
                    "pnl_usdt": pnl_usd,
                }
            )

        return {
            "ts": time.strftime("%H:%M:%S"),
            "demo": True,
            "mode": "DEMO",
            "balance_usdt": bal,
            "unrealized_usdt": unreal,
            "equity_usdt": equity,
            "total_return_pct": total_ret,
            "leverage": self.leverage,
            "capital_pct": self.capital_pct,
            "stop_loss_pct": self.risk.stop_loss_pct,
            "max_slippage_pct": self.risk.max_slippage_pct,
            "stats": self.executor.stats,
            "circuit_breaker": self.breaker.status(),
            "exchange_health": self.broker.exchange_health_snapshot(),
            "sqlite_wal": self.store.get_wal_status(),
            "alert_channels": self.alerter.status(),
            "open_positions": open_rows,
            "scores": list(self.live_scores.values()),
            "arbitrage_quotes": self.arb.scan_all(self.symbols),
            "arbitrage_history": self.store.get_arb_history(limit=10),
            "arb_total_profit": self.arb.total_profit_usdt,
            "equity_curve": self.store.get_equity_curve(limit=60),
            "recent_trades": self.store.get_trades(limit=12),
            "logs": list(self.logs),
        }

    async def handle_action(self, action: str, payload: dict) -> dict:
        if action == "kill_switch":
            self.breaker.manual_trip("WEB PANELİ KILL SWITCH")
            closed = await self.executor.close_all_positions("ACİL KILL SWITCH")
            closed_n = closed if isinstance(closed, int) else len(closed)
            await self._log_alert(f"🚨 Kill Switch tetiklendi ({closed_n} pozisyon kapatıldı).")
            self._sync_health_meta()
            return {
                "ok": True,
                "closed": closed_n,
                "message": f"🚨 Kill Switch uygulandı ({closed_n} pozisyon kapatıldı).",
            }
        if action == "toggle_pause":
            if self.breaker.paused:
                self.breaker.resume()
                msg = "▶️ Bot devam ettirildi."
            else:
                self.breaker.pause()
                msg = "⏸️ Bot duraklatıldı."
            await self._log_alert(msg)
            self._sync_health_meta()
            return {"ok": True, "message": msg}
        if action == "reset_breaker":
            self.breaker.reset()
            await self._log_alert("🔄 Sigorta sıfırlandı.")
            self._sync_health_meta()
            return {"ok": True, "message": "🔄 Sigorta sıfırlandı."}
        if action == "run_gc":
            res = self.store.run_garbage_collector()
            msg = f"🧹 SQLite WAL & VACUUM tamamlandı (arşivlenen={res['archived']})."
            await self._log_alert(msg)
            return {"ok": True, "message": msg}
        if action == "close_symbol":
            sym = str(payload.get("symbol", "")).upper()
            if sym not in self.executor.positions:
                return {"ok": False, "message": f"{sym} açık pozisyon bulunamadı."}
            pos = self.executor.positions[sym]
            px = self.executor.last_prices.get(sym, pos.entry)
            pnl = self.risk.profit_pct(pos, px)
            await self.executor._close(sym, px, "PANEL MANUEL KAPAMA", pnl)
            return {"ok": True, "message": f"{sym} kapatıldı."}
        if action == "sim_failover":
            self.broker._active_primary = "okx"
            self.broker.failover_count += 1
            self.broker._degraded_until["binance"] = time.time() + 120.0
            await self._log_alert("🔀 Demo Failover: Binance → OKX geçişi simüle edildi.")
            return {"ok": True, "message": "🔀 Binance → OKX failover simüle edildi."}
        if action == "recover_exchange":
            self.broker._degraded_until["binance"] = 0.0
            self.broker._active_primary = "binance"
            await self._log_alert("✅ Binance birincil borsa olarak normale döndü.")
            return {"ok": True, "message": "✅ Binance normale döndürüldü."}
        return {"ok": True, "message": f"Demo eylemi çalıştırıldı: {action}"}


class ProductionBotHub:
    """Gerçek bot durumunu okuyan, emirleri doğrudan yürütmeyen panel bağdaştırıcısı.

    Kontrol eylemleri yalnızca ana botun tükettiği SQLite komut kuyruğuna yazılır.
    Böylece web süreci ile işlem sürecindeki bakiye/pozisyon nesneleri ayrışmaz.
    """

    demo = False

    def __init__(self, db_path: str | Path | None = None):
        self.cfg = load_config()
        g = self.cfg["genel"]
        r = self.cfg["risk"]
        self.symbols = g["semboller"]
        self.leverage = int(g.get("kaldıraç", 20))
        self.capital_pct = float(r.get("kasa_giris_yuzde", 10.0))
        configured_db = self.cfg.get("veritabani", {}).get("dosya", "bot_state.db")
        self.store = StateStore(db_path or (BASE_DIR / configured_db))
        self.risk = RiskManager(
            stop_loss_pct=float(r.get("stop_loss_yuzde", 5.0)),
            max_slippage_pct=float(r.get("max_kayma_yuzde", 0.30)),
        )

    def _sync_health_meta(self):
        # Üretim paneli heartbeat yazmaz; ana botun heartbeat'i okunur.
        return None

    def build_state_payload(self) -> dict:
        status = self.store.get_meta("bot_status", {}) or {}
        scores_by_symbol = self.store.get_meta("live_scores", {}) or {}
        scores = []
        symbol_keys = list(dict.fromkeys([*self.symbols, *scores_by_symbol.keys()]))
        for symbol in symbol_keys:
            if symbol not in scores_by_symbol:
                continue
            row = dict(scores_by_symbol[symbol])
            prob = float(row.get("ml_prob_up", 0.5) or 0.5)
            row["ml_prob_up"] = round(prob * 100.0 if 0.0 <= prob <= 1.0 else prob, 1)
            scores.append(row)
        score_map = {row.get("symbol"): row for row in scores}
        positions = self.store.load_positions()
        trade_plans = self.store.get_meta("trade_plans", {}) or {}
        balance = float(status.get("balance_usdt", 0.0) or 0.0)
        equity_raw = status.get("equity_usdt")
        unrealized_raw = status.get("unrealized_usdt")
        equity = float(equity_raw) if equity_raw is not None else None
        unrealized = float(unrealized_raw) if unrealized_raw is not None else None
        curve = self.store.get_equity_curve(limit=60)
        # A limited chart window is not the beginning of the account. Do not
        # relabel its first sample (or current balance) as total return.
        baseline = None
        mode = str(status.get("mode", self.cfg["genel"]["mod"])).lower()
        if mode == "paper":
            account = self.store.get_meta("paper_account", {}) or {}
            try:
                raw_start = account.get("start_balance") if isinstance(account, dict) else None
                value = float(raw_start) if raw_start is not None and not isinstance(raw_start, bool) else None
                if value is not None and math.isfinite(value) and value > 0:
                    baseline = value
            except (TypeError, ValueError, OverflowError):
                pass
        total_return = ((equity / baseline - 1.0) * 100.0) if equity is not None and baseline is not None else None

        open_rows = []
        for symbol, pos in positions.items():
            raw_price = score_map.get(symbol, {}).get("price")
            try:
                price = float(raw_price)
                if not math.isfinite(price) or price <= 0:
                    price = None
            except (TypeError, ValueError, OverflowError):
                price = None
            pnl_pct = self.risk.profit_pct(pos, price) if price is not None else None
            open_rows.append(
                {
                    "symbol": symbol,
                    "side": pos.side,
                    "entry": pos.entry,
                    "price": price,
                    "qty": pos.qty,
                    "leverage": pos.leverage,
                    "margin_usdt": pos.margin_usdt,
                    "notional_usdt": pos.entry * pos.qty,
                    "layers": pos.layers,
                    "stop": pos.stop,
                    "locked_profit": pos.locked_profit,
                    "trade_plan": trade_plans.get(symbol),
                    "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                    "roe_pct": round(self.risk.roe_pct(pos, price), 1) if price is not None else None,
                    "pnl_usdt": round(self.risk.pnl_usdt(pos, price), 2) if price is not None else None,
                }
            )

        cb = self.store.get_meta("circuit_breaker", status.get("circuit_breaker", {})) or {}
        exchange_health = status.get("exchange_health", {}) or {
            "active_primary": status.get("primary_exchange", "binance"),
            "failover_active": False,
            "exchanges": {},
        }
        return {
            "ts": time.strftime("%H:%M:%S"),
            "demo": False,
            "mode": status.get("mode", self.cfg["genel"]["mod"].upper()),
            "balance_usdt": balance,
            "unrealized_usdt": unrealized,
            "equity_usdt": equity,
            "total_return_pct": round(total_return, 2) if total_return is not None else None,
            "leverage": self.leverage,
            "capital_pct": self.capital_pct,
            "stop_loss_pct": self.risk.stop_loss_pct,
            "max_slippage_pct": self.risk.max_slippage_pct,
            "stats": status.get("stats", {}) or {},
            "circuit_breaker": cb,
            "exchange_health": exchange_health,
            "sqlite_wal": self.store.get_wal_status(),
            "alert_channels": status.get("alert_channels", {"stats": {}}),
            "open_positions": open_rows,
            "scores": scores,
            "arbitrage_quotes": self.store.get_meta("arb_quotes", []) or [],
            "arbitrage_history": self.store.get_arb_history(limit=10),
            "arb_total_profit": float(status.get("arb_total_profit", 0.0) or 0.0),
            "equity_curve": curve,
            "recent_trades": self.store.get_trades(limit=12),
            "logs": status.get("logs", []) or [],
        }

    async def handle_action(self, action: str, payload: dict) -> dict:
        if action == "kill_switch":
            self.store.push_command("KILL_SWITCH")
            return {
                "ok": True,
                "message": "🚨 Kill-switch ana bota iletildi; pozisyonlar güvenli biçimde kapatılacak.",
            }
        if action == "toggle_pause":
            cb = self.store.get_meta("circuit_breaker", {}) or {}
            paused = not bool(cb.get("paused", False))
            self.store.push_command("PAUSE" if paused else "RESUME")
            return {
                "ok": True,
                "message": "⏸️ Duraklatma komutu iletildi."
                if paused
                else "▶️ Devam komutu iletildi.",
            }
        if action == "reset_breaker":
            self.store.push_command("RESET_BREAKER")
            return {"ok": True, "message": "🔄 Sigorta sıfırlama komutu ana bota iletildi."}
        if action == "run_gc":
            self.store.push_command("RUN_GC")
            return {"ok": True, "message": "🧹 SQLite bakım komutu ana bota iletildi."}
        if action == "close_symbol":
            symbol = str(payload.get("symbol", "")).upper()
            if symbol not in self.store.load_positions():
                return {"ok": False, "message": f"{symbol} açık pozisyon bulunamadı."}
            self.store.push_command("CLOSE_SYMBOL", {"symbol": symbol})
            return {"ok": True, "message": f"{symbol} kapama komutu ana bota iletildi."}
        return {"ok": False, "message": "Bu işlem yalnızca ayrı demo panelinde kullanılabilir."}


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>KRIPTO-BOT v7.2 — Güvenli İşlem ve İzleme Paneli</title>
<style>
  :root {
    --bg: #0b0f19; --card: #111827; --border: #1f2937; --text: #f3f4f6;
    --muted: #9ca3af; --green: #10b981; --red: #ef4444; --amber: #f59e0b;
    --blue: #3b82f6; --purple: #8b5cf6;
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); }
  .topbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; padding: 16px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; }
  .brand h1 { margin: 0 0 4px 0; font-size: 18px; }
  .brand p { margin: 0; font-size: 12px; color: var(--muted); }
  .badges { display: flex; flex-wrap: wrap; gap: 8px; }
  .badge { padding: 5px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; background: #1f2937; }
  .badge.green { background: rgba(16,185,129,.18); color: #34d399; }
  .badge.amber { background: rgba(245,158,11,.18); color: #fbbf24; }
  .badge.purple { background: rgba(139,92,246,.2); color: #c4b5fd; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
  button { cursor: pointer; border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; font-weight: 600; color: var(--text); background: #1f2937; }
  .btn-kill { background: #991b1b; border-color: #dc2626; }
  .btn-pause { background: #1e40af; border-color: #3b82f6; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 16px; }
  .kpi { font-size: 22px; font-weight: 700; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--border); }
  .pos { color: var(--green); } .neg { color: var(--red); }
  .tag-long { color: #34d399; font-weight: 700; } .tag-short { color: #f87171; font-weight: 700; }
  .metrics-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-top: 4px; }
  .toast { position: fixed; right: 20px; bottom: 20px; background: #1f2937; border: 1px solid #374151; padding: 10px 16px; border-radius: 8px; display: none; }
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <h1>🛡️ KRIPTO-BOT v7.2 — İşlem ve İzleme Paneli</h1>
    <p>Sabit 50 USDT Marj / 10x / 40 USDT Stop • Trailing + Order-Flow Çıkışı • Shadow Lab • Dual Futures (Binance + OKX)</p>
  </div>
  <div class="badges">
    <span id="modeBadge" class="badge purple">GERÇEK BOT</span>
    <span id="statusBadge" class="badge green">DURUM BEKLENİYOR</span>
    <span id="exBadge" class="badge green">AKTİF BORSA: BINANCE</span>
    <span id="clockBadge" class="badge">--:--:--</span>
  </div>
  <div style="display:flex;gap:6px;margin-top:8px;">
    <input id="dashboardToken" type="password" autocomplete="off" placeholder="Uzak erişim: panel tokeni" style="background:#111827;color:#f3f4f6;border:1px solid #374151;border-radius:6px;padding:7px;min-width:230px;" />
    <button onclick="saveDashboardToken()">Tokeni Kullan</button>
  </div>
</div>

<div class="controls">
  <button class="btn-kill" onclick="sendAction('kill_switch')">🚨 ACİL KILL SWITCH</button>
  <button id="pauseBtn" class="btn-pause" onclick="sendAction('toggle_pause')">⏸️ Duraklat / Başlat</button>
  <button onclick="sendAction('reset_breaker')">🔄 Sigortayı Sıfırla</button>
  <button onclick="sendAction('run_gc')">🧹 SQLite WAL & VACUUM</button>
  <button class="demo-only" onclick="sendAction('sim_failover')">🔀 Binance → OKX Failover Test</button>
  <button class="demo-only" onclick="sendAction('recover_exchange')">✅ Binance Normale Döndür</button>
</div>

<div class="grid">
  <div class="card"><div>Toplam Özsermaye</div><div id="kpiEquity" class="kpi">$0.00</div></div>
  <div class="card"><div>Cüzdan Bakiyesi</div><div id="kpiBalance" class="kpi">$0.00</div></div>
  <div class="card"><div>Açık K/Z</div><div id="kpiUnreal" class="kpi">$0.00</div></div>
  <div class="card"><div>Toplam Getiri</div><div id="kpiReturn" class="kpi">%0.00</div></div>
</div>

<div class="card">
  <h3>Açık Pozisyonlar</h3>
  <table>
    <thead><tr><th>Sembol</th><th>Yön</th><th>Kademe</th><th>Giriş</th><th>Anlık</th><th>Stop</th><th>K/Z %</th><th>ROE %</th><th>Net $</th><th>İşlem</th></tr></thead>
    <tbody id="openPosBody"></tbody>
  </table>
</div>

<div class="card"><h3>Canlı Sinyal & Order-Flow Analizi</h3><div id="scoresGrid" class="grid"></div></div>

<div class="card">
  <h3>Borsalar Arası Spread Tarayıcı</h3>
  <table>
    <thead><tr><th>Sembol</th><th>Alış Borsası</th><th>Alış</th><th>Satış Borsası</th><th>Satış</th><th>Brüt</th><th>Net</th></tr></thead>
    <tbody id="arbQuotesBody"></tbody>
  </table>
</div>

<div class="card">
  <h3>Son Kapanan İşlemler</h3>
  <table>
    <thead><tr><th>Sembol</th><th>Yön</th><th>Kademe</th><th>Giriş</th><th>Çıkış</th><th>Fiyat %</th><th>ROE %</th><th>PnL $</th><th>Sebep</th></tr></thead>
    <tbody id="tradesBody"></tbody>
  </table>
</div>

<div class="card"><h3>Sistem Kayıtları</h3><div id="logBox"></div></div>
<div id="toast" class="toast"></div>

<script>
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}
function authHeaders(json = false) {
  const headers = json ? {'Content-Type': 'application/json'} : {};
  const token = sessionStorage.getItem('dashboardToken') || '';
  if (token) headers['X-Dashboard-Token'] = token;
  return headers;
}
function saveDashboardToken() {
  const input = document.getElementById('dashboardToken');
  sessionStorage.setItem('dashboardToken', input.value.trim());
  input.value = '';
  showToast('Panel tokeni kaydedildi.');
  refreshState();
}
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3500);
}
async function sendAction(action, payload = {}) {
  try {
    const res = await fetch('/api/action', {
      method: 'POST', headers: authHeaders(true), body: JSON.stringify({action, payload})
    });
    const data = await res.json();
    if (data.message) showToast(data.message);
    if (!res.ok) return;
    await refreshState();
  } catch (e) { showToast('Komut hatası: ' + e); }
}
async function refreshState() {
  try {
    const res = await fetch('/api/state', {headers: authHeaders()});
    if (!res.ok) { showToast('Panel durumu okunamadı. Geçerli token girin.'); return; }
    const d = await res.json();
    document.getElementById('modeBadge').textContent = d.demo ? '⚠️ DEMO / SENTETİK VERİ' : `GERÇEK BOT / ${d.mode || ''}`;
    document.querySelectorAll('.demo-only').forEach(el => { el.style.display = d.demo ? '' : 'none'; });
    document.getElementById('clockBadge').textContent = 'Canlı: ' + d.ts;
    document.getElementById('kpiEquity').textContent = d.equity_usdt == null ? 'bilinmiyor' : '$' + Number(d.equity_usdt).toFixed(2);
    document.getElementById('kpiBalance').textContent = '$' + Number(d.balance_usdt || 0).toFixed(2);
    document.getElementById('kpiUnreal').textContent = d.unrealized_usdt == null ? 'bilinmiyor' : '$' + Number(d.unrealized_usdt).toFixed(2);
    document.getElementById('kpiReturn').textContent = d.total_return_pct == null ? 'bilinmiyor' : (d.total_return_pct >= 0 ? '+' : '') + Number(d.total_return_pct).toFixed(2) + '%';
    document.getElementById('exBadge').textContent = 'AKTİF BORSA: ' + String((d.exchange_health || {}).active_primary || 'binance').toUpperCase();
    const cb = d.circuit_breaker || {};
    document.getElementById('statusBadge').textContent = cb.tripped ? '🚨 SİGORTA ATTI' : (cb.paused ? '⏸️ DURAKLATILDI' : '✅ AKTİF & GÜVENLİ');

    const opBody = document.getElementById('openPosBody');
    opBody.innerHTML = (d.open_positions || []).length === 0
      ? '<tr><td colspan="10">Açık pozisyon yok</td></tr>'
      : d.open_positions.map(p => `<tr>
          <td><b>${esc(p.symbol)}</b></td>
          <td><span class="${p.side === 'LONG' ? 'tag-long' : 'tag-short'}">${esc(p.side)}</span></td>
          <td>${p.layers}x ($${Number(p.margin_usdt).toFixed(0)})</td>
          <td>$${Number(p.entry).toLocaleString()}</td>
          <td>${p.price == null ? 'bilinmiyor' : '$' + Number(p.price).toLocaleString()}</td>
          <td>$${Number(p.stop).toLocaleString()}</td>
          <td class="${p.pnl_pct == null ? '' : (p.pnl_pct >= 0 ? 'pos' : 'neg')}">${p.pnl_pct == null ? 'bilinmiyor' : p.pnl_pct + '%'}</td>
          <td class="${p.roe_pct == null ? '' : (p.roe_pct >= 0 ? 'pos' : 'neg')}">${p.roe_pct == null ? 'bilinmiyor' : p.roe_pct + '%'}</td>
          <td class="${p.pnl_usdt == null ? '' : (p.pnl_usdt >= 0 ? 'pos' : 'neg')}">${p.pnl_usdt == null ? 'bilinmiyor' : '$' + Number(p.pnl_usdt).toFixed(2)}</td>
          <td><button onclick="sendAction('close_symbol', {symbol: '${esc(p.symbol)}'})">Kapat</button></td>
        </tr>`).join('');

    document.getElementById('scoresGrid').innerHTML = (d.scores || []).slice(0, 12).map(s => `
      <div class="card" style="margin:0;">
        <div><b>${esc(s.symbol)}</b> — $${Number(s.price || 0).toLocaleString()} (${esc(s.signal)})</div>
        <div class="metrics-row"><span>Toplam: <b>${s.total}</b></span><span>🤖 ML (${esc(s.ml_backend)}): <b>${s.ml_skor}</b> (%${s.ml_prob_up} ↑)</span></div>
        <div class="metrics-row"><span>🌊 CVD Div: <b>${esc(s.cvd_divergence || 'YOK')}</b> | Absorption: <b>${esc(s.absorption || 'YOK')}</b></span></div>
        <div class="metrics-row"><span>📍 Tick VPVR POC: <b>${Number(s.vpvr_poc || 0).toLocaleString()}</b> (${s.vpvr_trades || 0} trade)</span></div>
      </div>`).join('');

    document.getElementById('arbQuotesBody').innerHTML = (d.arbitrage_quotes || []).slice(0, 10).map(a => `
      <tr>
        <td><b>${esc(a.symbol)}</b></td><td>${esc(a.buy_exchange).toUpperCase()}</td><td>$${Number(a.buy_price).toLocaleString()}</td>
        <td>${esc(a.sell_exchange).toUpperCase()}</td><td>$${Number(a.sell_price).toLocaleString()}</td>
        <td>%${a.gross_spread_pct}</td><td class="${a.net_spread_pct > 0 ? 'pos' : 'neg'}">%${a.net_spread_pct}</td>
      </tr>`).join('');

    document.getElementById('logBox').innerHTML = (d.logs || []).map(l =>
      `<div><span style="color:#60a5fa">[${esc(l.ts)}]</span> ${esc(l.text)}</div>`
    ).join('');

    const trBody = document.getElementById('tradesBody');
    trBody.innerHTML = (d.recent_trades || []).length === 0
      ? '<tr><td colspan="9">Henüz kapanan işlem yok</td></tr>'
      : d.recent_trades.map(t => `<tr>
          <td><b>${esc(t.symbol)}</b></td>
          <td><span class="${t.side === 'LONG' ? 'tag-long' : 'tag-short'}">${esc(t.side)}</span></td>
          <td>${t.layers}x Kademe</td>
          <td>$${Number(t.entry).toLocaleString()}</td>
          <td>$${Number(t.exit_price).toLocaleString()}</td>
          <td class="${t.pnl_pct >= 0 ? 'pos' : 'neg'}">${Number(t.pnl_pct).toFixed(2)}%</td>
          <td class="${t.roe_pct >= 0 ? 'pos' : 'neg'}">${Number(t.roe_pct).toFixed(1)}%</td>
          <td class="${t.pnl_usdt >= 0 ? 'pos' : 'neg'}">$${Number(t.pnl_usdt).toFixed(2)}</td>
          <td>${esc(t.reason)}</td>
        </tr>`).join('');
  } catch (e) {}
}
refreshState();
setInterval(refreshState, 1500);
</script>
</body>
</html>
"""


def create_dashboard_app(hub=None) -> web.Application:
    """Üretim paneli uygulamasını oluşturur.

    ``DASHBOARD_TOKEN`` tanımlıysa durum ve kontrol API'lerinde
    ``X-Dashboard-Token`` zorunludur. Token yoksa bu API'ler yalnızca loopback
    isteklerine açıktır; bilinmeyen ağlara kapalıdır.
    """
    hub = hub or ProductionBotHub()
    dashboard_token = os.getenv("DASHBOARD_TOKEN", "").strip()
    if dashboard_token and len(dashboard_token) < 16:
        raise RuntimeError("DASHBOARD_TOKEN en az 16 karakter olmalı")
    if dashboard_token:
        register_secret(dashboard_token)

    def is_authorized(request: web.Request) -> bool:
        if dashboard_token:
            supplied = request.headers.get("X-Dashboard-Token", "")
            return hmac.compare_digest(supplied, dashboard_token)
        try:
            return ipaddress.ip_address(request.remote or "").is_loopback
        except ValueError:
            return False

    def has_valid_origin(request: web.Request) -> bool:
        origin = request.headers.get("Origin", "")
        if not origin:
            return True
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == request.host

    @web.middleware
    async def security_headers(request: web.Request, handler):
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app = web.Application(middlewares=[security_headers])

    async def index_handler(request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def state_handler(request: web.Request) -> web.Response:
        if not is_authorized(request):
            return web.json_response(
                {"ok": False, "message": "Panel tokeni gerekli veya uzak erişim kapalı."},
                status=401,
            )
        return web.json_response(hub.build_state_payload())

    async def health_handler(request: web.Request) -> web.Response:
        hub._sync_health_meta()
        ok, payload = build_health_payload(hub.store)
        return web.json_response(payload, status=200 if ok else 503)

    async def metrics_handler(request: web.Request) -> web.Response:
        hub._sync_health_meta()
        return web.Response(
            text=build_prometheus_metrics(hub.store),
            content_type="text/plain; version=0.0.4",
            charset="utf-8",
        )

    async def action_handler(request: web.Request) -> web.Response:
        if not has_valid_origin(request):
            return web.json_response({"ok": False, "message": "Origin reddedildi."}, status=403)
        if not is_authorized(request):
            return web.json_response(
                {"ok": False, "message": "Geçerli X-Dashboard-Token gerekli."},
                status=401,
            )
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON nesnesi gerekli")
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "message": "Geçersiz JSON."}, status=400)
        action = str(body.get("action", ""))
        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            return web.json_response({"ok": False, "message": "payload nesne olmalı."}, status=400)
        result = await hub.handle_action(action, payload)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def _bg_ticker(app_obj: web.Application):
        try:
            while True:
                await asyncio.sleep(1.5)
                await hub.step_tick()
        except asyncio.CancelledError:
            pass

    async def on_startup(app_obj: web.Application):
        if hasattr(hub, "step_tick"):
            app_obj["ticker_task"] = asyncio.create_task(_bg_ticker(app_obj))

    async def on_cleanup(app_obj: web.Application):
        task = app_obj.get("ticker_task")
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.router.add_get("/", index_handler)
    app.router.add_get("/api/state", state_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_post("/api/action", action_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    demo = os.getenv("DASHBOARD_DEMO", "").strip().lower() in {"1", "true", "yes"}
    hub = LiveBotHub() if demo else ProductionBotHub()
    panel_cfg = hub.cfg.get("panel", {})
    host = os.getenv("DASHBOARD_HOST", str(panel_cfg.get("host", "0.0.0.0")))
    port = int(os.getenv("PORT", str(panel_cfg.get("port", 8501))))
    app = create_dashboard_app(hub)
    print(
        f"🌐 {'DEMO / SENTETİK' if demo else 'GERÇEK BOT'} paneli → "
        f"http://{host}:{port} | API auth: {'token' if os.getenv('DASHBOARD_TOKEN') else 'yalnızca loopback'}",
        flush=True,
    )
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"🛑 Panel başlatılamadı: {safe_exception_msg(exc)}", flush=True)
        raise
