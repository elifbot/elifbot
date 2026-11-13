import os, sys, time, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
# Çevrimdışı testler asla gerçek Telegram hesabına istek göndermemeli.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import bot_v7 as B

passed = 0
failed = 0


def check(name: str, cond: bool):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ [{passed:02d}] {name}")
    else:
        failed += 1
        print(f"  ❌ [FAIL] {name}")


def make_df(n: int = 240, drift: float = 0.002, start: float = 100.0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = drift + rng.normal(0.0, 0.003, size=n)
    close = start * np.cumprod(1.0 + rets)
    open_ = np.roll(close, 1)
    open_[0] = start
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    vol = rng.uniform(100.0, 500.0, size=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol})


print("🧪 bot_v7 — 27 Bağımsız Çevrimdışı Paper Senaryosu Başlıyor...")

# 1-5: İndikatör ve ısınma testleri
check("120 mumdan kısa veride indikatör None döner", B.compute_indicators(make_df(80)) is None)
ind_up = B.compute_indicators(make_df(250, drift=0.003, seed=11))
check("Yeterli mumda indikatör sözlüğü üretilir", isinstance(ind_up, dict))
check("Yükseliş serisinde EMA20 > EMA50 > EMA200 dizilimi oluşur", ind_up["trend"] == 1)
check("ATR pozitif ve sonlu hesaplanır", ind_up["atr"] > 0 and np.isfinite(ind_up["atr"]))
ind_dn = B.compute_indicators(make_df(250, drift=-0.003, seed=12))
check("Düşüş serisinde negatif trend (-1) algılanır", ind_dn["trend"] == -1)

# 6-12: Bot başlatma, Telegram izolasyonu ve pozisyon açılışı
tmp1 = tempfile.mkdtemp()
bot = B.Bot(initial_cash=10_000.0, cooldown_sec=60.0, data_dir=tmp1)
check("Telegram token boşken ağ gönderimi devre dışı", bot.tg.enabled is False)
check("Başlangıç kasası 10,000 USDT", abs(bot.cash - 10_000.0) < 1e-6)
check("Başlangıç özsermayesi kasaya eşit", abs(bot.equity() - 10_000.0) < 1e-6)

t0 = time.time()
p_long = bot.open_position("BTC/USDT", "LONG", 100.0, atr=2.0, now=t0)
check("LONG pozisyon başarıyla açılır", p_long is not None and p_long.side == "LONG")
check("Giriş komisyonu kasadan düşülür", bot.cash < 10_000.0)
check("LONG başlangıç stopu girişin 2 ATR altında", p_long.stop < p_long.entry)
check("LONG hedefi girişin 3 ATR üstünde", p_long.tp > p_long.entry)

# 13-18: Aynı sembol engeli, başabaş kilidi, trailing ve TP kapanışı
dup = bot.open_position("BTC/USDT", "LONG", 100.0, atr=2.0, now=t0 + 1)
check("Aynı sembolde ikinci eşzamanlı pozisyon engellenir", dup is None)
bot.on_tick("BTC/USDT", 103.5, now=t0 + 5)
check("1.5 ATR kârda stop başabaş üstüne taşınır", bot.pos["BTC/USDT"].be_moved is True and bot.pos["BTC/USDT"].stop > p_long.entry)
prev_stop = bot.pos["BTC/USDT"].stop
bot.on_tick("BTC/USDT", 105.0, now=t0 + 10)
check("Fiyat yükseldikçe trailing stop yukarı iz sürer", bot.pos["BTC/USDT"].stop > prev_stop)
ev_tp = bot.on_tick("BTC/USDT", 107.0, now=t0 + 15)
check("TP seviyesinde pozisyon otomatik kapanır", ev_tp == "TP" and "BTC/USDT" not in bot.pos)
check("Kârlı TP kapanışı sonrası kasa başlangıcın üzerine çıkar", bot.cash > 10_000.0)
check("Cooldown süresi dolmadan aynı sembolde yeni giriş engellenir", bot.open_position("BTC/USDT", "LONG", 107.0, 2.0, now=t0 + 30) is None)

# 19-23: SHORT yaşam döngüsü, kalıcılık (SQLite kurtarma) ve stop kapanışı
p_short = bot.open_position("ETH/USDT", "SHORT", 200.0, atr=4.0, now=t0 + 100)
check("SHORT pozisyon açılır ve stopu girişin üstündedir", p_short is not None and p_short.stop > p_short.entry)

bot_reloaded = B.Bot(initial_cash=10_000.0, cooldown_sec=60.0, data_dir=tmp1)
check("Yeniden başlatmada açık pozisyon SQLite'tan kurtarılır", "ETH/USDT" in bot_reloaded.pos)
check("Yeniden başlatmada kasa bakiyesi korunur", abs(bot_reloaded.cash - bot.cash) < 1e-5)

ev_sl = bot_reloaded.on_tick("ETH/USDT", 210.0, now=t0 + 120)
check("SHORT pozisyonda ters fiyat hareketinde STOP çalışır", ev_sl == "STOP" and "ETH/USDT" not in bot_reloaded.pos)
trades_cnt = bot_reloaded._db("SELECT COUNT(*) FROM trades")[0][0]
check("Kapanan işlemler SQLite trades tablosuna kaydedilir", trades_cnt == 2)

# 24-27: Günlük zarar kilidi ve uzaktan yönetim komutları
tmp2 = tempfile.mkdtemp()
bot2 = B.Bot(initial_cash=1_000.0, risk_pct=0.06, daily_loss_limit=0.04, data_dir=tmp2)
p_big = bot2.open_position("SOL/USDT", "LONG", 100.0, atr=5.0, now=t0)
bot2.on_tick("SOL/USDT", 88.0, now=t0 + 10)
check("Günlük zarar limiti aşıldığında bot otomatik kilitlenir", bot2.locked is True)
check("Kilitli botta yeni pozisyon açılmaz", bot2.open_position("BNB/USDT", "LONG", 300.0, 3.0, now=t0 + 20) is None)
resp_unlock = bot2.tg.dispatch_local("/kilitac")
check("/kilitac komutu kilidi kaldırır", bot2.locked is False and "açıldı" in resp_unlock)
bot2.open_position("BNB/USDT", "LONG", 300.0, 3.0, now=t0 + 30)
resp_kill = bot2.tg.dispatch_local("/kill")
check("/kill komutu tüm açık pozisyonları kapatıp botu kilitler", len(bot2.pos) == 0 and bot2.locked is True)

print(f"\n📊 bot_v7 Sonuç: {passed}/{passed + failed} senaryo geçti.")
if failed > 0 or passed != 27:
    sys.exit(1)
