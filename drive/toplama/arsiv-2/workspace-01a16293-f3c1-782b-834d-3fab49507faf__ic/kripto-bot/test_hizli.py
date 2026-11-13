"""İnternetsiz kapsamlı doğrulama (22 Bölüm):
  1-9  : İndikatör, Para Akışı, Haber, Risk, Strateji, ATR+Kelly, Korku/Açgözlülük, Walk-Forward, Maker+OCO
  10-17: %10 Kasa 20x, Sınırsız Ekleme, Çapraz Kurtarma, OI/Likidasyon Squeeze, Arbitraj, ML, SQLite, Event-Driven Backtest, Circuit Breaker, Web Paneli
  18   : Kritik Güvenlik ve Zırhlama (No Secret Leakage, .env İzolasyonu, Non-Root Docker, 3 Auth Hatası Kill-Switch, Input Sanitization)
  19   : Maksimum Kayma (%0.30) & Chase Order + Dinamik Kaldıraç (20x → 10x → 5x)
  20   : İki Yönlü İnteraktif Telegram Botu (/durum, /kill, Yetki Kontrolü)
  21   : Out-of-Sample (OOS) Aşırı Uyum (Overfitting) Test Modülü
  22   : WebSocket Keep-Alive (Ping/Pong) & Kopma Anında SQLite Durum Kurtarmalı Reconnect

Çalıştır:  python3 test_hizli.py
"""
import asyncio
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.arbitrage import ArbitrageEngine
from src.backtest import (
    EventDrivenBacktester,
    run_out_of_sample_test,
    verify_no_lookahead_bias,
)
from src.circuit_breaker import CircuitBreaker
from src.config import BASE_DIR, load_config
from src.dashboard import LiveBotHub
from src.exchanges import PaperBroker
from src.indicators import indicator_score
from src.market_data import MarketData
from src.ml_predictor import MLPredictor
from src.moneyflow import MoneyFlow
from src.news import NewsEngine, score_text
from src.risk import Position, RiskManager
from src.security import (
    mask_secrets,
    register_secret,
    safe_exception_msg,
    sanitize_external_text,
    verify_no_hardcoded_secrets,
)
from src.sentiment_ai import FearGreedEngine, local_fear_greed
from src.sizing import KellyTracker, PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.telegram import InteractiveTelegramBot
from src.walkforward import run_walkforward

passed, failed = 0, 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")


def fake_candles(n=300, drift=0.002, start=30000.0, seed=7):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.004, n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.roll(close, 1)
    open_[0] = start
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, n))
    vol = rng.uniform(10, 100, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol}
    )


print("1) İNDİKATÖRLER")
up = indicator_score(fake_candles(drift=0.004))
down = indicator_score(fake_candles(drift=-0.004))
check("yükselen trend pozitif skor", up["score"] > 10)
check("düşen trend negatif skor", down["score"] < -10)
check("12+ bileşen hesaplanıyor (funding ile 13)", len(up["components"]) >= 12)
check(
    "funding eklenince 13. bileşen geliyor",
    len(indicator_score(fake_candles(), funding_rate=0.002)["components"]) >= 13,
)
check("skor -100..100 aralığında", -100 <= up["score"] <= 100)

print("2) PARA AKIŞI (giriş/çıkış + balina)")
mf = MoneyFlow("BTC/USDT", whale_usdt=100_000)
for _ in range(100):
    mf.add_trade(30000, 0.5, is_buyer_maker=False)
for _ in range(20):
    mf.add_trade(30000, 0.5, is_buyer_maker=True)
w = mf.add_trade(30000, 5.0, is_buyer_maker=False)
snap = mf.snapshot()
check("net giriş pozitif skor", snap["score"] > 15 and snap["net_usdt"] > 0)
check("balina yakalandı", w is not None and w.side == "BUY")
check("CVD pozitif", snap["cvd"] > 0)
mf2 = MoneyFlow("ETH/USDT")
for _ in range(100):
    mf2.add_trade(2000, 1.0, is_buyer_maker=True)
check("net çıkış negatif skor", mf2.snapshot()["score"] < -15)

print("3) HABER ANALİZİ")
s1, u1, _ = score_text("Bitcoin ETF onaylandı, rekor giriş bekleniyor")
s2, u2, _ = score_text("Borsadan 200 milyon dolar çalındı, çekimler durduruldu")
s3, u3, _ = score_text("Ethereum güncellemesi tamamlandı")
check("olumlu haber pozitif", s1 > 20 and not u1)
check("hack haberi VETO", u2 and s2 < -50)
check("nötr/hafif haber", -20 < s3 < 40 and not u3)

print("4) RİSK (%5 stop, +%10 → stop +%5)")
rm = RiskManager()
pos = Position("BTC/USDT", "LONG", 100.0, 1.0, rm.initial_stop("LONG", 100.0))
check("ilk stop girişin %5 altında", abs(pos.stop - 95.0) < 1e-9)
r1 = rm.update(pos, 94.0)
check("%5 düşüşte STOP", r1["action"] == "close")

pos = Position("BTC/USDT", "LONG", 100.0, 1.0, rm.initial_stop("LONG", 100.0))
rm.update(pos, 111.0)
check(
    "+%10 sonrası stop en az +%5 kâra çekildi (+trailing)",
    pos.stop >= 105.0 - 1e-9 and pos.locked_profit,
)
r2 = rm.update(pos, 104.0)
check(
    "kâr kilidi stopu çalıştı",
    r2["action"] == "close" and r2["reason"] == "KÂR KİLİDİ STOPU",
)

pos = Position("BTC/USDT", "SHORT", 100.0, 1.0, rm.initial_stop("SHORT", 100.0))
check("short stop girişin %5 üstünde", abs(pos.stop - 105.0) < 1e-9)
qty = rm.position_size(10_000, 100.0, 95.0)
check("pozisyon büyüklüğü riski %1 ile sınırlı", abs(qty * 5.0 - 100.0) < 1e-6)

print("5) STRATEJİ BİRLEŞİMİ")
st = Strategy()
c = st.combine(80, 70, 50)
check("güçlü sinyal LONG", c["signal"] == "LONG" and c["total"] > 55)
c = st.combine(-80, -70, -50)
check("güçlü sinyal SHORT", c["signal"] == "SHORT" and c["total"] < -55)
d = st.entry_decision(st.combine(90, 90, 90), veto=True, has_position=False)
check("veto girişi engelliyor", d["action"] == "yok")
d = st.exit_decision("LONG", {"total": -30}, -60, False, 3.0)
check("ters sinyalde bot çıkıyor", d["action"] == "close")

print("6) ATR BOYUTLANDIRMA + KELLY")
tmp = tempfile.mkdtemp()
kt = KellyTracker(os.path.join(tmp, "k.json"), min_trades=20)
check("veri yokken Kelly pasif", kt.kelly_fraction() is None)
for _ in range(14):
    kt.record(5.0)
for _ in range(6):
    kt.record(-4.0)
f = kt.kelly_fraction()
check("Kelly f değeri mantıklı aralıkta", f is not None and 0 < f < 1)
sz = PositionSizer(kelly_min_trades=20, stats_path=os.path.join(tmp, "k2.json"))
r0, i0 = sz.risk_pct()
check("geçmiş yokken baz risk kullanılır", abs(r0 - 1.0) < 1e-9)
for _ in range(14):
    sz.kelly.record(5.0)
for _ in range(6):
    sz.kelly.record(-4.0)
r1, i1 = sz.risk_pct()
check("Kelly riski sınırlar içinde", 0.25 <= r1 <= 2.0 and i1["kaynak"] == "kelly")
q_calm, _ = sz.size(10_000, 100.0, 95.0, atr=1.0)
q_vol, iv = sz.size(10_000, 100.0, 95.0, atr=10.0)
check("oynak piyasada pozisyon küçülür", 0 < q_vol < q_calm and iv["atr_kisit"])
q_dust, _ = sz.size(5, 100.0, 95.0, atr=1.0)
check("min. tutar altı işlem engellenir", q_dust == 0.0)

print("7) KORKU / AÇGÖZLÜLÜK + VETO")
fg_fear = local_fear_greed("Panik satışları başladı, piyasada büyük korku ve çöküş")
fg_greed = local_fear_greed("Bitcoin ETF onaylandı, rekor giriş, tarihi ralli, coşku")
fg_mid = local_fear_greed("Ethereum güncellemesi planlandığı gibi tamamlandı")
check("korku metni düşük skor", fg_fear < 30)
check("coşku metni yüksek skor", fg_greed > 70)
check("nötr metin ortalarda", 35 < fg_mid < 65)
eng = FearGreedEngine()
val, src = asyncio.run(eng.ascore("ETF onaylandı, rekor giriş"))
check("LLM yokken yerel motor çalışır", src == "yerel" and val > 50)
ne1 = NewsEngine([], fear_veto_low=15, greed_long_veto_high=85)
ne1.push_item("Bitcoin ETF onaylandı rekor giriş tarihi ralli coşku boğa", "t")
m1 = ne1.mood()
check("aşırı coşku LONG vetosu verir", m1["veto_long"] and not m1["veto"])
ne2 = NewsEngine([], fear_veto_low=15, greed_long_veto_high=85)
ne2.push_item("Panik çöküş korku panik satışları iflas korkusu", "t")
m2 = ne2.mood()
check("panik tam veto verir", m2["veto"] and m2["fear_greed"] < 15)

print("8) WALK-FORWARD (mini)")
seg = [
    fake_candles(n=170, drift=0.006, start=30000.0, seed=1),
    fake_candles(n=170, drift=-0.006, start=34000.0, seed=2),
    fake_candles(n=170, drift=0.004, start=30000.0, seed=3),
]
wf_df = pd.concat(seg, ignore_index=True)
wf_df.insert(0, "timestamp", range(len(wf_df)))
wf_csv = os.path.join(tmp, "wf.csv")
wf_df.to_csv(wf_csv, index=False)
wf_out = os.path.join(tmp, "params_best.json")
best = run_walkforward(
    wf_csv, train=250, test=100, step=100, stride=10, out=wf_out, fast=True
)
check(
    "walk-forward parametre üretti",
    all(k in best for k in ("w_ind", "long_th", "short_th", "exit_th"))
    and os.path.exists(wf_out),
)

print("9) PAPER MAKER + KORUMA")
pb = PaperBroker()
m1 = pb.maker_order("BTC/USDT", "buy", 0.1, 30000)
m2 = pb.market_order("BTC/USDT", "buy", 0.1, 30000)
check("maker komisyonu taker'dan düşük", m1["fee"] < m2["fee"])
try:
    import ccxt  # noqa
    from src.exchanges import ExchangeManager

    cfg_mini = {
        "genel": {"mod": "paper", "semboller": ["BTC/USDT"], "borsalar": ["binance"]},
        "api": {},
        "emirler": {},
    }
    br = ExchangeManager(cfg_mini)
    fill = asyncio.run(
        br.execute_entry("BTC/USDT", "buy", 0.1, price_hint=30000, order_type="maker")
    )
    prot = asyncio.run(br.place_protection("BTC/USDT", "LONG", 0.1, 28500))
    ok_cancel = asyncio.run(br.cancel_protection("BTC/USDT", prot))
    asyncio.run(br.close())
    check(
        "paper maker giriş + koruma kaydı",
        fill.get("emir_tipi") == "maker" and prot.get("native") and ok_cancel,
    )
except ImportError:
    print("  ⏭ ccxt kurulu değil, ExchangeManager testi atlandı")

print("10) %10 KASA × 20X KALDIRAÇ + ARTIDA SINIRSIZ EKLEME + ÇAPRAZ KURTARMA")
sz_20x = PositionSizer(mode="kasa_10_20x", capital_pct=10.0, leverage=20)
qty_20x, info_20x = sz_20x.size(10_000.0, 50_000.0, 47_500.0)
check(
    "%10 kasa marj ($1000) × 20x kaldıraç = $20,000 büyüklük",
    abs(info_20x["margin_usdt"] - 1000.0) < 1e-6
    and abs(info_20x["notional"] - 20_000.0) < 1e-6
    and abs(qty_20x - 0.4) < 1e-6,
)

rm_p = RiskManager(
    stop_loss_pct=5.0,
    max_positions=2,
    capital_pct_per_entry=10.0,
    leverage=20,
    unlimited_pyramiding=True,
    pyramid_min_profit_pct=0.25,
)
p_win = Position("BTC/USDT", "LONG", 100.0, 2.0, 95.0, leverage=20, margin_usdt=10.0)
for step_i in range(1, 7):
    new_px = 100.0 + step_i * 1.0
    ok_add, _ = rm_p.can_add_to_winner(p_win, new_px)
    p_win.add_layer(new_px, 2.0, add_margin_usdt=10.0, stop_loss_pct=5.0)
check(
    "artıda sınırsız kademe eklemesi (7 kademeye ulaştı)",
    p_win.layers == 7 and p_win.qty == 14.0 and p_win.stop > 95.0,
)
ok_unlim, _ = rm_p.can_open(open_count=10, all_in_profit=True)
check("tüm pozisyonlar artıdayken max_positions sınırı kalkar", ok_unlim)

pos_winner = Position("BTC/USDT", "LONG", 100.0, 200.0, 95.0, leverage=20, margin_usdt=1000.0)
pos_loser = Position("ETH/USDT", "LONG", 100.0, 200.0, 95.0, leverage=20, margin_usdt=1000.0)
rescue = rm_p.find_pair_rescue(
    {"BTC/USDT": pos_winner, "ETH/USDT": pos_loser},
    {"BTC/USDT": 101.2, "ETH/USDT": 98.9},
)
check(
    "biri artıda biri ekside iken ufak kâr/zararla ikili kapama sinyali",
    rescue is not None
    and rescue["action"] == "pair_close"
    and rescue["winner_symbol"] == "BTC/USDT"
    and rescue["loser_symbol"] == "ETH/USDT"
    and abs(rescue["net_pnl_usdt"] - 20.0) < 1e-4,
)

print("11) AÇIK FAİZ (OI) & LİKİDASYON TAKİBİ (SQUEEZE)")
mf_sq = MoneyFlow("SOL/USDT", liq_squeeze_usdt=50_000)
mf_sq.update_open_interest(10_000_000, price=150.0, ts=time.time() - 60)
mf_sq.update_open_interest(10_250_000, price=153.0, ts=time.time())
mf_sq.add_trade(153.0, 100.0, is_buyer_maker=False)
mf_sq.add_liquidation("SHORT_LIQ", price=153.0, qty=600.0)
sq_snap = mf_sq.snapshot()
check(
    "Short Squeeze ve OI artışı tespit edildi",
    sq_snap["squeeze"] == "SHORT_SQUEEZE"
    and sq_snap["short_liq_usdt"] > 50_000
    and sq_snap["oi_change_pct"] > 2.0
    and sq_snap["score"] > 30,
)

mf_lsq = MoneyFlow("ETH/USDT", liq_squeeze_usdt=50_000)
mf_lsq.add_trade(2500.0, 20.0, is_buyer_maker=True)
mf_lsq.add_liquidation("LONG_LIQ", price=2500.0, qty=40.0)
lsq_snap = mf_lsq.snapshot()
check(
    "Long Squeeze tespit edildi",
    lsq_snap["squeeze"] == "LONG_SQUEEZE" and lsq_snap["score"] < -30,
)

print("12) ÇAPRAZ BORSA ARBİTRAJI (BINANCE ↔ OKX)")
arb = ArbitrageEngine(min_net_spread_pct=0.08, fee_per_leg_pct=0.03, slippage_pct=0.01)
arb.update_quote("binance", "BTC/USDT", bid=67990.0, ask=68000.0)
arb.update_quote("okx", "BTC/USDT", bid=68150.0, ask=68160.0)
opp = arb.check_opportunity("BTC/USDT")
check(
    "Binance ucuz / OKX pahalı arbitraj fırsatı yakalandı",
    opp is not None
    and opp["buy_exchange"] == "binance"
    and opp["sell_exchange"] == "okx"
    and opp["net_spread_pct"] > 0.10,
)
arb_rec = asyncio.run(arb.execute_arbitrage(opp))
check(
    "arbitraj yürütüldü ve net kâr kaydedildi",
    arb_rec["status"] == "EXECUTED" and arb.total_profit_usdt > 0,
)

print("13) MAKİNE ÖĞRENMESİ DESTEKLİ YÖN TAHMİNİ (ML PREDICTOR)")
ml = MLPredictor(horizon=3, min_train_bars=60, retrain_every=20)
df_up = fake_candles(n=180, drift=0.005, seed=11)
pred_up = ml.predict(df_up)
check(
    "ML modeli eğitildi ve olasılık/skor üretti",
    -100 <= pred_up["score"] <= 100
    and 0.0 < pred_up["prob_up"] < 1.0
    and pred_up["trained_samples"] > 50,
)

print("14) DURUM KALICILIĞI (SQLITE STATE PERSISTENCE)")
db_file = os.path.join(tmp, "state_test.db")
store1 = StateStore(db_file)
pos_save = Position(
    symbol="BTC/USDT",
    side="LONG",
    entry=65000.0,
    qty=0.307,
    stop=68250.0,
    peak=72000.0,
    locked_profit=True,
    leverage=20,
    margin_usdt=1000.0,
    layers=3,
)
store1.save_position(pos_save, exchange="binance")
store1.record_trade(
    "ETH/USDT",
    "LONG",
    2500.0,
    2600.0,
    8.0,
    4.0,
    "KÂR KİLİDİ",
    leverage=20,
    margin_usdt=1000.0,
    pnl_usdt=800.0,
    layers=2,
)
store2 = StateStore(db_file)
recovered = store2.load_positions()
rec_msgs = store2.startup_recovery_report()
check(
    "SQLite kesinti sonrası açık pozisyonu, kademeyi ve kâr kilidini kurtardı",
    "BTC/USDT" in recovered
    and recovered["BTC/USDT"].locked_profit is True
    and recovered["BTC/USDT"].layers == 3
    and recovered["BTC/USDT"].leverage == 20
    and len(rec_msgs) == 1,
)

print("15) EVENT-DRIVEN & SIFIR LOOK-AHEAD BIAS BACKTEST")
bt_df = pd.concat(
    [
        fake_candles(n=110, drift=0.005, start=30000.0, seed=21),
        fake_candles(n=90, drift=-0.005, start=34000.0, seed=22),
    ],
    ignore_index=True,
)
no_bias = verify_no_lookahead_bias(bt_df, check_bar=100)
check("Look-Ahead Bias matematiksel testi (gelecek değişince geçmiş sinyal 0 değişir)", no_bias)
ebt = EventDrivenBacktester("BTC/USDT", initial_balance=10_000.0, capital_pct=10.0, leverage=20)
bt_rep = ebt.run_df(bt_df, warmup=60)
check(
    "Event-Driven Backtest olay kuyruğu ile çalıştı",
    bt_rep["events_processed"] >= 140
    and bt_rep["lookahead_bias_free"] is True
    and len(bt_rep["equity_curve"]) == len(bt_df) - 60,
)

print("16) CIRCUIT BREAKER (ACİL DURUM SİGORTASI)")
cb = CircuitBreaker(max_consecutive_errors=3, daily_max_loss_pct=5.0, max_ws_disconnect_sec=10.0)
cb.record_order_error("timeout 1")
cb.record_order_error("timeout 2")
check("2 emir hatasında henüz atmaz", not cb.tripped)
cb.record_order_error("timeout 3")
check("ard arda 3 emir hatasında sigorta atar (Kill-Switch)", cb.tripped)
cb.reset()
cb.record_trade_pnl(-3.0)
cb.record_trade_pnl(-2.5)
check("günlük zarar %5'i geçince sigorta atar", cb.tripped and cb.daily_pnl_pct <= -5.0)
cb.reset()
cb.heartbeat_ws(time.time() - 12.0)
cb.check_ws_health(time.time())
check("WebSocket >10 sn kopunca sigorta atar", cb.tripped)

print("17) GERÇEK ZAMANLI WEB PANELİ (DASHBOARD + KILL SWITCH)")
hub = LiveBotHub(db_path=os.path.join(tmp, "dash.db"))
asyncio.run(hub.step_tick())
st_payload = hub.build_state_payload()
check(
    "Web paneli canlı durum, skorlar, açık pozisyonlar ve equity üretiyor",
    len(st_payload["scores"]) >= 3
    and len(st_payload["open_positions"]) >= 1
    and st_payload["leverage"] == 20,
)
ks_res = asyncio.run(hub.handle_action("kill_switch", {}))
check(
    "Web paneli Kill-Switch tüm pozisyonları kapatıp botu kilitliyor",
    ks_res["ok"] and len(hub.executor.positions) == 0 and hub.breaker.tripped,
)

print("18) KRİTİK GÜVENLİK VE ZIRHLAMA (SECURITY HARDENING)")
# 1. No Secret Leakage
register_secret("SUPER_SECRET_BINANCE_KEY_998877")
leaked_raw = (
    "Hata: apiKey=SUPER_SECRET_BINANCE_KEY_998877 "
    "secret='***REDACTED***' https://api.telegram.org/bot1234567:AAHfiqksKZ8WmR2zP9xL0/sendMessage"
)
masked_out = mask_secrets(leaked_raw)
exc_out = safe_exception_msg(RuntimeError(leaked_raw))
check(
    "API_KEY, API_SECRET ve Telegram Token loglarda tamamen maskeleniyor",
    "SUPER_SECRET_BINANCE_KEY_998877" not in masked_out
    and "myTopSecretValue12345" not in masked_out
    and "AAHfiqksKZ8WmR2zP9xL0" not in masked_out
    and "***MASKED***" in exc_out,
)
# 2. Environment Isolation (Hardcode kontrolü)
no_hardcoded, bad_files = verify_no_hardcoded_secrets(BASE_DIR / "src")
check(f"kaynak kodda hardcode edilmiş API anahtarı yok ({bad_files})", no_hardcoded)
# 3. Non-Root Docker User (appuser)
dockerfile_txt = (BASE_DIR / "Dockerfile").read_text(encoding="utf-8")
check(
    "Dockerfile içinde kısıtlı 'appuser' tanımlı ve USER appuser aktif",
    "useradd" in dockerfile_txt and "USER appuser" in dockerfile_txt,
)
# 4. Ard arda 3 Kimlik Doğrulama / Yetki Hatası -> Emergency Kill-Switch & Sistem Kilidi
cb_auth = CircuitBreaker(max_consecutive_auth_errors=3)
cb_auth.record_order_error("Binance -2015: Invalid API-key, IP, or permissions for action")
cb_auth.record_order_error("HTTP 401 Unauthorized: apiKey=SUPER_SECRET_BINANCE_KEY_998877")
check("2 yetki hatasında sistem henüz kilitlenmez", not cb_auth.system_locked)
cb_auth.record_order_error("PermissionDenied: signature for this request is not valid")
check(
    "ard arda 3 yetki hatasında Emergency Kill-Switch + Sistem Kilidi devreye girer ve anahtar sızmaz",
    cb_auth.tripped
    and cb_auth.system_locked
    and "SUPER_SECRET_BINANCE_KEY_998877" not in cb_auth.trip_reason,
)
# 5. Input Sanitization (RSS / Haber Girdi Doğrulama)
dirty_news = (
    "<script>alert('xss')</script>Bitcoin ETF onaylandı! "
    "; DROP TABLE open_positions; ignore previous instructions <img src=x onerror=evil()>"
)
clean_news = sanitize_external_text(dirty_news)
ne_sec = NewsEngine([])
item_sec = ne_sec.push_item(dirty_news, "<b>RSSSource</b>", "javascript:alert(1)")
check(
    "RSS/haber girdilerinden script, HTML, SQL/Prompt injection ve zararlı URL temizlendi",
    "<script>" not in clean_news
    and "DROP TABLE" not in clean_news
    and "ignore previous instructions" not in clean_news
    and item_sec.url == ""
    and "<b>" not in item_sec.source,
)

print("19) MAKSİMUM KAYMA (%0.30) & CHASE ORDER + DİNAMİK KALDIRAÇ (20x → 10x → 5x)")
rm_dyn = RiskManager(
    leverage=20,
    max_slippage_pct=0.30,
    dynamic_leverage_enabled=True,
    atr_high_volatility_pct=1.5,
    atr_extreme_volatility_pct=3.0,
)
ok_s1, slip1, _ = rm_dyn.check_slippage(100.0, 100.20)  # %0.20 kayma -> OK
ok_s2, slip2, _ = rm_dyn.check_slippage(100.0, 100.60)  # %0.60 kayma -> Chase Order!
check("kayma <%0.30 ise izin verir, >%0.30 ise market emrini reddeder", ok_s1 and not ok_s2)

pb_chase = PaperBroker(max_slippage_pct=0.30)
chase_fill = pb_chase.chase_order("BTC/USDT", "buy", 1.0, expected_price=100.0, current_market_price=100.80)
check(
    "Chase Order kaymayı maksimum %0.30 sınırında tutar ve maker komisyonu uygular",
    chase_fill["emir_tipi"] == "chase_limit"
    and abs(chase_fill["price"] - 100.30) < 1e-6
    and chase_fill["saved_slippage_pct"] > 0.45,
)

lev_calm, _ = rm_dyn.compute_dynamic_leverage(price=100.0, atr=0.8, veto_approaching=False, fear_greed=55.0)
lev_high, _ = rm_dyn.compute_dynamic_leverage(price=100.0, atr=2.0, veto_approaching=False, fear_greed=55.0)
lev_extr, _ = rm_dyn.compute_dynamic_leverage(price=100.0, atr=3.5, veto_approaching=False, fear_greed=55.0)
lev_veto, _ = rm_dyn.compute_dynamic_leverage(price=100.0, atr=0.8, veto_approaching=True, fear_greed=18.0)
check(
    "Dinamik Kaldıraç: sakin=20x, yüksek ATR=10x, aşırı ATR=5x, VETO yaklaşımı=5x",
    lev_calm == 20 and lev_high == 10 and lev_extr == 5 and lev_veto == 5,
)

print("20) TELEGRAM ÜZERİNDEN İKİ YÖNLÜ UZAKTAN KOMUT (/durum, /kill)")
hub_tg = LiveBotHub(db_path=os.path.join(tmp, "tg_test.db"))
tg = InteractiveTelegramBot(
    token="dummy_token",
    allowed_chat_id="777888",
    executor=hub_tg.executor,
    circuit_breaker=hub_tg.breaker,
    broker=hub_tg.broker,
)
unauth_rep = asyncio.run(tg.handle_command("/kill", sender_chat_id="999000"))
check("yetkisiz Telegram chat_id komutu reddedilir", "Yetkisiz" in unauth_rep and not hub_tg.breaker.tripped)
durum_rep = asyncio.run(tg.handle_command("/durum", sender_chat_id="777888"))
check(
    "/durum komutu anlık kasa, özsermaye ve açık pozisyon PnL tablosunu döner",
    "ANLIK DURUM RAPORU" in durum_rep and "BTC/USDT" in durum_rep,
)
kill_rep = asyncio.run(tg.handle_command("/kill", sender_chat_id="777888"))
check(
    "/kill komutu tüm açık pozisyonları acil kapatır ve botu kilitler",
    "ACİL KILL-SWITCH" in kill_rep
    and len(hub_tg.executor.positions) == 0
    and hub_tg.breaker.tripped,
)

print("21) OUT-OF-SAMPLE (OOS) AŞIRI UYUM (OVERFITTING) TEST MODÜLÜ")
oos_rep = run_out_of_sample_test(bt_df, train_ratio=0.70, symbol="BTC/USDT")
check(
    "Out-of-Sample testi %70 öğrenme / %30 görmediği veri ile çalıştı ve rapor üretti",
    oos_rep["train_bars"] == 140
    and oos_rep["oos_bars"] == 60
    and "in_sample" in oos_rep
    and "out_of_sample" in oos_rep
    and oos_rep["lookahead_bias_free"] is True,
)

print("22) WEBSOCKET KEEP-ALIVE (PING/PONG) & SQLITE DURUM KURTARMALI RECONNECT")
recon_db = os.path.join(tmp, "recon.db")
recon_store = StateStore(recon_db)
recon_store.save_position(
    Position("BTC/USDT", "LONG", 68000.0, 0.25, 71400.0, peak=75000.0, locked_profit=True, leverage=20)
)
md = MarketData(
    symbols=["BTC/USDT"],
    exchanges=["binance", "okx"],
    state_store=recon_store,
    on_ws_heartbeat=cb.heartbeat_ws,
)
md.record_pong("binance")
md.record_pong("okx")
recon_info = asyncio.run(md.handle_reconnect("binance"))
check(
    "WS Ping/Pong kaydedildi ve kopma sonrası SQLite'tan açık pozisyon anında kurtarıldı",
    md.ping_pong_count >= 3
    and recon_info["reconnect_count"] == 1
    and "BTC/USDT" in recon_info["recovered_symbols"],
)

print("23) MULTI-EXCHANGE FAILOVER (BORSA KESİNTİ SİGORTASI: BINANCE 3x TIMEOUT -> OKX)")
from src.exchanges import ExchangeManager
from src.health import HealthCheckServer, build_health_payload, build_prometheus_metrics

fo_cfg = {
    "genel": {"borsalar": ["binance", "okx"], "semboller": ["BTC/USDT"], "mod": "paper", "kaldıraç": 20},
    "risk": {"max_kayma_yuzde": 0.30},
    "emirler": {"komisyon_maker_yuzde": 0.02, "komisyon_taker_yuzde": 0.05},
    "failover": {"timeout_esigi": 3, "soguma_saniye": 300},
    "api": {},
}
em_fo = ExchangeManager(fo_cfg)
t1 = em_fo.record_exchange_timeout("binance", TimeoutError("Binance request timed out #1"))
t2 = em_fo.record_exchange_timeout("binance", TimeoutError("Binance request timed out #2"))
check("ilk 2 timeout'ta birincil borsa hala binance kalır", not t1 and not t2 and em_fo.primary == "binance")
t3 = em_fo.record_exchange_timeout("binance", TimeoutError("Binance request timed out #3"))
fo_snap = em_fo.exchange_health_snapshot()
check(
    "3. ardışık Binance timeout hatasında işlem ağırlığı otomatik OKX yedek borsasına kaydırılır",
    t3 is True
    and em_fo.primary == "okx"
    and em_fo.choose_healthy_exchange("binance") == "okx"
    and fo_snap["failover_active"] is True
    and fo_snap["active_primary"] == "okx",
)
fill_on_backup = asyncio.run(em_fo.execute_entry("BTC/USDT", "buy", 0.1, price_hint=68000.0))
check("Failover aktifken yeni pozisyonlar yedek borsa (OKX) üzerinden açılır", fill_on_backup.get("exchange") == "okx")
em_fo.record_exchange_success("binance")
check("Binance iyileştiğinde birincil borsa tekrar binance olur", em_fo.primary == "binance")
asyncio.run(em_fo.close())

print("24) SQLITE WAL MODU, GZIP LOG ROTATION & 24 SAATLİK VACUUM ÇÖP TOPLAYICI")
gc_db_path = os.path.join(tmp, "wal_gc_test.db")
gc_arch_dir = os.path.join(tmp, "archives")
gc_store = StateStore(gc_db_path, archive_dir=gc_arch_dir)
wal_st = gc_store.get_wal_status()
check("SQLite veritabanı otomatik WAL (Write-Ahead Logging) modunda açılır", wal_st["wal_active"] is True and wal_st["journal_mode"] == "wal")

for i in range(35):
    gc_store.record_trade("BTC/USDT", "LONG", 65000.0, 66000.0, 0.1, 1.5, f"TEST_TRADE_{i}")
    gc_store.record_equity(10000.0, 10000.0 + i * 10, 1)
gc_store.push_command("PAUSE")
_ = gc_store.pop_commands()

gc_res = gc_store.run_garbage_collector(max_trades=10, max_equity=10, max_arb=5, archive_gzip=True)
remaining_trades = gc_store.get_trades(limit=100)
check(
    "Çöp Toplayıcı (Garbage Collector) eski kayıtları .jsonl.gz olarak arşivler ve VACUUM çalıştırır",
    gc_res["ok"] is True
    and gc_res["archived_count"] == 50
    and gc_res["archive_file"] is not None
    and os.path.exists(gc_res["archive_file"])
    and len(remaining_trades) == 10
    and gc_res["vacuum_runs"] == 1,
)

print("25) GERÇEK ZAMANLI /health VE PROMETHEUS /metrics ENDPOINT")
hub_h = LiveBotHub(db_path=os.path.join(tmp, "health_test.db"))
code_ok, h_ok = build_health_payload(hub_h.store)
prom_txt = build_prometheus_metrics(hub_h.store)
check(
    "/health 200 OK + JSON ve /metrics Prometheus formatı döner",
    code_ok == 200
    and h_ok["alive"] is True
    and h_ok["healthy"] is True
    and h_ok["sqlite"]["wal_active"] is True
    and "kriptobot_up 1" in prom_txt
    and "kriptobot_sqlite_wal_active 1" in prom_txt,
)
_ = asyncio.run(hub_h.handle_action("sim_failover", {}))
code_fo, h_fo = build_health_payload(hub_h.store)
check(
    "Multi-Exchange Failover sırasında /health 200 OK ve active_exchange=okx döner",
    code_fo == 200 and h_fo["failover_active"] is True and h_fo["active_exchange"] == "okx",
)
_ = asyncio.run(hub_h.handle_action("kill_switch", {}))
code_unhealthy, h_unhealthy = build_health_payload(hub_h.store)
check(
    "Acil Kill-Switch durumunda /health 503 Service Unavailable döner",
    code_unhealthy == 503 and h_unhealthy["healthy"] is False,
)

print("26) MULTI-TIMEFRAME (1h / 4h ÇOKLU ZAMAN DİLİMİ) TREND FİLTRESİ")
from src.indicators import compute_htf_trend, multi_timeframe_filter

mtf_bull = multi_timeframe_filter(
    fake_candles(n=120, drift=0.005), fake_candles(n=120, drift=0.005)
)
mtf_bear = multi_timeframe_filter(
    fake_candles(n=120, drift=-0.005), fake_candles(n=120, drift=-0.005)
)
check(
    "1h ve 4h yükseliş trendinde BULLISH (allow_long=True, allow_short=False) üretir",
    mtf_bull["trend"] == "BULLISH" and mtf_bull["allow_long"] is True and mtf_bull["allow_short"] is False,
)
check(
    "1h ve 4h düşüş trendinde BEARISH (allow_long=False, allow_short=True) üretir",
    mtf_bear["trend"] == "BEARISH" and mtf_bear["allow_long"] is False and mtf_bear["allow_short"] is True,
)
# Ana trend (1h/4h) BEARISH iken 1m/5m grafikte güçlü LONG tepkisi (+75) gelse bile LONG açılmaz!
dec_blocked_long = st.entry_decision(
    {"total": 75.0, "signal": "LONG"}, veto=False, has_position=False, mtf_trend=mtf_bear
)
dec_allowed_short = st.entry_decision(
    {"total": -75.0, "signal": "SHORT"}, veto=False, has_position=False, mtf_trend=mtf_bear
)
check(
    "Ana trend (1h/4h) aşağı yönlüyken (BEARISH) 1m/5m küçük tepkide LONG açılmaz, SHORT açılır",
    dec_blocked_long["action"] == "yok"
    and "MTF TREND FİLTRESİ" in dec_blocked_long["reason"]
    and dec_allowed_short["action"] == "SHORT",
)
dec_blocked_short = st.entry_decision(
    {"total": -75.0, "signal": "SHORT"}, veto=False, has_position=False, mtf_trend=mtf_bull
)
check(
    "Ana trend (1h/4h) yukarı yönlüyken (BULLISH) ters yönlü SHORT açılmaz",
    dec_blocked_short["action"] == "yok" and "MTF TREND FİLTRESİ" in dec_blocked_short["reason"],
)

print("27) 20 KADEME EMİR DEFTERİ DERİNLİK ANALİZİ (ORDER BOOK 20-LEVEL DEPTH & BID/ASK RATIO)")
mf_depth = MoneyFlow("BTC/USDT", book_depth_levels=20)
bids_20_bull = [(68000.0 - i * 5, 3.0 if i not in (2, 5) else 12.0) for i in range(20)]
asks_20_bull = [(68005.0 + i * 5, 1.0) for i in range(20)]
dep_bull = mf_depth.update_book(bids_20_bull, asks_20_bull, depth=20)
snap_depth_bull = mf_depth.snapshot()
check(
    "20 kademe emir defterinde alıcı duvarı baskınken Bid/Ask Ratio > 2.5 ve skor pozitif artar",
    dep_bull["book_levels"] == 20
    and dep_bull["bid_ask_ratio"] > 2.5
    and dep_bull["wall_signal"] == "ALICI_DUVARI"
    and dep_bull["depth_score_boost"] > 10.0
    and snap_depth_bull["score"] > 10.0,
)
bids_20_bear = [(68000.0 - i * 5, 0.8) for i in range(20)]
asks_20_bear = [(68005.0 + i * 5, 3.5 if i not in (1, 4) else 15.0) for i in range(20)]
dep_bear = mf_depth.update_book(bids_20_bear, asks_20_bear, depth=20)
snap_depth_bear = mf_depth.snapshot()
check(
    "20 kademe emir defterinde satıcı duvarı baskınken Bid/Ask Ratio < 0.4 ve skor negatif olur",
    dep_bear["book_levels"] == 20
    and dep_bear["bid_ask_ratio"] < 0.4
    and dep_bear["wall_signal"] == "SATICI_DUVARI"
    and dep_bear["depth_score_boost"] < -10.0
    and snap_depth_bear["score"] < -10.0,
)

print("28) DISCORD WEBHOOK & PAGERDUTY ACİL DURUM ALARM ENTEGRASYONU")
from src.alerts import (
    MultiChannelAlerter,
    build_discord_payload,
    build_pagerduty_payload,
    is_critical_alert,
)

check(
    "Circuit Breaker ve Kill-Switch mesajları otomatik olarak kritik alarm sayılır",
    is_critical_alert("🚨 SİGORTA ATTI: ARD ARDA 3 EMİR HATASI")
    and is_critical_alert("CIRCUIT BREAKER: Günlük zarar limiti aşıldı")
    and not is_critical_alert("🟢 LONG AÇILDI | BTC/USDT"),
)
disc_crit = build_discord_payload("🚨 CIRCUIT BREAKER: Günlük zarar %5.2 aşıldı!")
pd_crit = build_pagerduty_payload("dummy_pd_key", "🚨 CIRCUIT BREAKER: Günlük zarar %5.2 aşıldı!")
check(
    "Discord acil durumda @everyone + kırmızı Embed (0xEF4444), PagerDuty severity=critical trigger üretir",
    "@everyone" in disc_crit["content"]
    and disc_crit["embeds"][0]["color"] == 0xEF4444
    and pd_crit["event_action"] == "trigger"
    and pd_crit["payload"]["severity"] == "critical",
)
mc_alerter = MultiChannelAlerter()
rec_crit = asyncio.run(mc_alerter("🚨 SİGORTA ATTI: ARD ARDA 3 EMİR HATASI"))
check(
    "MultiChannelAlerter kritik hatada Discord ve PagerDuty alarm sayaçlarını tetikler",
    rec_crit["critical"] is True
    and "discord" in rec_crit["channels"]
    and "pagerduty" in rec_crit["channels"]
    and mc_alerter.stats["pagerduty_triggered"] == 1
    and mc_alerter.stats["discord_dispatched"] == 1,
)

print(f"\nSONUÇ: {passed} geçti, {failed} kaldı")
raise SystemExit(1 if failed else 0)
