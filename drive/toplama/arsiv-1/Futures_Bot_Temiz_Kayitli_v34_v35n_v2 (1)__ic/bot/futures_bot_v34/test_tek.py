#!/usr/bin/env python3
"""test_tek.py — FROZEN tek adayı verilen tarih aralığında test et.
Sweep_v2'den bağımsız. Hiperparametre ARAMAZ, sadece test eder."""
import argparse, json, os, statistics, sys, time
import urllib.request, urllib.error
from datetime import datetime, timezone

HOSTLAR = ["https://www.binance.com/fapi/v1/klines",
           "https://fapi.binance.com/fapi/v1/klines"]

def _get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 418): time.sleep(2*(2**i)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < retries-1: time.sleep(2*(2**i)); continue
            raise
    raise RuntimeError(url)

def _klines(sym, limit, end_time):
    for h in HOSTLAR:
        try:
            return _get(f"{h}?symbol={sym}&interval=1m&limit={limit}&endTime={end_time}")
        except urllib.error.HTTPError as e:
            if e.code in (451, 403):
                print(f"    {h.split('/')[2]}: HTTP {e.code} → sonraki", flush=True); continue
            raise
    raise RuntimeError("hostlar reddetti")

def indir_aralik(sym, bas_ms, bit_ms):
    tum, cursor = [], bit_ms
    while cursor > bas_ms:
        page = _klines(sym, 1500, cursor)
        if not page: break
        tum = page + tum
        cursor = page[0][0] - 1
        if page[0][0] <= bas_ms: break
    return [m for m in tum if bas_ms <= int(m[0]) < bit_ms]

def rvol(m):
    rv = {}
    for i in range(120, len(m)):
        s = sum(float(x[5]) for x in m[i-60:i])
        g = [sum(float(x[5]) for x in m[j-60:j]) for j in range(i-120, i-60, 60)]
        if not g: continue
        o = statistics.mean(g)
        rv[i] = s/o if o > 0 else 0
    return rv

def sinyaller(m, ret_e, rv_e, bag_e):
    r = rvol(m); out = []
    for i in range(120, len(m)-60):
        o, c = float(m[i][1]), float(m[i][4])
        if o == 0: continue
        ret = (c-o)/o*100
        if abs(ret) < ret_e: continue
        if r.get(i,0) < rv_e: continue
        if bag_e > 0:
            o3 = float(m[i-3][1])
            if o3 == 0 or abs((c-o3)/o3*100) < bag_e: continue
        out.append({"i": i, "yon": "short" if ret > 0 else "long"})
    return out

def simule(s, m, tp, sl, uc, ky, max_tut=240):
    i = s["i"]
    if i+1 >= len(m): return None
    g0 = float(m[i+1][1])
    if g0 <= 0: return None
    g = g0*(1+ky/100) if s["yon"]=="long" else g0*(1-ky/100)
    tp_f = g*(1+tp/100) if s["yon"]=="long" else g*(1-tp/100)
    sl_f = g*(1-sl/100) if s["yon"]=="long" else g*(1+sl/100)
    for j in range(i+1, min(i+1+max_tut, len(m))):
        o, h, l = float(m[j][1]), float(m[j][2]), float(m[j][3])
        if s["yon"]=="long":
            if o<=sl_f: return {"pnl": ((o*(1-ky/100))-g)/g*100 - 2*uc, "n": "sl_acilis"}
            if l<=sl_f: return {"pnl": ((sl_f*(1-ky/100))-g)/g*100 - 2*uc, "n": "sl"}
            if h>=tp_f: return {"pnl": ((tp_f*(1-ky/100))-g)/g*100 - 2*uc, "n": "tp"}
        else:
            if o>=sl_f: return {"pnl": ((g-(o*(1+ky/100)))/g)*100 - 2*uc, "n": "sl_acilis"}
            if h>=sl_f: return {"pnl": ((g-(sl_f*(1+ky/100)))/g)*100 - 2*uc, "n": "sl"}
            if l<=tp_f: return {"pnl": ((g-(tp_f*(1+ky/100)))/g)*100 - 2*uc, "n": "tp"}
    j = min(i+1+max_tut, len(m)-1); cc = float(m[j][4])
    pnl = ((cc*(1-ky/100))-g)/g*100 if s["yon"]=="long" else ((g-(cc*(1+ky/100)))/g)*100
    return {"pnl": pnl - 2*uc, "n": "timeout"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bas", required=True)
    ap.add_argument("--bit", required=True)
    ap.add_argument("--semboller", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,ATOMUSDT,LTCUSDT,UNIUSDT,ARBUSDT,OPUSDT,APTUSDT,SUIUSDT,INJUSDT,NEARUSDT")
    ap.add_argument("--baglam", type=float, default=1.2)
    ap.add_argument("--ret", type=float, default=0.5)
    ap.add_argument("--rvol", type=float, default=5.0)
    ap.add_argument("--tp", type=float, default=1.25)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--kayma", type=float, default=0.05)
    ap.add_argument("--ucret", type=float, default=0.04)
    ap.add_argument("--cikti", default="reports/oos_test")
    a = ap.parse_args()
    os.makedirs(a.cikti, exist_ok=True)
    bas_ms = int(datetime.strptime(a.bas, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
    bit_ms = int(datetime.strptime(a.bit, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
    semb = [s.strip() for s in a.semboller.split(",") if s.strip()]

    print(f"=== OOS TEST | {len(semb)} sembol | {a.bas} → {a.bit} ===")
    print(f"FROZEN: bag={a.baglam} ret={a.ret} rvol={a.rvol} tp={a.tp} sl={a.sl}\n")

    tum = []
    for sym in semb:
        dosya = os.path.join(a.cikti, f"oos_{sym}_{a.bas}_{a.bit}.json")
        if os.path.exists(dosya):
            mumlar = json.load(open(dosya))
            print(f"  {sym}: cache {len(mumlar)}")
        else:
            print(f"  {sym}: indiriliyor...", end=" ", flush=True)
            try:
                mumlar = indir_aralik(sym, bas_ms, bit_ms)
                if len(mumlar) < 1000:
                    print(f"ATLANDI ({len(mumlar)})"); continue
                json.dump(mumlar, open(dosya, "w"))
                print(f"{len(mumlar)} ({len(mumlar)/60:.0f}sa)")
            except Exception as e:
                print(f"HATA: {e}"); continue
        ss = sinyaller(mumlar, a.ret, a.rvol, a.baglam)
        isl = [r for s in ss if (r := simule(s, mumlar, a.tp, a.sl, a.ucret, a.kayma))]
        if isl:
            o = sum(r["pnl"] for r in isl)/len(isl)
            print(f"    → {len(ss)} sinyal, {len(isl)} işlem, ort {o:+.3f}%")
        tum.extend(isl)

    print(f"\n=== SONUÇ ({a.bas} → {a.bit}) ===")
    if not tum: print("0 işlem"); return 1
    kaz = [t for t in tum if t["pnl"] > 0]
    n = {}
    for t in tum: n[t["n"]] = n.get(t["n"], 0)+1
    ort = sum(t["pnl"] for t in tum)/len(tum)
    wr = len(kaz)/len(tum)
    print(f"Toplam: {len(tum)} | Kazanma: {len(kaz)} ({wr*100:.1f}%) | Ort: {ort:+.4f}%")
    print(f"Çıkışlar: {n}")
    print(f"\nBEKLENTİ 100 işlem: {ort*100:+.2f}%")
    if ort > 0 and wr >= 0.45:
        print(f"SONUÇ: ✅ OOS POZİTİF — Paper'a geçiş GEREKÇELİ")
    else:
        print(f"SONUÇ: ❌ OOS ZAYIF/NEGATİF — Paper'a geçme")
    return 0

if __name__ == "__main__":
    sys.exit(main())
