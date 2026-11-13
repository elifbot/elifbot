import os, sys, time, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import bot_v7 as B

ok = fail = 0
def check(n, c):
    global ok, fail
    if c: ok += 1; print("  OK  ", n)
    else: fail += 1; print("  FAIL", n)

def candles(n=300, drift=0.0005, seed=3, start=100.0, tf=3600, forming=True):
    rng = np.random.default_rng(seed)
    close = start*np.exp(np.cumsum(rng.normal(drift, 0.006, n)))
    op = np.roll(close,1); op[0]=start
    hi = np.maximum(op,close)*1.002; lo = np.minimum(op,close)*0.998
    now = int(time.time()//tf)*tf
    ts = [(now-(n-1-i)*tf)*1000 for i in range(n)]   # son mum = oluşmakta olan
    return [[ts[i],op[i],hi[i],lo[i],close[i],10] for i in range(n)]

class FakeEx:
    def __init__(self):
        self.last = {"BTC/USDT:USDT": 100.0, "ETH/USDT:USDT": 50.0}
        self.markets = {s: {"swap":True,"linear":True,"quote":"USDT","settle":"USDT","active":True,
                            "contractSize":1.0,"limits":{"amount":{"min":0.001},"cost":{"min":5}}}
                        for s in self.last}
        self.markets["BTC/USDT-240628"] = {"swap":False,"linear":True,"quote":"USDT","settle":"USDT","active":True}
    def load_markets(self, reload=False): return self.markets
    def market(self, s): return self.markets[s]
    def amount_to_precision(self, s, a): return str(round(a, 3))
    def fetch_tickers(self):
        t = {s: {"last":p,"quoteVolume":5e7} for s,p in self.last.items()}
        t["BTC/USDT-240628"] = {"last":1,"quoteVolume":9e9}
        return t
    def fetch_ticker(self, s): return {"last": self.last[s]}
    def fetch_ohlcv(self, s, tf, limit=300):
        return candles(limit, seed=hash(s)%1000)

fx = FakeEx()
bot = B.Bot(exchanges={"Binance": fx, "OKX": FakeEx()})

print("1) indikatör")
raw = candles(300); df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"]).iloc[:-1]
ind = B.compute_indicators(df)
check("indikatörler hesaplandı", ind is not None)
check("RSI 0-100", 0 <= ind["rsi"] <= 100)
check("ATR>0, ADX 0-100", ind["atr"] > 0 and 0 <= ind["adx"] <= 100)
check("kısa veride None", B.compute_indicators(df.iloc[:50]) is None)

print("2) evren filtresi")
u = bot.build_universe("Binance")
check("delivery kontrat elendi", "BTC/USDT-240628" not in u and len(u) == 2)

print("3) boyutlandırma + likidasyon tamponu")
qty, lev, margin, sd = bot.size_position(fx, "BTC/USDT:USDT", 100.0, 1.0)
check("risk ≈ kasanın %1'i", abs(qty*sd - 10.0) < 0.1)
check("stop mesafesi (%1.5) likidasyon tamponu içinde", sd/100 <= B.CFG["liq_buffer"]/lev)
r = bot.size_position(fx, "BTC/USDT:USDT", 100.0, 80.0)
check("aşırı geniş stop reddedildi", r[0] is None)

print("4) giriş / breakeven / TP / PnL")
check("giriş açıldı", bot.open_position("Binance", fx, "BTC/USDT:USDT", "LONG", 100.0, 1.0))
key = ("Binance","BTC/USDT:USDT"); p = bot.pos[key]
check("long: stop girişin altında, tp üstünde", p["stop"] < p["entry"] < p["tp"])
check("aynı sembol tekrar engellendi", bot.gate("BTC/USDT:USDT","LONG") == "zaten açık")
bot.check_position(key, p["entry"] + 1.1*p["init_risk"])
check("+1R'de breakeven", bot.pos[key]["be_done"] == 1 and bot.pos[key]["stop"] > p["entry"])
bot.check_position(key, p["entry"] + 2.6*p["init_risk"])
check("TP'de kapandı", key not in bot.pos)
pnl = bot._db("SELECT pnl FROM trades")[0][0]
check("kârlı kapanış, komisyon düşülmüş", 0 < pnl < 2.6*p["init_risk"]*p["qty"])
check("cooldown devrede", bot.gate("BTC/USDT:USDT","LONG") == "cooldown")

print("5) short + stop")
bot.open_position("Binance", fx, "ETH/USDT:USDT", "SHORT", 50.0, 0.5)
k2 = ("Binance","ETH/USDT:USDT"); p2 = bot.pos[k2]
check("short: stop üstte, tp altta", p2["stop"] > p2["entry"] > p2["tp"])
bot.check_position(k2, p2["stop"] + 0.01)
check("short stop çalıştı", k2 not in bot.pos and bot._db("SELECT reason FROM trades ORDER BY id DESC LIMIT 1")[0][0] == "STOP")
check("kayıp negatif PnL", bot._db("SELECT pnl FROM trades ORDER BY id DESC LIMIT 1")[0][0] < 0)

print("6) kalıcılık + kill-switch")
bot.cooldown.clear()
bot.open_position("OKX", bot.exchanges["OKX"], "BTC/USDT:USDT", "LONG", 100.0, 1.0)
bot.conn.close() if False else None
bot2 = B.Bot(exchanges={"Binance": FakeEx(), "OKX": FakeEx()})
check("açık pozisyon DB'den yüklendi", ("OKX","BTC/USDT:USDT") in bot2.pos)
check("cooldown DB'den yüklendi", "ETH/USDT:USDT" in bot2.cooldown)
bot2.on_command("/kill")
check("kill pozisyonları kapattı ve kilitledi", not bot2.pos and bot2.locked)
bot3 = B.Bot(exchanges={"Binance": FakeEx(), "OKX": FakeEx()})
check("kilit restart'ta korunuyor", bot3.locked)
bot3.on_command("/resume")
check("/resume kilidi açtı", not bot3.locked)

print("7) günlük zarar limiti")
bot3._db("INSERT INTO trades (exchange,symbol,side,entry,exit,qty,pnl,reason,opened,closed) VALUES ('X','Y','LONG',1,1,1,-80,'t',?,?)", (time.time(), time.time()))
check("günlük limit girişi durdurdu", bot3.entries_allowed() is False)

print("8) tam tarama (sahte veri, hata fırlatmamalı)")
bot4 = B.Bot(exchanges={"Binance": FakeEx(), "OKX": FakeEx()})
bot4._db("DELETE FROM trades"); bot4.cooldown.clear()
bot4.scan()
check("scan çökmeden bitti", True)
check("aynı slotta tekrar taranmaz", not bot4.scan_due() or time.time() % B.TF_SECONDS < B.CFG["scan_delay_s"])

print("9) token maskeleme")
B.register_secret("123456:ABC-SECRET-TOKEN")
check("maskelendi", "ABC-SECRET" not in B.mask("hata url=https://api.telegram.org/bot123456:ABC-SECRET-TOKEN/x"))

print(f"\n{ok} geçti, {fail} kaldı")
sys.exit(1 if fail else 0)
