"""Gerçek Zamanlı Web Paneli (Dashboard) + Canlı Kontrol, Failover, SQLite GC & `/health` Sunucusu (v5).

Tarayıcıdan açılan şık, karanlık temalı gerçek zamanlı grafik arayüzü ile:
  • A) Multi-Exchange Failover (Borsa Kesinti Sigortası): Binance üst üste 3 timeout verirse
    otomatik olarak OKX yedek borsasına kesintisiz geçiş
  • B) SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı (Garbage Collector & Gzip Arşivleme)
  • C) Gerçek Zamanlı `/health`, `/healthz` (JSON) ve `/metrics` (Prometheus) Endpoint'leri
  • Anlık Açık Pozisyonlar (%10 kasa marjı, Dinamik 20x/10x/5x kaldıraç, kademe sayısı,
    %5 stop ve +%10→+%5 kâr kilidi durumu, ROE % ve $ K/Z)
  • Canlı Kâr/Zarar Eğrisi (Equity Curve)
  • Aktif Skorlar: İndikatör, Para Akışı + Açık Faiz (OI) + Likidasyon Squeeze,
    Haber / Korku-Açgözlülük, Makine Öğrenmesi (ML) Yön Tahmini, Dinamik Kaldıraç
  • Maksimum Kayma Filtresi (%0.30) & Chase Order sayacı
  • Çapraz Borsa Arbitrajı (Binance ↔ OKX) canlı fiyat farkı ve yakalanan arbitrajlar
  • Circuit Breaker (3 yetki hatası / 3 emir hatası / %5 günlük zarar / >10sn WS kopma)
  • Tek Tuşla Botu Durdur/Başlat, ACİL DURUM "KILL SWITCH" ve Telegram `/durum` - `/kill` testi

Çalıştırma:
    python -m src.dashboard
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
from aiohttp import web

from .alerts import MultiChannelAlerter
from .arbitrage import ArbitrageEngine
from .circuit_breaker import CircuitBreaker
from .config import BASE_DIR, load_config
from .exchanges import PaperBroker
from .executor import Executor
from .health import build_health_payload, build_prometheus_metrics
from .indicators import Indicators, indicator_score, multi_timeframe_filter
from .ml_predictor import MLPredictor
from .moneyflow import MoneyFlow
from .news import NewsEngine
from .risk import Position, RiskManager
from .security import mask_secrets, safe_exception_msg
from .sizing import PositionSizer
from .state_store import StateStore
from .strategy import Strategy
from .telegram import InteractiveTelegramBot


class DashboardSimBroker:
    """Web panelinde canlı piyasa + Multi-Exchange Failover + Paper motorunu besleyen broker."""

    def __init__(
        self,
        symbols: list[str],
        initial_balance: float = 10_000.0,
        max_slippage_pct: float = 0.30,
    ):
        self.mode = "paper"
        self.default_primary = "binance"
        self.primary = "binance"
        self.backup_exchange = "okx"
        self.symbols = symbols
        self.leverage = 20
        self.max_slippage_pct = max_slippage_pct
        self.failover_timeout_threshold = 3
        self.failover_cooldown_sec = 300.0
        self._consecutive_timeouts: dict[str, int] = {"binance": 0, "okx": 0}
        self._degraded_until: dict[str, float] = {"binance": 0.0, "okx": 0.0}
        self.failover_events: list[dict] = []
        self.paper = PaperBroker(
            balance_usdt=initial_balance, max_slippage_pct=max_slippage_pct
        )
        self.prices: dict[str, float] = {
            "BTC/USDT": 68450.0,
            "ETH/USDT": 2640.0,
            "SOL/USDT": 178.50,
        }
        for s in symbols:
            self.prices.setdefault(s, 100.0)

    def record_exchange_timeout(self, ex_name: str, err: Exception | str) -> bool:
        cnt = self._consecutive_timeouts.get(ex_name, 0) + 1
        self._consecutive_timeouts[ex_name] = cnt
        if cnt >= self.failover_timeout_threshold:
            now = time.time()
            self._degraded_until[ex_name] = now + self.failover_cooldown_sec
            backup = "okx" if ex_name == "binance" else "binance"
            self.primary = backup
            self.failover_events.append(
                {
                    "ts": now,
                    "from_exchange": ex_name,
                    "to_exchange": backup,
                    "consecutive_timeouts": cnt,
                    "reason": safe_exception_msg(err),
                }
            )
            return True
        return False

    def record_exchange_success(self, ex_name: str):
        self._consecutive_timeouts[ex_name] = 0
        self._degraded_until[ex_name] = 0.0
        if ex_name == self.default_primary:
            self.primary = self.default_primary

    def exchange_health_snapshot(self) -> dict:
        now = time.time()
        ex_map = {}
        for name in ("binance", "okx"):
            until = self._degraded_until.get(name, 0.0)
            deg = now < until
            ex_map[name] = {
                "degraded": deg,
                "consecutive_timeouts": self._consecutive_timeouts.get(name, 0),
                "cooldown_remaining_sec": round(max(0.0, until - now), 1) if deg else 0.0,
            }
        return {
            "default_primary": self.default_primary,
            "active_primary": self.primary,
            "backup_exchange": self.backup_exchange,
            "failover_active": self.primary != self.default_primary,
            "exchanges": ex_map,
            "failover_events_count": len(self.failover_events),
        }

    async def fetch_balance_usdt(self) -> float:
        return self.paper.balance

    async def fetch_price(self, symbol: str, exchange: str | None = None) -> float:
        return self.prices.get(symbol, 100.0)

    async def best_price(self, symbol: str, side: str) -> tuple[str, float]:
        return self.primary, self.prices.get(symbol, 100.0)

    async def execute_entry(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        order_type: str = "maker",
        timeout: float = 3.0,
        exchange: str | None = None,
        expected_price: float | None = None,
        leverage: int | None = None,
    ) -> dict:
        px = price_hint or self.prices.get(symbol, 100.0)
        if expected_price and expected_price > 0:
            slip = abs(px - expected_price) / expected_price * 100.0
            if slip > self.max_slippage_pct:
                res = self.paper.chase_order(
                    symbol, side, qty, expected_price, px, self.max_slippage_pct
                )
                res["exchange"] = self.primary
                return res
        res = self.paper.maker_order(symbol, side, qty, px)
        res["exchange"] = self.primary
        return res

    async def market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        exchange: str | None = None,
    ) -> dict:
        px = price_hint or self.prices.get(symbol, 100.0)
        res = self.paper.market_order(symbol, side, qty, px)
        res["exchange"] = self.primary
        return res

    async def place_protection(
        self,
        symbol: str,
        side: str,
        qty: float,
        sl_price: float,
        tp_price=None,
        exchange=None,
    ) -> dict:
        prot = {
            "native": True,
            "kind": "paper_oco_stop",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "sl": sl_price,
            "exchange": self.primary,
        }
        self.paper.protections[symbol] = prot
        return prot

    async def cancel_protection(self, symbol: str, prot, exchange=None) -> bool:
        self.paper.protections.pop(symbol, None)
        return True

    async def replace_protection(
        self,
        symbol: str,
        side: str,
        qty: float,
        sl_price: float,
        old,
        exchange=None,
    ) -> dict:
        return await self.place_protection(
            symbol, side, qty, sl_price, None, exchange
        )


class LiveBotHub:
    """Dashboard için tüm modülleri canlı koşturan merkez."""

    def __init__(self, db_path: str | Path | None = None):
        cfg = load_config()
        self.cfg = cfg
        g, r, sn = cfg["genel"], cfg["risk"], cfg["sinyal"]
        self.symbols: list[str] = g.get(
            "semboller", ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        )
        self.leverage: int = int(g.get("kaldıraç", 20) or 20)
        self.capital_pct: float = float(r.get("kasa_giris_yuzde", 10.0))

        self.store = StateStore(db_path or (BASE_DIR / "bot_state.db"))
        self.breaker = CircuitBreaker(
            max_consecutive_errors=3,
            daily_max_loss_pct=float(r.get("gunluk_max_zarar_yuzde", 5.0)),
            max_ws_disconnect_sec=10.0,
            max_consecutive_auth_errors=3,
            state_store=self.store,
        )
        self.broker = DashboardSimBroker(
            self.symbols,
            initial_balance=10_000.0,
            max_slippage_pct=float(r.get("max_kayma_yuzde", 0.30)),
        )
        self.risk = RiskManager(
            stop_loss_pct=float(r.get("stop_loss_yuzde", 5.0)),
            lock_trigger_pct=float(r.get("kar_kilit_tetikleyici", 10.0)),
            lock_level_pct=float(r.get("kar_kilit_seviyesi", 5.0)),
            trail_pct=float(r.get("trailing_yuzde", 5.0)),
            daily_max_loss_pct=float(r.get("gunluk_max_zarar_yuzde", 5.0)),
            capital_pct_per_entry=self.capital_pct,
            leverage=self.leverage,
            unlimited_pyramiding=True,
            pyramid_min_profit_pct=0.25,
            pair_rescue_enabled=True,
            rescue_min_loser_pct=0.5,
            max_slippage_pct=float(r.get("max_kayma_yuzde", 0.30)),
            dynamic_leverage_enabled=bool(r.get("dinamik_kaldirac", True)),
            atr_high_volatility_pct=float(r.get("atr_yuksek_oynaklik_yuzde", 1.5)),
            atr_extreme_volatility_pct=float(r.get("atr_asiri_oynaklik_yuzde", 3.0)),
        )
        self.strategy = Strategy(
            w_ind=sn.get("agirlik_indikator", 0.40),
            w_flow=sn.get("agirlik_para_akisi", 0.25),
            w_news=sn.get("agirlik_haber", 0.20),
            long_th=sn.get("long_esik", 55),
            short_th=sn.get("short_esik", -55),
            exit_th=sn.get("cikis_esik", 15),
            w_ml=sn.get("agirlik_ml", 0.15),
        )
        self.sizer = PositionSizer(
            mode="kasa_10_20x",
            capital_pct=self.capital_pct,
            leverage=self.leverage,
            stats_path=BASE_DIR / "kelly_stats.json",
        )
        self.logs: deque[dict] = deque(maxlen=80)
        self.multi_alerter = MultiChannelAlerter(
            telegram_token=cfg["api"].get("telegram_token", ""),
            telegram_chat_id=cfg["api"].get("telegram_chat", ""),
            discord_webhook_url=cfg["api"].get("discord_webhook", ""),
            pagerduty_routing_key=cfg["api"].get("pagerduty_routing_key", ""),
        )

        async def _log_alert(msg: str):
            self.add_log(msg)
            await self.multi_alerter.send(msg)

        self.executor = Executor(
            self.broker,
            self.risk,
            self.strategy,
            self.sizer,
            alert=_log_alert,
            cooldown_sec=15,
            order_type="maker",
            protection_on=True,
            state_store=self.store,
            circuit_breaker=self.breaker,
        )
        self.executor.add_cooldown_sec = 2.0

        self.tg_bot = InteractiveTelegramBot(
            token=cfg["api"].get("telegram_token", ""),
            allowed_chat_id=cfg["api"].get("telegram_chat", "") or "admin_local",
            executor=self.executor,
            circuit_breaker=self.breaker,
            broker=self.broker,
        )

        self.flows = {
            s: MoneyFlow(
                s,
                whale_usdt=100_000,
                liq_squeeze_usdt=50_000,
                book_depth_levels=20,
            )
            for s in self.symbols
        }
        self.ml_models = {
            s: MLPredictor(horizon=3, min_train_bars=60, retrain_every=20)
            for s in self.symbols
        }
        self.arb = ArbitrageEngine(
            min_net_spread_pct=0.08,
            fee_per_leg_pct=0.03,
            slippage_pct=0.01,
            trade_notional_usdt=1_000.0,
            cooldown_sec=5.0,
            state_store=self.store,
        )
        self.news = NewsEngine([], fear_greed_on=True)
        self.candles: dict[str, pd.DataFrame] = {}
        self.candles_1h: dict[str, pd.DataFrame] = {}
        self.candles_4h: dict[str, pd.DataFrame] = {}
        self.live_scores: dict[str, dict] = {}
        self._rng = np.random.default_rng(42)
        self._tick_n = 0
        self._init_seed_data()

    def add_log(self, text: str):
        self.logs.appendleft(
            {"ts": time.strftime("%H:%M:%S"), "text": mask_secrets(text)}
        )

    def _build_synthetic_20_book(
        self, mid_px: float, bias_ratio: float = 1.35
    ) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """20 kademeli gerçekçi emir defteri (Order Book Depth 20) üretir."""
        bids_20 = []
        asks_20 = []
        base_qty = max(0.05, 18_000.0 / max(mid_px, 1.0))
        for lvl in range(1, 21):
            step = 0.00025 * lvl
            b_px = round(mid_px * (1.0 - step), 4)
            a_px = round(mid_px * (1.0 + step), 4)
            wall_mult_b = 2.6 if lvl in (3, 7) else 1.0
            wall_mult_a = 2.2 if lvl in (4, 9) else 1.0
            b_q = round(base_qty * bias_ratio * wall_mult_b * (1.0 + 0.04 * lvl), 4)
            a_q = round(base_qty * wall_mult_a * (1.0 + 0.04 * lvl), 4)
            bids_20.append((b_px, b_q))
            asks_20.append((a_px, a_q))
        return bids_20, asks_20

    def _init_seed_data(self):
        drifts = {"BTC/USDT": 0.0025, "ETH/USDT": 0.0022, "SOL/USDT": 0.0030}
        starts = {"BTC/USDT": 67200.0, "ETH/USDT": 2580.0, "SOL/USDT": 172.0}
        for i, s in enumerate(self.symbols):
            rng = np.random.default_rng(100 + i)
            n = 160
            rets = rng.normal(drifts.get(s, 0.002), 0.0035, n)
            close = starts.get(s, 100.0) * np.exp(np.cumsum(rets))
            open_ = np.roll(close, 1)
            open_[0] = starts.get(s, 100.0)
            high = np.maximum(open_, close) * (1 + rng.uniform(0.0005, 0.0025, n))
            low = np.minimum(open_, close) * (1 - rng.uniform(0.0005, 0.0025, n))
            vol = rng.uniform(50, 400, n)
            df = pd.DataFrame(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": vol,
                }
            )
            self.candles[s] = df
            self.candles_1h[s] = df.copy()
            self.candles_4h[s] = df.copy()
            mtf_init = multi_timeframe_filter(self.candles_1h[s], self.candles_4h[s])
            self.executor.set_mtf_trend(s, mtf_init)

            px = float(close[-1])
            self.broker.prices[s] = px
            self.executor.last_prices[s] = px
            atr_v = float(Indicators.atr(df["high"], df["low"], df["close"], 14).iloc[-1])
            self.executor.set_atr(s, atr_v)

            # 20 Kademe Emir Defteri Derinlik Analizi başlangıç yüklemesi
            b20, a20 = self._build_synthetic_20_book(px, bias_ratio=1.42)
            self.flows[s].update_book(b20, a20, depth=20)

            base_oi = (
                450_000_000
                if "BTC" in s
                else (180_000_000 if "ETH" in s else 65_000_000)
            )
            self.flows[s].update_open_interest(base_oi, px, time.time() - 120)
            self.flows[s].update_open_interest(base_oi * 1.018, px, time.time())
            for _ in range(30):
                self.flows[s].add_trade(
                    px, rng.uniform(0.2, 1.5), is_buyer_maker=False
                )
            for _ in range(12):
                self.flows[s].add_trade(
                    px, rng.uniform(0.1, 0.8), is_buyer_maker=True
                )

            self.arb.update_quote("binance", s, px * 0.9998, px * 1.0000)
            self.arb.update_quote("okx", s, px * 1.0004, px * 1.0007)

        self.news.push_item(
            "Kurumsal Bitcoin ETF girişleri güçlü seyrediyor, piyasa pozitif",
            "CoinDesk",
        )
        self.add_log(
            "🛡️ KRIPTO-BOT v6 Zırhlı Komuta Paneli başlatıldı (1h/4h MTF Trend Filtresi + 20 Kademe Emir Defteri + Discord/PagerDuty Alarm)."
        )

        if not self.executor.positions:
            btc_px = self.broker.prices["BTC/USDT"]
            qty_btc, info_btc = self.sizer.size(
                self.broker.paper.balance, btc_px, btc_px * 0.95
            )
            pos_btc = Position(
                symbol="BTC/USDT",
                side="LONG",
                entry=round(btc_px * 0.988, 2),
                qty=qty_btc,
                stop=round(btc_px * 0.988 * 0.95, 2),
                leverage=20,
                margin_usdt=info_btc["margin_usdt"],
                layers=2,
                last_add_price=btc_px,
            )
            self.executor.positions["BTC/USDT"] = pos_btc
            self.store.save_position(pos_btc)

            sol_px = self.broker.prices["SOL/USDT"]
            qty_sol, info_sol = self.sizer.size(
                self.broker.paper.balance, sol_px, sol_px * 0.95
            )
            pos_sol = Position(
                symbol="SOL/USDT",
                side="LONG",
                entry=round(sol_px * 0.994, 4),
                qty=qty_sol,
                stop=round(sol_px * 0.994 * 0.95, 4),
                leverage=20,
                margin_usdt=info_sol["margin_usdt"],
                layers=1,
                last_add_price=sol_px,
            )
            self.executor.positions["SOL/USDT"] = pos_sol
            self.store.save_position(pos_sol)

        if not self.store.get_equity_curve(limit=5):
            base_eq = 10_000.0
            for _ in range(25):
                base_eq += float(self._rng.normal(28.0, 35.0))
                self.store.record_equity(
                    10_000.0, round(base_eq, 2), len(self.executor.positions)
                )
        self._sync_health_meta()

    def _sync_health_meta(self):
        bal = round(self.broker.paper.balance, 2)
        unreal = self.executor.total_unrealized_usdt()
        self.store.set_meta(
            "bot_status",
            {
                "ts": time.time(),
                "mode": "PAPER",
                "primary_exchange": self.broker.primary,
                "balance_usdt": bal,
                "equity_usdt": round(bal + unreal, 2),
                "open_positions": len(self.executor.positions),
                "circuit_breaker": self.breaker.snapshot(),
                "exchange_health": self.broker.exchange_health_snapshot(),
                "sqlite_wal": self.store.get_wal_status(),
            },
        )

    async def step_tick(self):
        self._tick_n += 1
        self.breaker.heartbeat_ws()
        mood = self.news.mood()
        fg = mood.get("fear_greed", 50.0)
        veto_app = bool(mood.get("veto_approaching"))
        self.executor.set_market_mood(fear_greed=fg, veto_approaching=veto_app)

        for s in self.symbols:
            df = self.candles[s]
            last_px = float(df["close"].iloc[-1])
            shock = float(self._rng.normal(0.0004, 0.0018))
            new_px = round(last_px * (1.0 + shock), 4)
            high_px = max(last_px, new_px) * (
                1.0 + float(self._rng.uniform(0, 0.0008))
            )
            low_px = min(last_px, new_px) * (
                1.0 - float(self._rng.uniform(0, 0.0008))
            )
            vol = float(self._rng.uniform(60, 280))

            new_row = pd.DataFrame(
                [
                    {
                        "open": last_px,
                        "high": high_px,
                        "low": low_px,
                        "close": new_px,
                        "volume": vol,
                    }
                ]
            )
            df = pd.concat([df.iloc[-180:], new_row], ignore_index=True)
            self.candles[s] = df
            self.broker.prices[s] = new_px

            atr_v = float(
                Indicators.atr(df["high"], df["low"], df["close"], 14).iloc[-1]
            )
            if s not in self.executor._atr or self._tick_n % 5 == 0:
                self.executor.set_atr(s, atr_v)
            dyn_lev, lev_why = self.executor.get_dynamic_leverage(s, new_px)

            is_sell = shock < -0.0002
            self.flows[s].add_trade(
                new_px,
                float(self._rng.uniform(0.3, 2.0)),
                is_buyer_maker=is_sell,
            )
            # 20 Kademe Emir Defteri Derinlik Analizi güncellemesi
            bias_r = float(np.clip(1.25 + shock * 80.0, 0.45, 3.20))
            b20, a20 = self._build_synthetic_20_book(new_px, bias_ratio=bias_r)
            self.flows[s].update_book(b20, a20, depth=20)

            oi_prev = self.flows[s].snapshot().get("open_interest") or 100_000_000
            self.flows[s].update_open_interest(
                oi_prev * (1.0 + shock * 0.8), new_px
            )

            spread_jitter = float(self._rng.normal(0.0003, 0.0006))
            self.arb.update_quote(
                "binance", s, new_px * 0.9999, new_px * 1.0001
            )
            okx_mid = new_px * (1.0 + spread_jitter)
            self.arb.update_quote("okx", s, okx_mid * 0.9999, okx_mid * 1.0002)

            opp = self.arb.check_opportunity(s)
            if opp:
                await self.arb.execute_arbitrage(
                    opp, self.broker, self.executor._say
                )

            await self.executor.on_price_tick(s, new_px)

            ind = indicator_score(df)
            ml_res = self.ml_models[s].predict(df)
            flow_snap = self.flows[s].snapshot()
            fg_tilt = fg - 50.0
            news_blended = round(mood["score"] * 0.7 + fg_tilt * 0.6, 1)
            combined = self.strategy.combine(
                ind["score"], flow_snap["score"], news_blended, ml_res["score"]
            )
            mtf_cur = self.executor.get_mtf_trend(s)
            if not isinstance(mtf_cur, dict):
                mtf_cur = multi_timeframe_filter(
                    self.candles_1h.get(s, df), self.candles_4h.get(s, df)
                )
                self.executor.set_mtf_trend(s, mtf_cur)

            self.live_scores[s] = {
                "symbol": s,
                "price": new_px,
                "total": combined["total"],
                "signal": combined["signal"],
                "indikator": round(ind["score"], 1),
                "para_akisi": flow_snap["score"],
                "haber": news_blended,
                "ml_skor": ml_res["score"],
                "ml_prob_up": round(ml_res["prob_up"] * 100, 1),
                "ml_backend": ml_res["backend"],
                "fear_greed": fg,
                "dynamic_leverage": dyn_lev,
                "leverage_reason": lev_why,
                "active_exchange": self.broker.primary,
                "mtf_trend": mtf_cur.get("trend", "NEUTRAL"),
                "mtf_score": mtf_cur.get("score", 0.0),
                "bid_ask_ratio": flow_snap.get("bid_ask_ratio", 1.0),
                "wall_signal": flow_snap.get("wall_signal", "DENGELI"),
                "bid_depth_usdt": flow_snap.get("bid_depth_usdt", 0.0),
                "ask_depth_usdt": flow_snap.get("ask_depth_usdt", 0.0),
                "squeeze": flow_snap.get("squeeze", "YOK"),
                "oi": flow_snap.get("open_interest", 0.0),
                "oi_change_pct": flow_snap.get("oi_change_pct", 0.0),
                "short_liq_usdt": flow_snap.get("short_liq_usdt", 0.0),
                "long_liq_usdt": flow_snap.get("long_liq_usdt", 0.0),
            }

            if self._tick_n % 4 == 0:
                await self.executor.on_signal(
                    s,
                    new_px,
                    combined,
                    flow_snap["score"],
                    bool(mood["veto"]),
                    bool(mood.get("veto_long")),
                    bool(mood.get("veto_short")),
                    mtf_trend=mtf_cur,
                )

        bal = self.broker.paper.balance
        unreal = self.executor.total_unrealized_usdt()
        if self._tick_n % 3 == 0:
            self.store.record_equity(
                bal, round(bal + unreal, 2), len(self.executor.positions)
            )
        self._sync_health_meta()

    async def handle_action(self, action: str, payload: dict) -> dict:
        if action == "kill_switch":
            self.breaker.trip("MANUEL ACİL DURUM KILL-SWITCH (Web Paneli)")
            closed = await self.executor.close_all_positions("MANUEL KILL-SWITCH")
            self.store.push_command("KILL_SWITCH")
            self._sync_health_meta()
            return {
                "ok": True,
                "message": f"🚨 KILL SWITCH AKTİF: {closed} açık pozisyon anında kapatıldı ve bot kilitlendi!",
            }

        if action == "toggle_pause":
            new_state = not self.breaker.paused
            self.breaker.set_paused(new_state)
            self.store.push_command("PAUSE" if new_state else "RESUME")
            msg = (
                "⏸️ Bot duraklatıldı (yeni işlem açılmaz)."
                if new_state
                else "▶️ Bot tekrar aktif edildi."
            )
            self.add_log(msg)
            self._sync_health_meta()
            return {"ok": True, "message": msg}

        if action == "reset_breaker":
            self.breaker.reset()
            self.store.push_command("RESET_BREAKER")
            await self.multi_alerter.resolve_pagerduty(
                "Circuit Breaker sıfırlandı, sistem normale döndü"
            )
            self.add_log(
                "🔄 Circuit Breaker (Acil Durum Sigortası) sıfırlandı, PagerDuty incident resolve edildi."
            )
            self._sync_health_meta()
            return {"ok": True, "message": "🔄 Sigorta sıfırlandı ve PagerDuty incident kapatıldı."}

        if action == "sim_mtf_filter":
            sym = "ETH/USDT"
            px = self.broker.prices[sym]
            # 1h ve 4h ana trendi sert DÜŞÜŞ (BEARISH = -68.0) olarak ayarla
            bear_mtf = {
                "trend": "BEARISH",
                "score": -68.0,
                "allow_long": False,
                "allow_short": True,
                "reason": "1h/4h Ana Trend DÜŞÜŞ (-68.0) → Küçük tepkilerde LONG engellendi",
            }
            self.executor.set_mtf_trend(sym, bear_mtf)
            # 1m/5m grafikte sahte bir LONG tepki sinyali (+74.0) gönder
            fake_long_sig = {"total": 74.0, "signal": "LONG", "parts": {}}
            self.executor.positions.pop(sym, None)
            await self.executor.on_signal(
                sym, px, fake_long_sig, 45.0, False, mtf_trend=bear_mtf
            )
            msg = (
                f"📉 MTF TREND FİLTRESİ DEVREDE ({sym}): 1m/5m sinyal +74.0 (LONG) olmasına rağmen "
                f"1h/4h ana trend DÜŞÜŞ (BEARISH, skor -68.0) olduğu için tuzak LONG girişi engellendi! "
                f"(Toplam engellenen: {self.executor.stats.get('mtf_filtered', 0)})"
            )
            self.add_log(msg)
            return {"ok": True, "message": msg}

        if action == "sim_depth_wall":
            sym = "BTC/USDT"
            px = self.broker.prices[sym]
            b20, a20 = self._build_synthetic_20_book(px, bias_ratio=3.10)
            dep = self.flows[sym].update_book(b20, a20, depth=20)
            snap = self.flows[sym].snapshot()
            msg = (
                f"📚 20 KADEME EMİR DEFTERİ ANALİZİ ({sym}): "
                f"Alıcı Duvarı ${dep['bid_depth_usdt']:,.0f} vs Satıcı ${dep['ask_depth_usdt']:,.0f} | "
                f"Bid/Ask Ratio: {dep['bid_ask_ratio']:.2f}x ({dep['wall_signal']}) → "
                f"Skor katkısı: {dep['depth_score_boost']:+.1f} | Yeni Akış Skoru: {snap['score']:+.1f}"
            )
            self.add_log(msg)
            return {"ok": True, "message": msg}

        if action == "sim_discord_pagerduty":
            alert_msg = (
                "🚨 [KRİTİK ALARM TESTİ] Circuit Breaker & PagerDuty/Discord Webhook Entegrasyonu: "
                "Sunucu acil durum sesli telefon alarmı (PagerDuty severity=critical) + Discord @everyone Embed tetiklendi!"
            )
            rec = await self.multi_alerter.send(
                alert_msg,
                force_critical=True,
                custom_details={"source": "web_dashboard_test", "equity": self.broker.paper.balance},
            )
            self.add_log(
                f"🔔 [Discord + PagerDuty Alarm] Kanallar: {', '.join(rec['channels'])} | "
                f"Discord: {rec['discord_embed_title']} | PagerDuty: {rec['pagerduty_severity']}"
            )
            return {
                "ok": True,
                "message": (
                    f"🔔 Discord (@everyone Embed) + PagerDuty (severity=critical telefon alarmı) tetiklendi! "
                    f"Toplam PagerDuty: {self.multi_alerter.stats['pagerduty_triggered']} | Discord: {self.multi_alerter.stats['discord_dispatched']}"
                ),
            }

        if action == "sim_failover":
            # Binance'te ardı ardına 3 timeout hatası simüle et -> Otomatik OKX geçişi
            for i in range(1, 4):
                self.broker.record_exchange_timeout(
                    "binance", f"RequestTimeout: Binance API 504 Gateway Timeout (#{i})"
                )
            msg = (
                f"🔀 MULTI-EXCHANGE FAILOVER AKTİF: Binance API ardı ardına 3 timeout hatası verdi! "
                f"İşlem ağırlığı ve yeni pozisyonlar kesintisiz olarak yedek borsaya ({self.broker.primary.upper()}) kaydırıldı."
            )
            self.add_log(msg)
            self._sync_health_meta()
            return {"ok": True, "message": msg}

        if action == "recover_exchange":
            self.broker.record_exchange_success("binance")
            self.broker.record_exchange_success("okx")
            msg = "✅ Binance API bağlantısı normale döndü; birincil borsa tekrar BINANCE olarak ayarlandı."
            self.add_log(msg)
            self._sync_health_meta()
            return {"ok": True, "message": msg}

        if action == "run_gc":
            res = self.store.run_garbage_collector(
                max_trades=500, max_equity=500, max_arb=300
            )
            msg = (
                f"🧹 SQLite WAL & VACUUM Çöp Toplayıcı tamamlandı | "
                f"Mod: {res['journal_mode'].upper()} | Arşivlenen: {res['archived_count']} satır | "
                f"DB Boyutu: {res['size_before_bytes']:,}B → {res['size_after_bytes']:,}B "
                f"(VACUUM #{res['vacuum_runs']})"
            )
            self.add_log(msg)
            self._sync_health_meta()
            return {"ok": True, "message": msg}

        if action == "close_symbol":
            sym = payload.get("symbol", "")
            if sym in self.executor.positions:
                pos = self.executor.positions[sym]
                px = self.broker.prices.get(sym, pos.entry)
                pnl = self.risk.profit_pct(pos, px)
                await self.executor._close(
                    sym, px, "WEB PANELİ MANUEL KAPAMA", pnl
                )
                self._sync_health_meta()
                return {"ok": True, "message": f"✅ {sym} pozisyonu kapatıldı."}
            return {"ok": False, "message": f"{sym} açık pozisyon bulunamadı."}

        if action == "sim_pyramid":
            sym = "BTC/USDT"
            px = self.broker.prices[sym]
            if sym not in self.executor.positions:
                await self.executor._open(
                    sym, "LONG", px * 0.99, "Web Paneli: %10 Kasa × 20x İlk Giriş"
                )
            pos = self.executor.positions[sym]
            win_px = round(max(px, pos.entry * 1.012), 2)
            self.broker.prices[sym] = win_px
            self.executor.last_prices[sym] = win_px
            await self.executor._add_layer(
                sym, win_px, "Artıda Sınırsız Pozisyon Ekleme (%10 Kasa × 20x)"
            )
            return {
                "ok": True,
                "message": f"➕ {sym} artıdayken {pos.layers}. kademe eklendi! Toplam Marj: ${pos.margin_usdt:,.0f}",
            }

        if action == "sim_pair_rescue":
            btc_px = self.broker.prices["BTC/USDT"]
            eth_px = self.broker.prices["ETH/USDT"]
            qty_b, info_b = self.sizer.size(
                self.broker.paper.balance, btc_px, btc_px * 0.95
            )
            qty_e, info_e = self.sizer.size(
                self.broker.paper.balance, eth_px, eth_px * 0.95
            )

            self.executor.positions["BTC/USDT"] = Position(
                symbol="BTC/USDT",
                side="LONG",
                entry=round(btc_px / 1.014, 2),
                qty=qty_b,
                stop=round(btc_px * 0.94, 2),
                leverage=20,
                margin_usdt=info_b["margin_usdt"],
                layers=1,
            )
            self.executor.positions["ETH/USDT"] = Position(
                symbol="ETH/USDT",
                side="LONG",
                entry=round(eth_px / 0.9885, 2),
                qty=qty_e,
                stop=round(eth_px * 0.94, 2),
                leverage=20,
                margin_usdt=info_e["margin_usdt"],
                layers=1,
            )
            self.executor.last_prices["BTC/USDT"] = btc_px
            self.executor.last_prices["ETH/USDT"] = eth_px
            rescue = self.risk.find_pair_rescue(
                self.executor.positions, self.executor.last_prices
            )
            if rescue:
                await self.executor.execute_pair_rescue(rescue)
                return {"ok": True, "message": f"⚖️ {rescue['reason']}"}
            return {"ok": False, "message": "Çapraz kurtarma koşulu oluşmadı."}

        if action == "sim_dynamic_lev":
            sym = "BTC/USDT"
            px = self.broker.prices[sym]
            self.executor.set_atr(sym, px * 0.020)
            lev, why = self.executor.get_dynamic_leverage(sym, px)
            self.add_log(f"🔄 DİNAMİK KALDIRAÇ | {sym}: 20x → {lev}x ({why})")
            return {
                "ok": True,
                "message": f"🔄 Dinamik Kaldıraç Devrede ({sym}): ATR yükseldiği için kaldıraç 20x → {lev}x seviyesine çekildi ({why})!",
            }

        if action == "sim_chase_order":
            sym = "ETH/USDT"
            px = self.broker.prices[sym]
            fill = await self.broker.execute_entry(
                sym,
                "buy",
                1.0,
                price_hint=px * 1.0065,
                expected_price=px,
            )
            self.executor.stats["chase_orders"] += 1
            msg = (
                f"🎯 CHASE ORDER | {sym}: Anlık kayma %{fill.get('raw_slippage_pct', 0.65):.2f} > maks %0.30! "
                f"Market iptal edildi → Chase Limit @ ${fill['price']:,.2f} (Kurtarılan kayma: %{fill.get('saved_slippage_pct', 0.35):.2f})"
            )
            self.add_log(msg)
            return {"ok": True, "message": msg}

        if action == "sim_tg_durum":
            rep = await self.tg_bot.handle_command(
                "/durum", sender_chat_id=self.tg_bot.allowed_chat_id
            )
            first_line = rep.splitlines()[0] if rep else "/durum"
            self.add_log(f"📲 [Telegram /durum] {rep.replace(chr(10), ' | ')}")
            return {
                "ok": True,
                "message": f"📲 Telegram /durum yanıtı üretildi: {first_line} (Log kutusunda tam rapor)",
            }

        if action == "sim_squeeze":
            sym = "SOL/USDT"
            px = self.broker.prices[sym]
            self.flows[sym].add_liquidation("SHORT_LIQ", px, 1200.0)
            snap = self.flows[sym].snapshot()
            self.add_log(
                f"💥 SHORT SQUEEZE PATLAMASI | {sym} | Short Tasfiye: ${snap['short_liq_usdt']:,.0f} | Akış Skoru: {snap['score']:+.1f}"
            )
            return {
                "ok": True,
                "message": f"💥 {sym} üzerinde ${snap['short_liq_usdt']:,.0f} Short Tasfiyesi (SHORT SQUEEZE) algılandı! Akış skoru: {snap['score']:+.1f}",
            }

        if action == "sim_arbitrage":
            sym = "BTC/USDT"
            px = self.broker.prices[sym]
            self.arb._last_exec.pop(sym, None)
            self.arb.update_quote("binance", sym, px * 0.9995, px * 1.0000)
            self.arb.update_quote("okx", sym, px * 1.0028, px * 1.0032)
            opp = self.arb.check_opportunity(sym)
            if opp:
                rec = await self.arb.execute_arbitrage(
                    opp, self.broker, self.executor._say
                )
                return {
                    "ok": True,
                    "message": f"⚡ Çapraz Arbitraj: Binance AL @ {rec['buy_price']:,.2f} → OKX SAT @ {rec['sell_price']:,.2f} | Net Kâr: +${rec['profit_usdt']:.2f}",
                }
            return {"ok": False, "message": "Spread eşiği altında."}

        return {"ok": False, "message": "Bilinmeyen komut"}

    def build_state_payload(self) -> dict:
        bal = round(self.broker.paper.balance, 2)
        unreal = self.executor.total_unrealized_usdt()
        equity = round(bal + unreal, 2)
        total_ret_pct = round(
            (equity / self.broker.paper.start_balance - 1.0) * 100.0, 2
        )

        open_rows = []
        for sym, pos in self.executor.positions.items():
            px = self.broker.prices.get(sym, pos.entry)
            pnl_pct = round(self.risk.profit_pct(pos, px), 2)
            roe_pct = round(self.risk.roe_pct(pos, px), 1)
            pnl_usd = round(self.risk.pnl_usdt(pos, px), 2)
            open_rows.append(
                {
                    "symbol": sym,
                    "side": pos.side,
                    "entry": round(pos.entry, 4),
                    "price": round(px, 4),
                    "qty": round(pos.qty, 5),
                    "leverage": pos.leverage,
                    "margin_usdt": round(pos.margin_usdt, 2),
                    "notional_usdt": round(pos.entry * pos.qty, 2),
                    "layers": pos.layers,
                    "stop": round(pos.stop, 4),
                    "locked_profit": pos.locked_profit,
                    "pnl_pct": pnl_pct,
                    "roe_pct": roe_pct,
                    "pnl_usdt": pnl_usd,
                }
            )

        return {
            "ts": time.strftime("%H:%M:%S"),
            "balance_usdt": bal,
            "unrealized_usdt": unreal,
            "equity_usdt": equity,
            "total_return_pct": total_ret_pct,
            "leverage": self.leverage,
            "capital_pct": self.capital_pct,
            "stop_loss_pct": self.risk.stop_loss_pct,
            "max_slippage_pct": self.risk.max_slippage_pct,
            "stats": self.executor.stats,
            "circuit_breaker": self.breaker.snapshot(),
            "exchange_health": self.broker.exchange_health_snapshot(),
            "sqlite_wal": self.store.get_wal_status(),
            "alert_channels": self.multi_alerter.snapshot(),
            "open_positions": open_rows,
            "scores": list(self.live_scores.values()),
            "arbitrage_quotes": self.arb.scan_all(self.symbols),
            "arbitrage_history": list(self.arb.history)[:10],
            "arb_total_profit": self.arb.total_profit_usdt,
            "equity_curve": self.store.get_equity_curve(limit=60),
            "recent_trades": self.store.get_trades(limit=12),
            "logs": list(self.logs)[:25],
        }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>KRIPTO-BOT v5 — Multi-Exchange Failover, SQLite WAL & Gerçek Zamanlı Komuta Paneli</title>
<style>
  :root {
    --bg: #0b0f19;
    --card: #111827;
    --card2: #161f33;
    --border: #1f2937;
    --text: #f3f4f6;
    --muted: #9ca3af;
    --green: #10b981;
    --red: #ef4444;
    --amber: #f59e0b;
    --blue: #3b82f6;
    --purple: #8b5cf6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13.5px;
    line-height: 1.45;
    padding: 16px;
  }
  .topbar {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    background: linear-gradient(135deg, #111827 0%, #172554 100%);
    border: 1px solid #1e3a8a;
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 14px;
  }
  .brand h1 { font-size: 18px; font-weight: 800; letter-spacing: 0.3px; }
  .brand p { color: #93c5fd; font-size: 12px; margin-top: 2px; }
  .badges { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .badge {
    padding: 5px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 700;
    background: #1f2937;
    border: 1px solid #374151;
  }
  .badge.green { background: rgba(16,185,129,0.15); color: #34d399; border-color: rgba(16,185,129,0.4); }
  .badge.red { background: rgba(239,68,68,0.2); color: #f87171; border-color: rgba(239,68,68,0.5); }
  .badge.amber { background: rgba(245,158,11,0.18); color: #fbbf24; border-color: rgba(245,158,11,0.4); }
  .badge.purple { background: rgba(139,92,246,0.18); color: #c4b5fd; border-color: rgba(139,92,246,0.4); }

  .controls {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 14px;
  }
  button {
    cursor: pointer;
    border: none;
    border-radius: 8px;
    padding: 9px 13px;
    font-weight: 700;
    font-size: 12px;
    color: #fff;
    transition: all 0.15s ease;
  }
  button:hover { filter: brightness(1.12); transform: translateY(-1px); }
  .btn-kill { background: linear-gradient(135deg, #dc2626, #991b1b); box-shadow: 0 0 14px rgba(239,68,68,0.4); }
  .btn-pause { background: #2563eb; }
  .btn-reset { background: #4b5563; }
  .btn-sim { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; }

  .toast {
    display: none;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 14px;
    font-weight: 600;
    background: rgba(59,130,246,0.18);
    border: 1px solid #3b82f6;
    color: #bfdbfe;
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
    gap: 12px;
    margin-bottom: 14px;
  }
  .kpi {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
  }
  .kpi .lbl { color: var(--muted); font-size: 11.5px; text-transform: uppercase; }
  .kpi .val { font-size: 19px; font-weight: 800; margin-top: 4px; }
  .kpi .sub { font-size: 11.5px; color: var(--muted); margin-top: 2px; }

  .main-grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 14px;
    margin-bottom: 14px;
  }
  @media (max-width: 1024px) { .main-grid { grid-template-columns: 1fr; } }

  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    margin-bottom: 14px;
  }
  .panel h2 {
    font-size: 14.5px;
    font-weight: 700;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: #e5e7eb;
  }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { padding: 8px 8px; text-align: left; border-bottom: 1px solid #1f2937; }
  th { color: var(--muted); font-weight: 600; font-size: 11.5px; text-transform: uppercase; }
  .pos { color: var(--green); font-weight: 700; }
  .neg { color: var(--red); font-weight: 700; }
  .tag-long { background: rgba(16,185,129,0.18); color: #34d399; padding: 2px 7px; border-radius: 4px; font-weight: 700; }
  .tag-short { background: rgba(239,68,68,0.18); color: #f87171; padding: 2px 7px; border-radius: 4px; font-weight: 700; }

  .score-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
  }
  .scard {
    background: var(--card2);
    border: 1px solid #26324d;
    border-radius: 9px;
    padding: 12px;
  }
  .scard-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .bar-wrap { height: 7px; background: #1f2937; border-radius: 4px; overflow: hidden; margin: 6px 0; }
  .bar-fill { height: 100%; transition: width 0.3s ease; }
  .metrics-row { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--muted); margin-top: 4px; }
  .log-box { max-height: 220px; overflow-y: auto; font-family: monospace; font-size: 12px; }
  .log-item { padding: 4px 0; border-bottom: 1px dashed #1f2937; }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <h1>🛡️ KRIPTO-BOT v6 — MTF 1h/4h Trend, 20 Kademe Emir Defteri, Discord/PagerDuty & Komuta Paneli</h1>
    <p>1h/4h MTF Trend Filtresi • 20 Kademe Emir Defteri (Bid/Ask Ratio) • Discord & PagerDuty Alarm • Multi-Exchange Failover • SQLite WAL & VACUUM • %10 Kasa × Dinamik 20x/10x/5x</p>
  </div>
  <div class="badges">
    <span id="statusBadge" class="badge green">AKTİF & GÜVENLİ</span>
    <span id="exBadge" class="badge green">AKTİF BORSA: BINANCE</span>
    <span class="badge purple">1h/4h MTF FİLTRESİ + 20 KADEME DEPTH</span>
    <span id="alertBadge" class="badge amber">DISCORD & PAGERDUTY ALARM</span>
    <span id="clockBadge" class="badge">--:--:--</span>
  </div>
</div>

<div class="controls">
  <button class="btn-kill" onclick="sendAction('kill_switch')">🚨 ACİL KILL SWITCH (Tüm Pozisyonları Kapat)</button>
  <button id="pauseBtn" class="btn-pause" onclick="sendAction('toggle_pause')">⏸️ Botu Duraklat / Başlat</button>
  <button class="btn-reset" onclick="sendAction('reset_breaker')">🔄 Sigortayı Sıfırla</button>
  <button class="btn-sim" onclick="sendAction('sim_mtf_filter')">📉 1h/4h MTF Düşüş Trendi Filtresi Test</button>
  <button class="btn-sim" onclick="sendAction('sim_depth_wall')">📚 20 Kademe Emir Defteri (Bid/Ask Ratio) Test</button>
  <button class="btn-sim" onclick="sendAction('sim_discord_pagerduty')">🔔 Discord & PagerDuty Acil Alarm Test</button>
  <button class="btn-sim" onclick="sendAction('sim_failover')">🔀 Binance 3x Timeout → OKX Failover Test</button>
  <button class="btn-sim" onclick="sendAction('recover_exchange')">✅ Binance Normale Döndür</button>
  <button class="btn-sim" onclick="sendAction('run_gc')">🧹 SQLite WAL & VACUUM</button>
  <button class="btn-sim" onclick="sendAction('sim_pyramid')">➕ Artıda Kademe Ekle</button>
  <button class="btn-sim" onclick="sendAction('sim_pair_rescue')">⚖️ Çapraz İkili Kurtarma</button>
  <button class="btn-sim" onclick="sendAction('sim_chase_order')">🎯 Chase Order (%0.30 Kayma)</button>
</div>

<div id="toast" class="toast"></div>

<div class="kpi-grid">
  <div class="kpi">
    <div class="lbl">Anlık Özsermaye (Equity)</div>
    <div id="kpiEquity" class="val">$10,000.00</div>
    <div id="kpiReturn" class="sub">%0.00 toplam getiri</div>
  </div>
  <div class="kpi">
    <div class="lbl">Nakit Kasa / Açık PnL</div>
    <div id="kpiBalance" class="val">$10,000.00</div>
    <div id="kpiUnreal" class="sub">Açık K/Z: $0.00</div>
  </div>
  <div class="kpi">
    <div class="lbl">Multi-Exchange Failover</div>
    <div id="kpiExchange" class="val">BINANCE (Birincil)</div>
    <div id="kpiExchangeSub" class="sub">Binance Timeout: 0/3 | Yedek: OKX</div>
  </div>
  <div class="kpi">
    <div class="lbl">SQLite WAL & VACUUM GC</div>
    <div id="kpiWal" class="val">WAL AKTİF</div>
    <div id="kpiWalSub" class="sub">Boyut: 0 KB | VACUUM: 0</div>
  </div>
  <div class="kpi">
    <div class="lbl">Dinamik Kaldıraç & Kayma</div>
    <div class="val">20x → 10x → 5x</div>
    <div id="kpiChase" class="sub">Max Kayma %0.30 | 0 Chase</div>
  </div>
  <div class="kpi">
    <div class="lbl">Circuit Breaker & /health</div>
    <div id="kpiBreaker" class="val" style="font-size:14.5px;">GÜVENLİ</div>
    <div id="kpiBreakerSub" class="sub">GET /health (200 OK) • /metrics</div>
  </div>
</div>

<div class="main-grid">
  <div class="panel">
    <h2>
      <span>📌 Anlık Açık Pozisyonlar (SQLite WAL Kalıcı + Artıda Sınırsız Ekleme + Çapraz Kurtarma)</span>
      <span id="openCountBadge" class="badge">0 Açık</span>
    </h2>
    <table>
      <thead>
        <tr>
          <th>Sembol</th>
          <th>Yön</th>
          <th>Kademe</th>
          <th>Kaldıraç</th>
          <th>Ort. Giriş</th>
          <th>Anlık Fiyat</th>
          <th>Marj (%10)</th>
          <th>Büyüklük ($)</th>
          <th>Stop (-%5)</th>
          <th>Fiyat PnL</th>
          <th>ROE</th>
          <th>Net K/Z ($)</th>
          <th>İşlem</th>
        </tr>
      </thead>
      <tbody id="openPositionsBody"></tbody>
    </table>
  </div>

  <div class="panel">
    <h2><span>📈 Canlı Kâr / Zarar Eğrisi (Equity Curve)</span></h2>
    <svg id="equitySvg" width="100%" height="195" viewBox="0 0 500 195" preserveAspectRatio="none" style="background:#0d1322;border-radius:8px;border:1px solid #1f2937;"></svg>
  </div>
</div>

<div class="panel">
  <h2><span>🧠 Aktif Sinyal Motoru: 13 İndikatör + OI/Likidasyon Squeeze + Haber/FG + ML Yön Tahmini + Dinamik Kaldıraç</span></h2>
  <div id="scoreCards" class="score-cards"></div>
</div>

<div class="main-grid">
  <div class="panel">
    <h2><span>⚡ Çapraz Borsa Arbitraj Tarayıcısı (Binance ↔ OKX Canlı Spread)</span></h2>
    <table>
      <thead>
        <tr>
          <th>Parite</th>
          <th>Ucuz Borsa (AL)</th>
          <th>Alış Fiyatı</th>
          <th>Pahalı Borsa (SAT)</th>
          <th>Satış Fiyatı</th>
          <th>Brüt Fark</th>
          <th>Net Fark (Komisyon Sonrası)</th>
          <th>Tahmini Net Kâr ($1K)</th>
          <th>Durum</th>
        </tr>
      </thead>
      <tbody id="arbQuotesBody"></tbody>
    </table>
  </div>

  <div class="panel">
    <h2><span>📜 Canlı Sistem & Güvenlik Günlüğü (Anahtarlar Maskeli)</span></h2>
    <div id="logBox" class="log-box"></div>
  </div>
</div>

<div class="panel">
  <h2><span>🏁 Son Kapanan İşlemler (SQLite Kayıtlı)</span></h2>
  <table>
    <thead>
      <tr>
        <th>Sembol</th>
        <th>Yön</th>
        <th>Kademe</th>
        <th>Giriş</th>
        <th>Çıkış</th>
        <th>Fiyat PnL %</th>
        <th>ROE %</th>
        <th>Net K/Z ($)</th>
        <th>Kapanış Nedeni</th>
      </tr>
    </thead>
    <tbody id="tradesBody"></tbody>
  </table>
</div>

<script>
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4800);
}

async function sendAction(action, payload = {}) {
  try {
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action, payload})
    });
    const data = await res.json();
    if (data.message) showToast(data.message);
    await refreshState();
  } catch (e) {
    showToast('Komut hatası: ' + e);
  }
}

function drawEquity(curve) {
  const svg = document.getElementById('equitySvg');
  if (!curve || curve.length < 2) return;
  const vals = curve.map(c => c.equity_usdt);
  const minV = Math.min(...vals) * 0.999;
  const maxV = Math.max(...vals) * 1.001;
  const range = Math.max(maxV - minV, 1);
  const W = 500, H = 195, pad = 18;
  const pts = vals.map((v, i) => {
    const x = pad + (i / (vals.length - 1)) * (W - pad * 2);
    const y = H - pad - ((v - minV) / range) * (H - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const first = vals[0], last = vals[vals.length - 1];
  const color = last >= first ? '#10b981' : '#ef4444';
  svg.innerHTML = `
    <polyline fill="none" stroke="${color}" stroke-width="2.6" points="${pts}" />
    <text x="14" y="20" fill="#9ca3af" font-size="11">Zirve: $${Math.max(...vals).toFixed(2)}</text>
    <text x="14" y="185" fill="#9ca3af" font-size="11">Dip: $${Math.min(...vals).toFixed(2)}</text>
    <text x="370" y="20" fill="${color}" font-weight="bold" font-size="12">Son: $${last.toFixed(2)}</text>
  `;
}

async function refreshState() {
  try {
    const res = await fetch('/api/state');
    const d = await res.json();

    document.getElementById('clockBadge').textContent = 'Canlı: ' + d.ts;
    document.getElementById('kpiEquity').textContent = '$' + d.equity_usdt.toLocaleString('en-US', {minimumFractionDigits:2});
    const retEl = document.getElementById('kpiReturn');
    retEl.textContent = (d.total_return_pct >= 0 ? '+' : '') + d.total_return_pct + '% toplam getiri';
    retEl.className = 'sub ' + (d.total_return_pct >= 0 ? 'pos' : 'neg');

    document.getElementById('kpiBalance').textContent = '$' + d.balance_usdt.toLocaleString('en-US', {minimumFractionDigits:2});
    const unEl = document.getElementById('kpiUnreal');
    unEl.textContent = 'Açık K/Z: ' + (d.unrealized_usdt >= 0 ? '+$' : '-$') + Math.abs(d.unrealized_usdt).toFixed(2);
    unEl.className = 'sub ' + (d.unrealized_usdt >= 0 ? 'pos' : 'neg');

    document.getElementById('kpiChase').textContent =
      `Max Kayma %${d.max_slippage_pct} | ${d.stats.chase_orders || 0} Chase | MTF Engel: ${d.stats.mtf_filtered || 0}`;

    const ac = (d.alert_channels || {}).stats || {};
    const ab = document.getElementById('alertBadge');
    if (ab) {
      ab.textContent = `🔔 Discord: ${ac.discord_dispatched || 0} | PagerDuty: ${ac.pagerduty_triggered || 0}`;
    }

    const eh = d.exchange_health || {};
    const activeEx = (eh.active_primary || 'binance').toUpperCase();
    const foActive = Boolean(eh.failover_active);
    const binTo = ((eh.exchanges || {}).binance || {}).consecutive_timeouts || 0;
    document.getElementById('kpiExchange').textContent = foActive ? `${activeEx} (FAILOVER YEDEK)` : `${activeEx} (Birincil)`;
    document.getElementById('kpiExchangeSub').textContent =
      `Binance Timeout: ${binTo}/3 | Yedek: ${(eh.backup_exchange || 'okx').toUpperCase()}`;
    const exBadge = document.getElementById('exBadge');
    exBadge.textContent = foActive ? `🔀 FAILOVER AKTİF: ${activeEx}` : `AKTİF BORSA: ${activeEx}`;
    exBadge.className = 'badge ' + (foActive ? 'amber' : 'green');

    const wal = d.sqlite_wal || {};
    document.getElementById('kpiWal').textContent = `MOD: ${(wal.journal_mode || 'wal').toUpperCase()}`;
    document.getElementById('kpiWalSub').textContent =
      `DB: ${((wal.db_size_bytes || 0) / 1024).toFixed(1)} KB | VACUUM: ${wal.vacuum_runs || 0}x`;

    const cb = d.circuit_breaker;
    const sb = document.getElementById('statusBadge');
    sb.textContent = cb.status;
    sb.className = 'badge ' + (cb.tripped ? 'red' : (cb.paused ? 'amber' : 'green'));
    document.getElementById('kpiBreaker').textContent = cb.status;
    document.getElementById('kpiBreakerSub').textContent =
      `Emir: ${cb.consecutive_errors}/${cb.max_consecutive_errors} | Yetki: ${cb.consecutive_auth_errors || 0}/3 | /health: ${cb.tripped ? '503' : '200 OK'}`;

    document.getElementById('openCountBadge').textContent = d.open_positions.length + ' Açık Pozisyon';
    const opBody = document.getElementById('openPositionsBody');
    if (d.open_positions.length === 0) {
      opBody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:#9ca3af;padding:16px;">Şu anda açık pozisyon yok. Sinyal bekleniyor veya üstteki düğmelerle test edebilirsiniz.</td></tr>';
    } else {
      opBody.innerHTML = d.open_positions.map(p => `
        <tr>
          <td><b>${p.symbol}</b></td>
          <td><span class="${p.side === 'LONG' ? 'tag-long' : 'tag-short'}">${p.side}</span></td>
          <td><b>${p.layers}. Kademe</b></td>
          <td>${p.leverage}x</td>
          <td>$${p.entry.toLocaleString()}</td>
          <td>$${p.price.toLocaleString()}</td>
          <td>$${p.margin_usdt.toLocaleString()}</td>
          <td>$${p.notional_usdt.toLocaleString()}</td>
          <td>$${p.stop.toLocaleString()} ${p.locked_profit ? '🔒' : ''}</td>
          <td class="${p.pnl_pct >= 0 ? 'pos' : 'neg'}">${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct}%</td>
          <td class="${p.roe_pct >= 0 ? 'pos' : 'neg'}">${p.roe_pct >= 0 ? '+' : ''}${p.roe_pct}%</td>
          <td class="${p.pnl_usdt >= 0 ? 'pos' : 'neg'}">${p.pnl_usdt >= 0 ? '+$' : '-$'}${Math.abs(p.pnl_usdt).toFixed(2)}</td>
          <td><button style="padding:4px 9px;background:#ef4444;font-size:11px;" onclick="sendAction('close_symbol', {symbol:'${p.symbol}'})">Kapat</button></td>
        </tr>
      `).join('');
    }

    const sc = document.getElementById('scoreCards');
    sc.innerHTML = d.scores.map(s => {
      const pct = Math.min(100, Math.max(0, (s.total + 100) / 2));
      const col = s.total >= 55 ? '#10b981' : (s.total <= -55 ? '#ef4444' : '#3b82f6');
      return `
        <div class="scard">
          <div class="scard-head">
            <span><b>${s.symbol}</b> — $${s.price.toLocaleString()}</span>
            <span class="badge ${s.signal === 'LONG' ? 'green' : (s.signal === 'SHORT' ? 'red' : '')}">${s.signal} (${s.total})</span>
          </div>
          <div class="bar-wrap"><div class="bar-fill" style="width:${pct}%;background:${col};"></div></div>
          <div class="metrics-row">
            <span>İndikatör: <b>${s.indikator}</b></span>
            <span>Para Akışı: <b>${s.para_akisi}</b></span>
            <span>Haber/FG: <b>${s.haber}</b> (${s.fear_greed})</span>
          </div>
          <div class="metrics-row">
            <span>🤖 ML (${s.ml_backend}): <b>${s.ml_skor}</b> (%${s.ml_prob_up} ↑)</span>
            <span>🔄 Kaldıraç: <b>${s.dynamic_leverage || 20}x</b> (${(s.active_exchange || 'binance').toUpperCase()})</span>
          </div>
          <div class="metrics-row">
            <span>🧭 1h/4h MTF Trend: <b>${s.mtf_trend || 'NEUTRAL'}</b> (${s.mtf_score >= 0 ? '+' : ''}${s.mtf_score || 0})</span>
            <span>📚 20-Kademe Bid/Ask: <b>${(s.bid_ask_ratio || 1).toFixed(2)}x</b> (${s.wall_signal || 'DENGELI'})</span>
          </div>
          <div class="metrics-row">
            <span>📊 OI Değişim: <b>%${s.oi_change_pct}</b> | Squeeze: <b>${s.squeeze}</b></span>
            <span>Tasfiye S/L: <b>$${(s.short_liq_usdt/1000).toFixed(0)}K/$${(s.long_liq_usdt/1000).toFixed(0)}K</b></span>
          </div>
        </div>
      `;
    }).join('');

    const arbBody = document.getElementById('arbQuotesBody');
    arbBody.innerHTML = d.arbitrage_quotes.map(a => `
      <tr>
        <td><b>${a.symbol}</b></td>
        <td>${a.buy_exchange.toUpperCase()}</td>
        <td>$${a.buy_price.toLocaleString()}</td>
        <td>${a.sell_exchange.toUpperCase()}</td>
        <td>$${a.sell_price.toLocaleString()}</td>
        <td>%${a.gross_spread_pct}</td>
        <td class="${a.net_spread_pct > 0 ? 'pos' : 'neg'}">%${a.net_spread_pct}</td>
        <td class="${a.est_profit_usdt > 0 ? 'pos' : ''}">$${a.est_profit_usdt}</td>
        <td>${a.actionable ? '<span class="tag-long">ARBİTRAJ AKTİF</span>' : '<span style="color:#9ca3af">İzleniyor</span>'}</td>
      </tr>
    `).join('');

    document.getElementById('logBox').innerHTML = d.logs.map(l =>
      `<div class="log-item"><span style="color:#60a5fa">[${l.ts}]</span> ${l.text}</div>`
    ).join('');

    const trBody = document.getElementById('tradesBody');
    if (!d.recent_trades || d.recent_trades.length === 0) {
      trBody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#9ca3af;">Henüz kapanan işlem yok.</td></tr>';
    } else {
      trBody.innerHTML = d.recent_trades.map(t => `
        <tr>
          <td><b>${t.symbol}</b></td>
          <td><span class="${t.side === 'LONG' ? 'tag-long' : 'tag-short'}">${t.side}</span></td>
          <td>${t.layers}x Kademe</td>
          <td>$${Number(t.entry).toLocaleString()}</td>
          <td>$${Number(t.exit_price).toLocaleString()}</td>
          <td class="${t.pnl_pct >= 0 ? 'pos' : 'neg'}">${t.pnl_pct >= 0 ? '+' : ''}${Number(t.pnl_pct).toFixed(2)}%</td>
          <td class="${t.roe_pct >= 0 ? 'pos' : 'neg'}">${t.roe_pct >= 0 ? '+' : ''}${Number(t.roe_pct).toFixed(1)}%</td>
          <td class="${t.pnl_usdt >= 0 ? 'pos' : 'neg'}">${t.pnl_usdt >= 0 ? '+$' : '-$'}${Math.abs(Number(t.pnl_usdt)).toFixed(2)}</td>
          <td>${t.reason}</td>
        </tr>
      `).join('');
    }

    drawEquity(d.equity_curve);
  } catch (e) {
    console.error(e);
  }
}

refreshState();
setInterval(refreshState, 1500);
</script>
</body>
</html>
"""


def create_dashboard_app(hub: LiveBotHub | None = None) -> web.Application:
    hub = hub or LiveBotHub()

    @web.middleware
    async def cors_and_frame_middleware(request: web.Request, handler):
        if request.method == "OPTIONS":
            resp = web.Response(status=200)
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    app = web.Application(middlewares=[cors_and_frame_middleware])
    app["hub"] = hub

    async def index_handler(request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def state_handler(request: web.Request) -> web.Response:
        return web.json_response(hub.build_state_payload())

    async def health_handler(request: web.Request) -> web.Response:
        hub._sync_health_meta()
        code, payload = build_health_payload(hub.store)
        return web.json_response(payload, status=code)

    async def metrics_handler(request: web.Request) -> web.Response:
        hub._sync_health_meta()
        body = build_prometheus_metrics(hub.store)
        return web.Response(
            text=body,
            content_type="text/plain; version=0.0.4",
            charset="utf-8",
        )

    async def action_handler(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = str(body.get("action", ""))
        payload = body.get("payload") or {}
        res = await hub.handle_action(action, payload)
        return web.json_response(res)

    async def _bg_ticker(app_obj: web.Application):
        try:
            while True:
                await asyncio.sleep(1.5)
                await hub.step_tick()
        except asyncio.CancelledError:
            pass

    async def on_startup(app_obj: web.Application):
        app_obj["ticker_task"] = asyncio.create_task(_bg_ticker(app_obj))

    async def on_cleanup(app_obj: web.Application):
        task = app_obj.get("ticker_task")
        if task:
            task.cancel()

    app.router.add_get("/", index_handler)
    app.router.add_get("/api/state", state_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/healthz", health_handler)
    app.router.add_get("/api/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_post("/api/action", action_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    port = int(os.getenv("PORT", "8501"))
    app = create_dashboard_app()
    print(
        f"🌐 Gerçek Zamanlı Web Paneli + /health & /metrics çalışıyor → http://0.0.0.0:{port}",
        flush=True,
    )
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
