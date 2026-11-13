"""KRIPTO-BOT ana programı — hızlı ve zırhlı asenkron işlem döngüsü (v5).

  • A) Multi-Exchange Failover (Borsa Kesinti Sigortası):
    - Birincil borsada (Binance) ardı ardına 3 timeout/ağ hatası gelirse işlem ağırlığı
      ve yeni pozisyonlar kesintisiz olarak yedek borsaya (OKX) kaydırılır.
  • B) SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı (Garbage Collector):
    - `bot_state.db` otomatik WAL modunda çalışır; her 24 saatte bir eski kayıtları
      `.jsonl.gz` arşivine sıkıştırır ve `VACUUM` ile veritabanı şişmesini önler.
  • C) Gerçek Zamanlı Metrikler (Prometheus `/metrics` & `/health` Endpoint):
    - Bulut sunucularda dış izleme araçlarının her saniye botun hayatta ve sağlıklı
      olduğunu kontrol etmesi için hafif HTTP `/health` ve `/metrics` sunar.
  • Güvenlik Zırhlaması + Dinamik Kaldıraç (20x → 10x → 5x) + %0.30 Kayma Filtresi & Chase Order
  • İki Yönlü Telegram Botu (`/durum`, `/kill`, `/durdur`, `/baslat`, `/sigorta`)
  • WebSocket Keep-Alive (Ping/Pong) + Kopma Anında SQLite Durum Kurtarma

Çalıştırma:
    python -m src.main            (paper mod = sanal para, güvenli)
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pandas as pd

from .arbitrage import ArbitrageEngine
from .circuit_breaker import CircuitBreaker
from .config import BASE_DIR, load_config
from .exchanges import ExchangeManager
from .executor import Executor
from .health import HealthCheckServer
from .indicators import Indicators, indicator_score, multi_timeframe_filter
from .market_data import MarketData
from .ml_predictor import MLPredictor
from .moneyflow import MoneyFlow
from .news import NewsEngine
from .risk import RiskManager
from .security import mask_secrets, safe_exception_msg
from .sizing import PositionSizer
from .state_store import StateStore
from .strategy import Strategy
from .telegram import InteractiveTelegramBot, make_alerter


def ohlcv_to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df.astype(float)


def load_optimized_params(cfg: dict) -> dict | None:
    opt = cfg.get("optimizasyon", {})
    if not opt.get("otomatik_params"):
        return None
    p = Path(opt.get("params_dosyasi", "params_best.json"))
    if not p.is_absolute():
        p = BASE_DIR / p
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(
            f"⚠️ optimize params okunamadı ({safe_exception_msg(e)}), varsayılan kullanılıyor."
        )
    return None


async def main():
    cfg = load_config()
    g, r, sn = cfg["genel"], cfg["risk"], cfg["sinyal"]
    pf, nw, hz = cfg["para_akisi"], cfg["haberler"], cfg["hiz"]
    bz, em = cfg.get("boyutlandirma", {}), cfg.get("emirler", {})
    sg = cfg.get("sigorta", {})
    ml_cfg = cfg.get("makine_ogrenmesi", {})
    arb_cfg = cfg.get("arbitraj", {})
    db_cfg = cfg.get("veritabani", {})
    hc_cfg = cfg.get("health_check", {})
    api = cfg["api"]
    symbols: list[str] = g["semboller"]
    exchanges: list[str] = g["borsalar"]
    mode = g["mod"]
    leverage = int(g.get("kaldıraç", bz.get("kaldirac", 20)) or 20)
    capital_pct = float(r.get("kasa_giris_yuzde", bz.get("kasa_yuzde", 10.0)))

    op = load_optimized_params(cfg)
    if op:
        sn = {
            **sn,
            "agirlik_indikator": op.get("w_ind", sn["agirlik_indikator"]),
            "agirlik_para_akisi": op.get("w_flow", sn["agirlik_para_akisi"]),
            "agirlik_haber": op.get("w_news", sn["agirlik_haber"]),
            "long_esik": op.get("long_th", sn["long_esik"]),
            "short_esik": op.get("short_th", sn["short_esik"]),
            "cikis_esik": op.get("exit_th", sn["cikis_esik"]),
        }
        print(f"🧠 Walk-forward parametreleri yüklendi: {op.get('meta', {})}")

    print("=" * 74)
    print(f"🤖 KRIPTO-BOT v5 başlatılıyor | MOD: {mode.upper()} | {', '.join(symbols)}")
    print(
        f"   Borsalar: {', '.join(exchanges)} (Multi-Exchange Failover AÇIK) | "
        f"Kasa Giriş: %{capital_pct:g} × Dinamik {leverage}x/10x/5x | "
        f"Stop: %{r['stop_loss_yuzde']} | Max Kayma: %{r.get('max_kayma_yuzde', 0.30)}"
    )
    print(
        f"   Altyapı: SQLite WAL + 24s VACUUM GC AÇIK | /health & /metrics AÇIK | "
        f"Sır Maskeleme + .env İzolasyonu + İki Yönlü Telegram AÇIK"
    )
    print("=" * 74, flush=True)
    if mode == "live":
        print("⚠️  CANLI MOD: GERÇEK PARA ile işlem yapılacak! (devam etmek için 5 sn)")
        await asyncio.sleep(5)

    state_store = StateStore(
        BASE_DIR / db_cfg.get("dosya", "bot_state.db"),
        maintenance_interval_sec=float(db_cfg.get("cop_toplayici_saniye", 86400.0)),
    )
    circuit_breaker = CircuitBreaker(
        max_consecutive_errors=int(sg.get("max_ardisik_emir_hatasi", 3)),
        daily_max_loss_pct=float(
            sg.get("gunluk_max_zarar_yuzde", r.get("gunluk_max_zarar_yuzde", 5.0))
        ),
        max_ws_disconnect_sec=float(sg.get("ws_kopma_saniye", 10.0)),
        flash_crash_pct=float(sg.get("flash_crash_yuzde", 8.0)),
        max_consecutive_auth_errors=int(sg.get("max_ardisik_yetki_hatasi", 3)),
        state_store=state_store,
    )

    broker = ExchangeManager(cfg)
    risk = RiskManager(
        stop_loss_pct=r["stop_loss_yuzde"],
        lock_trigger_pct=r["kar_kilit_tetikleyici"],
        lock_level_pct=r["kar_kilit_seviyesi"],
        trail_pct=r["trailing_yuzde"],
        risk_per_trade_pct=r["islem_basina_risk_yuzde"],
        max_positions=r["max_pozisyon"],
        daily_max_loss_pct=r["gunluk_max_zarar_yuzde"],
        capital_pct_per_entry=capital_pct,
        leverage=leverage,
        unlimited_pyramiding=bool(r.get("sinirsiz_ekleme", True)),
        pyramid_min_profit_pct=float(r.get("ekleme_min_kar_yuzde", 0.25)),
        pair_rescue_enabled=bool(r.get("capraz_kurtarma", True)),
        rescue_min_loser_pct=float(r.get("kurtarma_min_zarar_yuzde", 0.5)),
        max_slippage_pct=float(r.get("max_kayma_yuzde", 0.30)),
        dynamic_leverage_enabled=bool(r.get("dinamik_kaldirac", True)),
        atr_high_volatility_pct=float(r.get("atr_yuksek_oynaklik_yuzde", 1.5)),
        atr_extreme_volatility_pct=float(r.get("atr_asiri_oynaklik_yuzde", 3.0)),
    )
    use_ml = bool(ml_cfg.get("aktif", True))
    strategy = Strategy(
        sn["agirlik_indikator"],
        sn["agirlik_para_akisi"],
        sn["agirlik_haber"],
        sn["long_esik"],
        sn["short_esik"],
        sn["cikis_esik"],
        g.get("short_izni", True),
        w_ml=float(sn.get("agirlik_ml", 0.15)) if use_ml else 0.0,
    )

    size_mode = bz.get("mod", "kasa_10_20x")
    sizer = PositionSizer(
        base_risk_pct=r["islem_basina_risk_yuzde"],
        atr_mult=bz.get("atr_katsayi", 1.5),
        kelly_on=size_mode in ("kelly", "atr_kelly"),
        kelly_fraction=bz.get("kelly_kesir", 0.5),
        kelly_min_risk=bz.get("kelly_min_risk", 0.25),
        kelly_max_risk=bz.get("kelly_max_risk", 2.0),
        kelly_min_trades=bz.get("kelly_min_islem", 20),
        stats_path=BASE_DIR / "kelly_stats.json",
        mode=size_mode,
        capital_pct=capital_pct,
        leverage=leverage,
    )

    mtf_cfg = cfg.get("mtf_filtre", {})
    alert = make_alerter(
        api["telegram_token"],
        api["telegram_chat"],
        discord_webhook=api.get("discord_webhook", ""),
        pagerduty_routing_key=api.get("pagerduty_routing_key", ""),
    )
    executor = Executor(
        broker,
        risk,
        strategy,
        sizer,
        alert,
        r["mola_saniye"],
        em.get("giris_tipi", "maker"),
        em.get("maker_zaman_asimi_sn", 3),
        em.get("borsa_korumasi", True),
        state_store=state_store,
        circuit_breaker=circuit_breaker,
    )
    tg_bot = InteractiveTelegramBot(
        token=api["telegram_token"],
        allowed_chat_id=api["telegram_chat"],
        executor=executor,
        circuit_breaker=circuit_breaker,
        broker=broker,
    )

    # C) Bağımsız Gerçek Zamanlı /health & /metrics Sunucusu
    health_server: HealthCheckServer | None = None
    if hc_cfg.get("aktif", True):
        health_server = HealthCheckServer(
            state_store,
            host=str(hc_cfg.get("host", "0.0.0.0")),
            port=int(hc_cfg.get("port", 8502)),
        )
        try:
            await health_server.start()
            print(
                f"🩺 Sağlık & Prometheus sunucusu aktif: "
                f"http://{hc_cfg.get('host', '0.0.0.0')}:{hc_cfg.get('port', 8502)}/health & /metrics",
                flush=True,
            )
        except Exception:
            health_server = None

    flows = {
        s: MoneyFlow(
            s,
            pf["balina_esik_usdt"],
            pf["pencere_saniye"],
            pf["hacim_patlama_katsayi"],
            pf.get("likidasyon_squeeze_usdt", 50_000),
            book_depth_levels=int(pf.get("emir_defteri_kademe", 20)),
        )
        for s in symbols
    }
    ml_models = {
        s: MLPredictor(
            horizon=int(ml_cfg.get("ufuk_mum", 3)),
            min_train_bars=int(ml_cfg.get("min_egitim_mumu", 80)),
            retrain_every=int(ml_cfg.get("yeniden_egitim_araligi", 15)),
        )
        for s in symbols
    }
    arb = ArbitrageEngine(
        min_net_spread_pct=float(arb_cfg.get("min_net_kar_yuzde", 0.08)),
        fee_per_leg_pct=float(em.get("komisyon_taker_yuzde", 0.05)),
        trade_notional_usdt=float(arb_cfg.get("islem_tutari_usdt", 1000.0)),
        cooldown_sec=float(arb_cfg.get("mola_saniye", 10.0)),
        enabled=bool(arb_cfg.get("aktif", True)),
        state_store=state_store,
    )
    news = NewsEngine(
        nw["kaynaklar"],
        nw["kontrol_saniye"],
        api["cryptopanic_key"],
        fear_greed_on=nw.get("korku_acgozluluk", True),
        fear_veto_low=nw.get("korku_veto_alt", 15),
        greed_long_veto_high=nw.get("acgozluluk_long_veto_ust", 85),
        llm_url=api.get("llm_url", ""),
        llm_key=api.get("llm_key", ""),
        llm_model=api.get("llm_model", ""),
    )

    last_ind: dict[str, float] = {s: 0.0 for s in symbols}
    last_ml: dict[str, dict] = {
        s: {"score": 0.0, "prob_up": 0.5, "direction": "NOTR", "backend": "numpy_gbdt"}
        for s in symbols
    }
    live_scores: dict[str, dict] = {}
    tick_count = {"n": 0}
    t_start = time.time()

    async def evaluate(s: str, price: float):
        ind = last_ind.get(s, 0.0)
        flow_snap = flows[s].snapshot()
        flow = flow_snap["score"]
        mood = news.mood()
        fg = mood.get("fear_greed", 50.0)
        veto_app = bool(mood.get("veto_approaching"))
        executor.set_market_mood(fear_greed=fg, veto_approaching=veto_app)
        dyn_lev, lev_why = executor.get_dynamic_leverage(s, price)

        fg_tilt = fg - 50.0
        news_blended = round(mood["score"] * 0.7 + fg_tilt * 0.6, 1)
        ml_info = last_ml.get(s, {})
        ml_sc = ml_info.get("score", 0.0) if use_ml else None
        combined = strategy.combine(ind, flow, news_blended, ml_sc)
        mtf_info = executor.get_mtf_trend(s) or {
            "trend": "NEUTRAL",
            "score": 0.0,
            "allow_long": True,
            "allow_short": True,
        }

        live_scores[s] = {
            "symbol": s,
            "price": round(price, 4),
            "total": combined["total"],
            "signal": combined["signal"],
            "indikator": round(ind, 1),
            "para_akisi": round(flow, 1),
            "haber": news_blended,
            "ml_skor": round(ml_sc or 0.0, 1),
            "ml_prob_up": ml_info.get("prob_up", 0.5),
            "ml_backend": ml_info.get("backend", "numpy_gbdt"),
            "fear_greed": fg,
            "dynamic_leverage": dyn_lev,
            "leverage_reason": lev_why,
            "active_exchange": broker.primary,
            "mtf_trend": mtf_info.get("trend", "NEUTRAL")
            if isinstance(mtf_info, dict)
            else str(mtf_info),
            "mtf_score": mtf_info.get("score", 0.0)
            if isinstance(mtf_info, dict)
            else 0.0,
            "bid_ask_ratio": flow_snap.get("bid_ask_ratio", 1.0),
            "wall_signal": flow_snap.get("wall_signal", "DENGELI"),
            "bid_depth_usdt": flow_snap.get("bid_depth_usdt", 0.0),
            "ask_depth_usdt": flow_snap.get("ask_depth_usdt", 0.0),
            "squeeze": flow_snap.get("squeeze", "YOK"),
            "oi": flow_snap.get("open_interest", 0.0),
            "oi_change_pct": flow_snap.get("oi_change_pct", 0.0),
            "short_liq_usdt": flow_snap.get("short_liq_usdt", 0.0),
            "long_liq_usdt": flow_snap.get("long_liq_usdt", 0.0),
            "veto": bool(mood["veto"]),
        }
        state_store.set_meta("live_scores", live_scores)

        await executor.on_signal(
            s,
            price,
            combined,
            flow,
            bool(mood["veto"]) and nw.get("veto_guc", True),
            bool(mood.get("veto_long")),
            bool(mood.get("veto_short")),
            mtf_trend=mtf_info,
        )

    async def on_trade(
        exchange: str, symbol: str, price: float, qty: float, buyer_maker: bool
    ):
        tick_count["n"] += 1
        whale = flows[symbol].add_trade(price, qty, buyer_maker)
        await executor.on_price_tick(symbol, price)
        if whale is not None:
            await alert(
                f"🐋 BALİNA {whale.side} {symbol}: "
                f"${whale.notional_usdt:,.0f} @ {price:,.4f}"
            )
            await evaluate(symbol, price)

    async def on_price(exchange: str, symbol: str, price: float):
        arb.update_quote(exchange, symbol, price, price)
        await executor.on_price_tick(symbol, price)
        opp = arb.check_opportunity(symbol)
        if opp:
            await arb.execute_arbitrage(opp, broker, alert)

    async def on_book(exchange: str, symbol: str, bids, asks):
        flows[symbol].update_book(bids, asks)
        if bids and asks:
            arb.update_quote(exchange, symbol, float(bids[0][0]), float(asks[0][0]))
            opp = arb.check_opportunity(symbol)
            if opp:
                await arb.execute_arbitrage(opp, broker, alert)

    async def on_liquidation(
        exchange: str, symbol: str, side: str, price: float, qty: float
    ):
        ev = flows[symbol].add_liquidation(side, price, qty)
        snap = flows[symbol].snapshot()
        if snap.get("squeeze") in ("SHORT_SQUEEZE", "LONG_SQUEEZE"):
            await alert(
                f"💥 {snap['squeeze']} ALGILANDI | {symbol} | "
                f"Tasfiye: ${ev.notional_usdt:,.0f} @ {price:,.4f}"
            )
            await evaluate(symbol, price)

    market = MarketData(
        symbols,
        exchanges,
        on_trade,
        on_price,
        on_book,
        hz["reconnect_saniye"],
        on_liquidation=on_liquidation,
        on_ws_heartbeat=circuit_breaker.heartbeat_ws,
        state_store=state_store,
        executor=executor,
        ping_interval_sec=float(hz.get("ws_ping_saniye", 15.0)),
    )

    async def refresh_loop():
        await asyncio.sleep(3)
        while True:
            try:
                for s in symbols:
                    try:
                        rows = await broker.fetch_ohlcv(s, g["zaman_dilimi"], 300)
                        df = ohlcv_to_df(rows)
                        funding = await broker.fetch_funding(s)
                        ind = indicator_score(df, funding)
                        last_ind[s] = ind["score"]
                        if use_ml:
                            last_ml[s] = ml_models[s].predict(df)

                        # Çoklu Zaman Dilimi (Multi-Timeframe 1h / 4h) Trend Filtresi
                        if mtf_cfg.get("aktif", True):
                            try:
                                rows_1h = await broker.fetch_ohlcv(s, "1h", 120)
                                rows_4h = await broker.fetch_ohlcv(s, "4h", 120)
                                mtf_res = multi_timeframe_filter(
                                    ohlcv_to_df(rows_1h),
                                    ohlcv_to_df(rows_4h),
                                    bearish_block_th=float(
                                        mtf_cfg.get("dusus_engelleme_esigi", -15.0)
                                    ),
                                    bullish_block_th=float(
                                        mtf_cfg.get("yukselis_engelleme_esigi", 15.0)
                                    ),
                                )
                                executor.set_mtf_trend(s, mtf_res)
                            except Exception:
                                pass

                        atr_s = Indicators.atr(
                            df["high"],
                            df["low"],
                            df["close"],
                            bz.get("atr_periyot", 14),
                        )
                        try:
                            executor.set_atr(s, float(atr_s.iloc[-1]))
                        except Exception:
                            pass
                        price = market.get_price(s) or float(df["close"].iloc[-1])
                        oi = await broker.fetch_open_interest(s)
                        if oi:
                            flows[s].update_open_interest(oi, price)
                        await evaluate(s, price)
                    except Exception as e:
                        err_msg = safe_exception_msg(e)
                        print(f"⚠️ {s} yenileme hatası: {err_msg}", flush=True)
                        if circuit_breaker.record_order_error(e):
                            await alert(
                                f"🚨 SİGORTA ATTI: {circuit_breaker.trip_reason}"
                            )
                            await executor.close_all_positions(
                                circuit_breaker.trip_reason
                            )

                bal = await broker.fetch_balance_usdt()
                unreal = executor.total_unrealized_usdt()
                state_store.record_equity(bal, bal + unreal, len(executor.positions))
                state_store.set_meta("arb_quotes", arb.scan_all(symbols))
                st = state_store.get_meta("bot_status", {}) or {}
                st["exchange_health"] = broker.exchange_health_snapshot()
                st["sqlite_wal"] = state_store.get_wal_status()
                state_store.set_meta("bot_status", st)
            except Exception as e:
                print(
                    f"⚠️ yenileme döngüsü hatası: {safe_exception_msg(e)}",
                    flush=True,
                )
            await asyncio.sleep(hz["mum_yenileme_saniye"])

    async def command_and_watchdog_loop():
        while True:
            await asyncio.sleep(1.0)
            try:
                if circuit_breaker.check_ws_health():
                    await alert(f"🚨 SİGORTA ATTI: {circuit_breaker.trip_reason}")
                    await executor.close_all_positions("WS >10 SN KOPMA SİGORTASI")

                cmds = state_store.pop_commands()
                for c in cmds:
                    name = c["cmd"]
                    pl = c.get("payload", {})
                    if name == "KILL_SWITCH":
                        circuit_breaker.trip("WEB PANELİ ACİL KILL-SWITCH")
                        await executor.close_all_positions(
                            "WEB PANELİ ACİL KILL-SWITCH"
                        )
                    elif name == "PAUSE":
                        circuit_breaker.set_paused(True)
                    elif name == "RESUME":
                        circuit_breaker.set_paused(False)
                    elif name == "RESET_BREAKER":
                        circuit_breaker.reset()
                    elif name == "RUN_GC":
                        state_store.run_garbage_collector()
                    elif name == "CLOSE_SYMBOL":
                        sym = pl.get("symbol")
                        if sym and sym in executor.positions:
                            pos = executor.positions[sym]
                            px = executor.last_prices.get(sym, pos.entry)
                            pnl = risk.profit_pct(pos, px)
                            await executor._close(
                                sym, px, "WEB PANELİ MANUEL KAPAMA", pnl
                            )
            except Exception:
                pass

    async def heartbeat():
        while True:
            await asyncio.sleep(60)
            up = int(time.time() - t_start)
            mood = news.mood()
            risk_pct, kinfo = sizer.risk_pct()
            parts = []
            for s in symbols:
                p = market.get_price(s)
                parts.append(f"{s}={p:,.2f}" if p else f"{s}=?")
            print(
                mask_secrets(
                    f"💓 {up // 60}dk | tick={tick_count['n']} | borsa={broker.primary.upper()} | "
                    f"gecikme={market.avg_latency_ms():.0f}ms | "
                    f"haber={mood['score']:+.0f} FG={mood.get('fear_greed', 50):.0f} | "
                    f"mod=%{risk_pct:g}({kinfo.get('kaynak')}) | "
                    f"sigorta={circuit_breaker.snapshot()['status']} | "
                    f"açık={list(executor.positions)} | {' '.join(parts)} | "
                    f"istatistik={executor.stats}"
                ),
                flush=True,
            )

    tasks = [
        asyncio.create_task(market.run_forever()),
        asyncio.create_task(news.run_forever()),
        asyncio.create_task(refresh_loop()),
        asyncio.create_task(command_and_watchdog_loop()),
        asyncio.create_task(tg_bot.poll_forever()),
        asyncio.create_task(state_store.maintenance_loop()),
        asyncio.create_task(heartbeat()),
    ]
    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n🛑 Bot durduruluyor...")
    finally:
        market.stop()
        news.stop()
        tg_bot.stop()
        if health_server:
            await health_server.stop()
        for t in tasks:
            t.cancel()
        await broker.close()
        print(f"📊 Son istatistik: {executor.stats}")
        print(
            f"💰 Kasa (paper): ${broker.paper.balance:,.2f}"
            if mode == "paper"
            else ""
        )


if __name__ == "__main__":
    asyncio.run(main())
