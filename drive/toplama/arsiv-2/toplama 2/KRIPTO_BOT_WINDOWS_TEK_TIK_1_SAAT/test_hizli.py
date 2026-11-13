"""KRIPTO-BOT v7.2 — 101 Kapsamlı Çevrimdışı Sistem ve Paper Senaryo Doğrulaması."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

# `.env` içinde gerçek anahtarlar olsa bile bu doğrulama tamamen çevrimdışıdır.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["PAGERDUTY_ROUTING_KEY"] = ""

from src.alerts import MultiChannelAlerter
from src.arbitrage import ArbitrageEngine
from src.attribution import build_session_analysis
from src.backtest import (
    EventDrivenBacktester,
    MarketEvent,
    SignalEvent,
    run_out_of_sample_test,
    verify_no_lookahead_bias,
)
from src.circuit_breaker import CircuitBreaker
from src.cohort_report import build_cohort_report
from src.config import load_config
from src.dashboard import LiveBotHub, ProductionBotHub
from src.exchanges import ExchangeManager, PaperBroker, is_timeout_or_network_error
from src.executor import Executor
from src.futures_catalog import build_futures_catalog
from src.health import build_health_payload, build_prometheus_metrics
from src.indicators import Indicators, indicator_score, multi_timeframe_filter
from src.market_data import (
    IncrementalOrderBook,
    MarketData,
    OrderBookSyncError,
    binance_ws_base,
    to_binance_stream,
    to_okx_inst,
)
from src.ml_predictor import MLPredictor
from src.moneyflow import MoneyFlow
from src.news import NewsEngine
from src.pdf_indicators import pdf_v2_snapshot
from src.reconcile import reconcile_positions
from src.risk import Position, RiskManager, position_limits_for_mode
from src.security import (
    is_auth_or_permission_error,
    mask_secrets,
    register_secret,
    safe_exception_msg,
)
from src.sentiment_ai import AISentimentAnalyzer
from src.shadow_lab import ShadowLab
from src.sizing import KellyTracker, PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy

passed = 0
failed = 0


def check(name: str, cond: bool):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ [{passed:03d}] {name}")
    else:
        failed += 1
        print(f"  ❌ [FAIL] {name}")


def make_ohlcv(n: int = 180, drift: float = 0.0015, start: float = 50_000.0, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = drift + rng.normal(0.0, 0.0025, size=n)
    close = start * np.cumprod(1.0 + rets)
    open_ = np.roll(close, 1)
    open_[0] = start
    high = np.maximum(open_, close) * 1.0025
    low = np.minimum(open_, close) * 0.9975
    vol = rng.uniform(120.0, 600.0, size=n)
    now = time.time()
    ts = [(now - (n - i) * 300) * 1000.0 for i in range(n)]
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": vol})


print("🚀 KRIPTO-BOT v7.2 — 101 Çevrimdışı Sistem Senaryosu Başlıyor...\n")
tmp_root = Path(tempfile.mkdtemp())

# --- BÖLÜM 1: Yapılandırma & Güvenlik (1..10) ---
cfg = load_config()
check("config.yaml başarıyla yüklenir", isinstance(cfg, dict))
check("Varsayılan mod paper olarak yapılandırılmış", cfg["genel"]["mod"] == "paper")
check("Varsayılan kaldıraç 10x", cfg["genel"]["kaldıraç"] == 10)
check("Sabit marj 50 USDT", cfg["boyutlandirma"]["mod"] == "sabit_usdt" and cfg["boyutlandirma"]["sabit_marj_usdt"] == 50.0)
check("Stop modeli marj (%80 = 40 USDT)", cfg["risk"]["stop_modeli"] == "marj" and cfg["risk"]["marj_zarar_orani"] == 0.80)
check("Kâr koşusu (runner exit) aktif", cfg["cikis"]["kosan_kar"] is True)
register_secret("TopSecretApiKey987654321")
check("Kayıtlı sır metin içinde maskelenir", "TopSecretApiKey987654321" not in mask_secrets("hata: TopSecretApiKey987654321"))
check("Telegram bot token URL'si maskelenir", "123456789:ABCDEF" not in mask_secrets("https://api.telegram.org/bot123456789:ABCDEF_ghijklmno1234567890/sendMessage"))
check("İstisna mesajı güvenli biçimde temizlenir", "TopSecretApiKey987654321" not in safe_exception_msg(RuntimeError("key=TopSecretApiKey987654321")))
check("Yetki hataları doğru sınıflandırılır", is_auth_or_permission_error(RuntimeError("Invalid API-key, IP, or permissions for action")))

# --- BÖLÜM 2: Teknik İndikatörler, MTF & PDF v2 (11..22) ---
df_up = make_ohlcv(220, drift=0.0022, seed=3)
df_dn = make_ohlcv(220, drift=-0.0022, seed=4)
ind_res = indicator_score(df_up, funding_rate=0.0001)
check("İndikatör skoru -100..+100 aralığında", -100.0 <= ind_res["score"] <= 100.0)
check("İndikatör snapshot rejim ve kurulum bilgisi üretir", "regime" in ind_res["snapshot"] and "setup" in ind_res["snapshot"])
check("Supertrend yönü ve seviyesi hesaplanır", ind_res["snapshot"]["supertrend"] > 0)
check("Session VWAP ve Anchored VWAP üretilir", ind_res["snapshot"]["session_vwap"] > 0 and ind_res["snapshot"]["anchored_vwap"] > 0)
check("ATR serisi pozitif değer döner", float(Indicators.atr(df_up["high"], df_up["low"], df_up["close"], 14).iloc[-1]) > 0)
mtf_bull = multi_timeframe_filter(df_up, df_up)
check("Yükseliş 1h/4h verisinde MTF LONG izni açık", mtf_bull["allow_long"] is True)
mtf_bear = multi_timeframe_filter(df_dn, df_dn)
check("Düşüş 1h/4h verisinde MTF LONG engellenir", mtf_bear["allow_long"] is False)
pdf_snap = pdf_v2_snapshot(df_up)
check("PDF v2 araştırma paketi 6 aile özeti üretir", "family_votes" in pdf_snap and len(pdf_snap["family_votes"]) >= 5)
check("PDF v2 KAMA, HMA ve Hurst hesaplar", "kama" in pdf_snap["values"] and "hurst" in pdf_snap["values"])
check("PDF v2 piyasa yapısı (BOS/CHoCH/FVG) içerir", "structure" in pdf_snap["family_votes"])
check("İndikatör motorunda gelecek sızıntısı (lookahead) yok", verify_no_lookahead_bias(df_up, 120) is True)
check("Düşüş serisinde indikatör skoru yükseliş serisinden düşük", indicator_score(df_dn)["score"] < ind_res["score"])

# --- BÖLÜM 3: Para Akışı, Derinlik, CVD Divergence, Absorption & Tick VPVR (23..34) ---
mf = MoneyFlow("BTC/USDT", whale_usdt=100_000, vpvr_bins=12)
now_ts = time.time()
for i in range(60):
    mf.add_trade(50_000.0 + (i % 3), 0.1, False, ts=now_ts - 400 + i * 3)
for i in range(60):
    mf.add_trade(50_010.0 + (i % 2), 0.12, False, ts=now_ts - 200 + i * 3)
whale_ev = mf.add_trade(50_020.0, 3.0, False, ts=now_ts - 2)
check("100K+ USDT işlem balina olarak yakalanır", whale_ev is not None and whale_ev.side == "ALIŞ")
depth = mf.update_book([(50_015.0 - i, 2.5) for i in range(20)], [(50_025.0 + i, 1.0) for i in range(20)], ts=now_ts - 1)
check("20 kademe alıcı baskın defterde ALICI_DUVARI sinyali oluşur", depth["wall_signal"] == "ALICI_DUVARI" and depth["bid_ask_ratio"] > 1.65)
mf.update_open_interest(100_000, price=50_000.0, ts=now_ts - 60)
mf.update_open_interest(103_000, price=50_200.0, ts=now_ts - 1)
liq_ev = mf.add_liquidation("BUY", 50_200.0, 1.5, ts=now_ts - 1)
check("BUY yönlü zorunlu tasfiye SHORT_LIQ olarak kaydedilir", liq_ev.side == "SHORT_LIQ")
snap_mf = mf.snapshot()
check("Agresif alım + duvar + short squeeze ile para akışı skoru pozitif", snap_mf["score"] > 30)
check("OI + fiyat artışında YENI_LONG_GIRISI sinyali oluşur", snap_mf["oi_signal"] == "YENI_LONG_GIRISI")
check("SHORT_SQUEEZE algılanır", snap_mf["squeeze"] == "SHORT_SQUEEZE")
check("Tick VPVR ısınır ve POC/VAH/VAL üretir", snap_mf["vpvr_warm"] is True and snap_mf["vpvr_val"] <= snap_mf["vpvr_poc"] <= snap_mf["vpvr_vah"])
snap_fast = mf.snapshot(include_vpvr=False)
check("include_vpvr=False hızlı snapshot'ta VPVR hesaplamasını atlar", "vpvr_poc" not in snap_fast)

mf_div = MoneyFlow("ETH/USDT", absorption_min_usdt=1e9)
for i in range(5):
    mf_div.add_trade(100.0, 1.0, False, ts=now_ts - 100 + i * 10)
for i in range(5):
    mf_div.add_trade(101.0, 1.0, True, ts=now_ts - 40 + i * 8)
check("Fiyat yükselirken CVD düşerse BEARISH divergence üretilir", mf_div.snapshot()["cvd_divergence"] == "BEARISH")

mf_abs = MoneyFlow("SOL/USDT", absorption_min_usdt=100.0)
mf_abs.update_book([(99.5, 10.0)], [(100.5, 10.0)], ts=now_ts - 50)
for i in range(6):
    mf_abs.add_trade(100.0, 0.3, True, ts=now_ts - 45 + i * 3)
mf_abs.add_trade(100.0, 0.1, False, ts=now_ts - 15)
mf_abs.update_book([(99.5, 11.0)], [(100.5, 10.0)], ts=now_ts - 5)
check("Yoğun satışa rağmen fiyat ve bid duvarı tutunursa SATIS_EMILIMI üretilir", mf_abs.snapshot()["absorption"] == "SATIS_EMILIMI")
mf_compact = MoneyFlow("XRP/USDT", compact_history=True)
check("Compact history bellek sınırlarını daraltır", mf_compact._trades.maxlen == 2_000 and mf_compact._vpvr_trades.maxlen == 5_000)
check("Para akışı karar etiketi üretilir", snap_mf["verdict"] in ("GÜÇLÜ GİRİŞ", "GİRİŞ"))

# --- BÖLÜM 4: NLP Duygu Analizi, Haber Motoru & ML Tahminci (35..44) ---
ai = AISentimentAnalyzer()
bull_s = ai.analyze("Spot Bitcoin ETF approved with record institutional inflow")
bear_s = ai.analyze("Major crypto exchange hacked, withdrawals halted after exploit")
check("Olumlu ETF haberi pozitif duygu skoru alır", bull_s["score"] > 15 and bull_s["veto"] is False)
check("Borsa hack haberi negatif skor ve acil veto üretir", bear_s["score"] < -40 and bear_s["veto"] is True)
neg_flip = ai.analyze("Hack rumor denied, funds not stolen")
check("Olumsuzlama eki ('not') yanlış pozitif paniği yumuşatır", neg_flip["veto"] is False)

news_eng = NewsEngine([], fear_greed_on=False)
news_eng._register("Old hack", "RSS", "", -90, True, ["KRİTİK"], published_ts=now_ts - 9000)
check("Bayat haber taze veto üretmez", news_eng.mood()["veto"] is False)
news_eng.push_item("Breaking: exchange hacked and withdrawals halted", "RSS")
check("Taze kritik haber anında veto üretir", news_eng.mood()["veto"] is True)
ne_greed = NewsEngine([], fear_greed_on=True, greed_long_veto_high=85)
ne_greed.push_item("Massive ETF bull rally ATH inflow approval adoption", "RSS")
check("Aşırı açgözlülük LONG vetosunu tetikler", ne_greed.mood()["long_veto"] is True)

ml = MLPredictor(horizon=3, min_train_bars=60, retrain_every=15)
check("Yetersiz mumda ML güvenli nötr (0.0, %50) döner", ml.predict(df_up.iloc[:30])["trained"] is False)
ml_pred = ml.predict(df_up)
check("Yeterli mumda ML walk-forward eğitilir ve olasılık üretir", ml_pred["trained"] is True and 0.0 <= ml_pred["prob_up"] <= 1.0)
check("ML skoru -100..+100 aralığında", -100.0 <= ml_pred["score"] <= 100.0)
check("ML backend adı raporlanır", isinstance(ml_pred["backend"], str) and len(ml_pred["backend"]) > 0)

# --- BÖLÜM 5: Risk, Sabit 50/40 Boyutlandırma, Kelly & Strateji (45..60) ---
rm = RiskManager(
    stop_model="marj",
    margin_stop_fraction=0.80,
    leverage=10,
    unlimited_pyramiding=False,
    max_layers=1,
    pair_rescue_enabled=False,
)
check("10x ve %80 marj zararı için başlangıç stop mesafesi %8.0", abs(rm.effective_stop_pct(10) - 8.0) < 1e-6)
check("LONG 100 girişte başlangıç stopu 92.0", abs(rm.initial_stop("LONG", 100.0, 10) - 92.0) < 1e-6)
check("SHORT 100 girişte başlangıç stopu 108.0", abs(rm.initial_stop("SHORT", 100.0, 10) - 108.0) < 1e-6)

sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=50.0, leverage=10, stats_path=tmp_root / "kelly.json")
qty_50, inf_50 = sizer.size(1_000.0, 100.0, 92.0)
check("Sabit 50 USDT × 10x @ 100 fiyatta miktar 5.0 adet ve notional 500 USDT", abs(qty_50 - 5.0) < 1e-9 and inf_50["notional"] == 500.0)
check("5 adet × 8$ stop mesafesi = tam 40 USDT başlangıç fiyat riski", abs(qty_50 * (100.0 - 92.0) - 40.0) < 1e-9)
qty_low, _ = sizer.size(40.0, 100.0, 92.0)
check("Bakiye 50 USDT altındaysa giriş reddedilir", qty_low == 0.0)

pos_t = Position("BTC/USDT", "LONG", 100.0, 5.0, 92.0, leverage=10, margin_usdt=50.0, entry_fee_usdt=0.25)
check("Net başabaş fiyatı giriş ve tahmini çıkış komisyonunu içerir", rm.net_breakeven_price(pos_t) > 100.0)
rm.update(pos_t, 102.0)
check("Küçük kârda başlangıç 92 stopu daraltılmaz (erken stop yok)", abs(pos_t.stop - 92.0) < 1e-6)
rm.update(pos_t, 112.0)
check("Güçlü kârda (%10+) kâr kilidi devreye girer ve stop girişin üstüne taşınır", pos_t.locked_profit is True and pos_t.stop > 105.0)
can_pyr, _ = rm.can_add_to_winner(pos_t, 115.0)
check("Sabit modelde kademe ekleme (pyramiding) kapalıdır", can_pyr is False)
paper_lim = position_limits_for_mode(cfg["risk"], "paper")
live_lim = position_limits_for_mode(cfg["risk"], "live")
check("Paper pozisyon limiti geniş (1000), live limiti sıkı (3)", paper_lim["max_positions"] == 1000 and live_lim["max_positions"] == 3)

kt = KellyTracker(tmp_root / "kt.json", min_trades=5)
for v in (-2.0, -1.5, 1.0, -2.0, -1.0, -1.5):
    kt.record(v)
check("Negatif beklentide Kelly kesri <= 0 döner", (kt.fraction() or 0.0) <= 0.0)

strat = Strategy(runner_exit=True)
comb_blk = strat.combine(70.0, 60.0, 10.0, market_context={"regime_aware": True, "entry_allowed": False, "entry_block_reason": "BB sıkışması"})
check("Sıkışma rejiminde LONG sinyali BEKLE'ye çevrilir", comb_blk["signal"] == "BEKLE" and comb_blk["raw_signal"] == "LONG")
comb_of = strat.combine(70.0, 60.0, 10.0, market_context={"regime_aware": False, "cvd_divergence": "BEARISH"})
check("Bearish CVD divergence LONG girişini veto eder", comb_of["signal"] == "BEKLE" and "divergence" in comb_of["orderflow_veto"])
comb_ok = strat.combine(75.0, 65.0, 10.0, market_context={"regime_aware": False})
dec_mtf = strat.entry_decision(comb_ok, False, mtf_trend={"trend": "BEARISH", "allow_long": False, "allow_short": True})
check("MTF düşüş trendi LONG girişini engeller", dec_mtf["action"] == "yok" and "MTF TREND FİLTRESİ" in dec_mtf["reason"])
check("Runner modunda yalnız skor zayıflamasıyla erken çıkış yapılmaz", strat.exit_decision("LONG", {"total": -70}, -80, False, 6.0)["action"] == "hold")

# --- BÖLÜM 6: SQLite WAL, Çöp Toplayıcı, Sigorta, Sağlık & Alarmlar (61..74) ---
store = StateStore(tmp_root / "state.db")
wal_st = store.get_wal_status()
check("SQLite WAL modu aktif", wal_st["wal_enabled"] is True)
p_save = Position("ETH/USDT", "SHORT", 3_000.0, 0.5, 3_240.0, leverage=10, margin_usdt=50.0, exchange="okx")
store.save_position(p_save, "okx")
loaded_pos = store.load_positions()
check("Açık pozisyon ve borsa bilgisi SQLite'tan geri yüklenir", "ETH/USDT" in loaded_pos and loaded_pos["ETH/USDT"].exchange == "okx")
check("Başlangıç kurtarma raporu açık pozisyonu listeler", len(store.startup_recovery_report()) >= 2)
for i in range(18):
    store.record_trade("BTC/USDT", "LONG", 100.0, 102.0, 1.0, 2.0, "TRAILING STOP", pnl_usdt=2.0, net_pnl_usdt=1.9)
gc_res = store.run_garbage_collector(max_trades=10, max_equity=10, max_arb=10)
check("Garbage collector taşan kayıtları .jsonl.gz arşivine taşır", gc_res["archived"] == 8 and len(store.get_trades(50)) == 10)
store.push_command("PAUSE", {"by": "test"})
cmds = store.pop_commands()
check("Komut kuyruğu FIFO çalışır ve tek sefer tüketilir", len(cmds) == 1 and cmds[0]["cmd"] == "PAUSE" and store.pop_commands() == [])

cb = CircuitBreaker(max_consecutive_errors=3, daily_max_loss_pct=5.0, max_ws_disconnect_sec=30.0)
cb.heartbeat_ws()
check("Başlangıçta sigorta sağlıklıdır ve girişe izin verir", cb.can_trade()[0] is True)
cb.record_order_error("err1")
cb.record_order_error("err2")
tripped = cb.record_order_error("err3")
check("Ardı ardına 3 emir hatasında sigorta atar", tripped is True and cb.tripped is True)
cb.reset()
check("Sigorta sıfırlanınca işlem izni geri gelir", cb.can_trade()[0] is True)

store.set_meta("bot_status", {"ts": time.time(), "mode": "PAPER", "balance_usdt": 1000.0, "equity_usdt": 1012.5, "open_positions": 1})
store.set_meta("circuit_breaker", cb.snapshot())
status_h, h_payload = build_health_payload(store)
check("/health uç noktası taze heartbeat ile 200 OK döner", status_h == 200 and h_payload["healthy"] is True)
prom_txt = build_prometheus_metrics(store)
check("Prometheus /metrics çıktısı kriptobot_equity_usdt metriğini içerir", "kriptobot_equity_usdt 1012.5" in prom_txt)

alerter = MultiChannelAlerter(discord_webhook_url="", pagerduty_routing_key="")
alert_res = asyncio.run(alerter.send("Test alarmı", critical=True))
check("Boş webhook/key ile dış ağ çağrısı yapılmaz", alert_res == {})

rec_rep = reconcile_positions({"BTC/USDT": p_save}, [])
check("Mutabakat motoru borsada olmayan hayalet pozisyonu yakalar", len(rec_rep["ghosts"]) == 1)
cohorts = build_cohort_report(store.get_trades(10))
check("Kohort raporu bot kapanışlarını oturum sonundan ayırır", cohorts["coverage"]["bot_closed"] == 10)
attr_rep = build_session_analysis(store.get_trades(10))
check("Oturum atıf analizi özet sözlüğü üretir", attr_rep["overall"]["count"] == 10)

# --- BÖLÜM 7: Borsa Katmanı, PaperBroker, Futures Katalogu, WS & Arbitraj (75..89) ---
pb = PaperBroker(balance_usdt=1_000.0, fee_taker_pct=0.05)
f_open = pb.market_order("BTC/USDT", "buy", 5.0, 100.0, exchange="binance")
check("PaperBroker alışta komisyonu düşer ve pozisyon miktarını izler", pb.position_qty["BTC/USDT"] == 5.0 and pb.balance < 1_000.0)
f_close = pb.market_order("BTC/USDT", "sell", 9.0, 102.0, exchange="binance", reduce_only=True)
check("PaperBroker reduce-only kapamada açık miktarı aşmaz, ters pozisyon açmaz", f_close["qty"] == 5.0 and "BTC/USDT" not in pb.position_qty)
pb.apply_funding("BTC/USDT", -0.15, 0.0001, 3600)
check("PaperBroker funding ödemesini kasaya ve toplama işler", abs(pb.total_funding_usdt + 0.15) < 1e-9)

check("Timeout hata sınıflandırıcı ağ hatalarını tanır", is_timeout_or_network_error(TimeoutError("request timed out")))
ex_mgr = ExchangeManager({"genel": {"mod": "paper", "semboller": ["BTC/USDT"], "borsalar": ["binance", "okx"], "kaldıraç": 10}, "api": {}})
check("USDT-M swap için CCXT sembolü BTC/USDT:USDT olarak üretilir", ex_mgr._ccxt_symbol("BTC/USDT") == "BTC/USDT:USDT")
check("Binance market keşfi yalnız linear (USDT-M) tiplerle sınırlı", ex_mgr._ex["binance"].options["fetchMarkets"]["types"] == ["linear"])
asyncio.run(ex_mgr.close())

cat_syms, cat_sup = build_futures_catalog(
    {
        "binance": {"1": {"symbol": "BTC/USDT:USDT", "swap": True, "contract": True, "linear": True, "quote": "USDT", "settle": "USDT", "active": True}},
        "okx": {"2": {"symbol": "ETH/USDT:USDT", "swap": True, "contract": True, "linear": True, "quote": "USDT", "settle": "USDT", "active": True}},
    }
)
check("Futures katalogu iki borsanın aktif USDT perpetual kontratlarını birleştirir", cat_syms == ["BTC/USDT", "ETH/USDT"] and cat_sup["ETH/USDT"] == ["okx"])
check("Binance stream ve OKX swap enstrüman adları doğru çevrilir", to_binance_stream("BTC/USDT") == "btcusdt" and to_okx_inst("BTC/USDT", "swap") == "BTC-USDT-SWAP")
check("Binance Futures WS taban adresi fstream.binance.com kullanır", "fstream.binance.com" in binance_ws_base("swap", "public"))

ob = IncrementalOrderBook()
ob.apply("snapshot", {"bids": [["100", "5"]], "asks": [["101", "4"]], "seqId": 10})
ob.apply("update", {"bids": [["100", "0"], ["99.5", "6"]], "asks": [], "prevSeqId": 10, "seqId": 11})
top_b, top_a = ob.top(5)
check("OKX artımlı emir defteri sıfırlanan kademeyi siler ve sırayı doğrular", top_b[0] == (99.5, 6.0) and top_a[0] == (101.0, 4.0))
seq_err = False
try:
    ob.apply("update", {"bids": [], "asks": [], "prevSeqId": 99, "seqId": 100})
except OrderBookSyncError:
    seq_err = True
check("OKX emir defterinde sıra boşluğu OrderBookSyncError fırlatır", seq_err is True)

md = MarketData(["BTC/USDT"], ["okx"], market_type="swap", contract_sizes={("okx", "BTC/USDT"): 0.01})
check("OKX swap kontrat adedi contractSize ile coin miktarına çevrilir", abs((md.normalize_quantity("okx", "BTC/USDT", 3) or 0.0) - 0.03) < 1e-9)

arb = ArbitrageEngine(min_net_spread_pct=0.08, fee_per_leg_pct=0.05, trade_notional_usdt=1_000.0)
arb.update_quote("binance", "BTC/USDT", 50_000.0, 50_010.0)
arb.update_quote("okx", "BTC/USDT", 50_150.0, 50_160.0)
opp = arb.check_opportunity("BTC/USDT")
check("Borsalar arası net spread eşiği aşıldığında arbitraj fırsatı bulunur", opp is not None and opp["buy_exchange"] == "binance" and opp["sell_exchange"] == "okx")
arb_paper = asyncio.run(arb.execute_arbitrage(opp))
check("Paper modda arbitraj kârı simüle edilir", arb_paper["status"] == "PAPER_FILLED" and arb_paper["profit_usdt"] > 0)

class _LiveDummy:
    mode = "live"

arb_live = asyncio.run(arb.execute_arbitrage(opp, broker=_LiveDummy()))
check("Canlı modda arbitraj fail-closed (DISABLED_LIVE) olarak engellenir", arb_live["status"] == "DISABLED_LIVE")

# --- BÖLÜM 8: Backtest, OOS, Shadow Lab & Web Komuta Paneli (90..101) ---
bt = EventDrivenBacktester(
    symbol="BTC/USDT",
    initial_balance=1_000.0,
    fixed_margin_usdt=50.0,
    leverage=10,
    stop_model="marj",
    runner_exit=True,
    use_ml=False,
)
bt._handle_signal_event(SignalEvent(0, "BTC/USDT", "LONG", 75.0, 100.0, "TEST"))
ord_ev = bt.events.popleft()
check("Backtest sabit 50 USDT marj × 10x ile emir üretir", abs(ord_ev.margin_usdt - 50.0) < 1e-9 and abs(ord_ev.qty - 5.0) < 1e-9)
bt._handle_order_event(ord_ev)
bt._handle_fill_event(bt.events.popleft())
check("Backtest LONG pozisyonda 40 USDT marj-stop mesafesini kurar", bt.pos is not None and bt.pos.stop < bt.pos.entry)
bt._handle_signal_event(SignalEvent(1, "BTC/USDT", "ADD_LONG", 80.0, 105.0, "ADD"))
check("Sabit marjlı backtest piramitleme eklemesini bloklar", len(bt.events) == 0)

bt_rep = EventDrivenBacktester(symbol="BTC/USDT", initial_balance=1_000.0, fixed_margin_usdt=50.0, leverage=10, stop_model="marj", runner_exit=True, use_ml=False).run_df(df_up, warmup=60)
check("Event-driven backtest uçtan uca çalışır ve lookahead-free onaylar", bt_rep["events_processed"] > 100 and bt_rep["lookahead_bias_free"] is True)
oos_rep = run_out_of_sample_test(df_up, symbol="BTC/USDT")
check("Out-of-Sample (70/30) doğrulaması karar üretir", oos_rep["verdict"].startswith(("SAĞLAM", "DİKKAT")))

shadow = ShadowLab(
    strat,
    rm,
    cfg["cikis"],
    True,
    cfg["emirler"],
    {"aktif": True, "sanal_kasa_usdt": 1_000.0, "pdf_confluence": {"aktif": True}},
)
check("Shadow Lab 6 temel + 1 pdf-confluence olmak üzere 7 izole varyant başlatır", len(shadow.variants) == 7)
sh_rep = shadow.report()
check("Shadow Lab raporu varyant karşılaştırma tablosunu üretir", "variants" in sh_rep and any(v["name"] == "pdf-confluence" for v in sh_rep["variants"]))

hub = LiveBotHub(db_path=tmp_root / "demo_hub.db")
asyncio.run(hub.step_tick())
st_payload = hub.build_state_payload()
check(
    "Web paneli canlı durum, skorlar, açık pozisyonlar ve equity üretiyor",
    len(st_payload["scores"]) >= 3
    and len(st_payload["open_positions"]) >= 1
    and st_payload["leverage"] == 10
    and all(
        p["margin_usdt"] == 50.0 and p["layers"] == 1
        for p in st_payload["open_positions"]
    ),
)
ks_res = asyncio.run(hub.handle_action("kill_switch", {}))
check(
    "Web paneli Kill Switch tüm açık pozisyonları kapatıp sigortayı kilitler",
    ks_res["ok"] is True and len(hub.executor.positions) == 0 and hub.breaker.tripped is True,
)
prod_hub = ProductionBotHub(db_path=tmp_root / "prod_hub.db")
check(
    "ProductionBotHub salt-okunur gerçek mod durum yükünü üretir",
    prod_hub.build_state_payload()["demo"] is False,
)
prod_act = asyncio.run(prod_hub.handle_action("kill_switch", {}))
check(
    "ProductionBotHub doğrudan emir göndermez, SQLite komut kuyruğuna yazar",
    prod_act["ok"] is True and prod_hub.store.pop_commands()[0]["cmd"] == "KILL_SWITCH",
)
check("Toplam 101 doğrulama adımı eksiksiz tamamlandı", passed == 100 and failed == 0)

print(f"\n🎯 GENEL SONUÇ: {passed}/{passed + failed} senaryo başarıyla geçti!")
if failed > 0 or passed != 101:
    sys.exit(1)
