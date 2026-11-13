#!/usr/bin/env python3
"""backtest_v1.py — referans strateji backtest (fade + RVOL + TP/SL).
BAĞIMSIZ: ws_bot.py'yi etkilemez. Gerçek detektörle eşleşmeyebilir."""
import argparse, json, statistics, time, urllib.request

BINANCE = "https://fapi.binance.com/fapi/v1/klines"

def klines(sym, interval="1m", limit=1500):
    url = f"{BINANCE}?symbol={sym}&interval={interval}&limit={limit}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())

def indir(sym, gun):
    hedef = gun * 1440
    tum = []
    while len(tum) < hedef:
        page = klines(sym, "1m", min(1500, hedef - len(tum)))
        if not page: break
        tum = page + tum
    return tum[-hedef:]

def sinyal_bul(mumlar, ret_esik, rvol_esik, baglam_esik):
    # RVOL: son 60 dk hacim / önceki 60 dk ortalaması
    rv = {}
    for i in range(120, len(mumlar)):
        son = sum(float(m[5]) for m in mumlar[i-60:i])
        gecmis = [sum(float(m[5]) for m in mumlar[j-60:j]) for j in range(i-120, i-60, 60)]
        ort = statistics.mean(gecmis) if gecmis else 0
        rv[i] = son / ort if ort > 0 else 0
    sinyaller = []
    for i in range(120, len(mumlar) - 60):
        o, c = float(mumlar[i][1]), float(mumlar[i][4])
        if o == 0: continue
        ret = (c - o) / o * 100
        if abs(ret) < ret_esik: continue
        if rv.get(i, 0) < rvol_esik: continue
        o3 = float(mumlar[i-3][1])
        bret = (c - o3) / o3 * 100 if o3 > 0 else 0
        if abs(bret) < baglam_esik: continue
        yon = "short" if ret > 0 else "long"  # fade
        sinyaller.append({"i": i, "yon": yon, "ret": ret, "rvol": rv[i]})
    return sinyaller

def simulate(sinyaller, mumlar, tp, sl, ucret, kayma, max_tut=240):
    islemler = []
    for s in sinyaller:
        i = s["i"]; giris = float(mumlar[i][4])
        giris *= (1 + kayma/100) if s["yon"]=="long" else (1 - kayma/100)
        tp_f = giris*(1+tp/100) if s["yon"]=="long" else giris*(1-tp/100)
        sl_f = giris*(1-sl/100) if s["yon"]=="long" else giris*(1+sl/100)
        cikis = neden = None
        for j in range(i+1, min(i+max_tut, len(mumlar))):
            y, k = float(mumlar[j][2]), float(mumlar[j][3])
            if s["yon"]=="long":
                if k<=sl_f: cikis, neden = sl_f, "sl"; break
                if y>=tp_f: cikis, neden = tp_f, "tp"; break
            else:
                if y>=sl_f: cikis, neden = sl_f, "sl"; break
                if k<=tp_f: cikis, neden = tp_f, "tp"; break
        if cikis is None:
            cikis = float(mumlar[min(i+max_tut, len(mumlar)-1)][4]); neden = "timeout"
        pnl = ((cikis-giris)/giris*100) if s["yon"]=="long" else ((giris-cikis)/giris*100)
        pnl -= 2*ucret
        islemler.append({"pnl": pnl, "neden": neden, "yon": s["yon"]})
    return islemler

def rapor(islemler):
    if not islemler: print("Sinyal yok."); return
    kaz = [t for t in islemler if t["pnl"]>0]; kay = [t for t in islemler if t["pnl"]<=0]
    top = sum(t["pnl"] for t in islemler); ort = top/len(islemler)
    ko = sum(t["pnl"] for t in kaz)/len(kaz) if kaz else 0
    ka = sum(t["pnl"] for t in kay)/len(kay) if kay else 0
    ns = {}
    for t in islemler: ns[t["neden"]] = ns.get(t["neden"],0)+1
    wr = len(kaz)/len(islemler)
    beklenti = wr*ko + (1-wr)*ka
    print(f"\n=== BACKTEST ===")
    print(f"Sinyal: {len(islemler)} | Kazanç: {len(kaz)} ({wr*100:.1f}%) | Kayıp: {len(kay)}")
    print(f"Toplam PnL: {top:+.3f}% | Ort/işlem: {ort:+.3f}%")
    print(f"Ort kazanç: {ko:+.3f}% | Ort kayıp: {ka:+.3f}%")
    print(f"Çıkışlar: {ns}")
    print(f"BEKLENTİ/işlem: {beklenti:+.4f}%  |  100 işlemde: {beklenti*100:+.2f}%")
    print(f"SONUÇ: {'POZİTİF ✓' if beklenti>0 else 'NEGATİF ✗'}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semboller", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT")
    ap.add_argument("--gun", type=int, default=7)
    ap.add_argument("--ret", type=float, default=0.5)
    ap.add_argument("--rvol", type=float, default=5.0)
    ap.add_argument("--baglam-ret", type=float, default=1.2)
    ap.add_argument("--tp", type=float, default=1.25)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--ucret", type=float, default=0.04)
    ap.add_argument("--kayma", type=float, default=0.05)
    a = ap.parse_args()
    print(f"Strateji: fade | ret>={a.ret}% | rvol>={a.rvol} | baglam>={a.baglam_ret}%")
    print(f"TP={a.tp}% | SL={a.sl}% | Ücret={a.ucret}%×2 | Kayma={a.kayma}%")
    tum = []
    for sym in a.semboller.split(","):
        sym = sym.strip()
        try:
            m = indir(sym, a.gun)
            s = sinyal_bul(m, a.ret, a.rvol, a.baglam_ret)
            i = simulate(s, m, a.tp, a.sl, a.ucret, a.kayma)
            print(f"{sym}: {len(m)} mum, {len(s)} sinyal, {len(i)} işlem")
            tum.extend(i)
        except Exception as e:
            print(f"{sym}: HATA — {e}")
    rapor(tum)

if __name__ == "__main__":
    main()
