# -*- coding: utf-8 -*-
"""test_4bot.py - BOT 1 / 2 / 3 / 4'u AYNI tick akisi uzerinde yan yana kosturur.

Kullanim:
    python test_4bot.py --senaryo
    python test_4bot.py --senaryo --json sonuc.json
    python test_4bot.py --ticks kayit.jsonl

Dosya duzeni (hepsi ayni klasorde):
    cekirdek.py  apex_bot.py  hybrid_bot.py      <- BOT 3 + BOT 4
    turbo_engine.py  akilli_filtre.py            <- BOT 1 (kendi zipinden)
    acarbot_omega/                               <- BOT 2 (kendi zipinden)

BOT 1 / BOT 2 bulunamazsa atlanir, kalanlar kosar (tabloda YOK gorunur).

ONEMLI: tickler varsayilan olarak ZAMAN GRUBU basina tek tek beslenir (gercek
zamanli akis gibi). --toplu verilirse hepsi tek blokta basilir; o durumda bot
hareketin tamamini bir anda gorur ve %0,60 kovalama filtresi her seyi reddeder.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback

BOT_TANIMLARI = [
    ("BOT1_TURBO", [
        ("turbo_engine", "TurboEngine"),
        ("turbo_engine", "Engine"),
        ("turbo_engine", "Turbo"),
    ]),
    ("BOT2_OMEGA", [
        ("acarbot_omega", "OmegaEngine"),
        ("acarbot_omega.engine", "OmegaEngine"),
        ("acarbot_omega", "Omega"),
        ("omega_engine", "OmegaEngine"),
    ]),
    ("BOT3_HYBRID", [("hybrid_bot", "HybridV2")]),
    ("BOT4_APEX", [("apex_bot", "Apex")]),
]


# ------------------------------------------------------------------ yukleme
def motor_yukle(adaylar):
    for modul, sinif in adaylar:
        try:
            m = importlib.import_module(modul)
        except Exception:
            continue
        k = getattr(m, sinif, None)
        if k is None:
            continue
        for arguman in ((), (1000.0,), (None,)):
            try:
                return k(*arguman)
            except Exception:
                continue
    return None


def _besleyici(motor):
    for ad in ("ingest_batch", "ingest_ticks", "add_ticks", "on_ticks"):
        fn = getattr(motor, ad, None)
        if callable(fn):
            return fn
    return None


def besle(motor, ticks, toplu=False):
    fn = _besleyici(motor)
    if fn is None:
        tek = getattr(motor, "ingest_tick", None)
        if callable(tek):
            for t in ticks:
                tek(t)
            return
        raise RuntimeError("motorun besleme metodu yok (ingest_batch/ingest_ticks/ingest_tick)")

    if toplu:
        for i in range(0, len(ticks), 2000):
            fn(ticks[i:i + 2000])
        return

    i = 0
    adet = len(ticks)
    while i < adet:
        ts = ticks[i].get("ts")
        j = i
        while j < adet and ticks[j].get("ts") == ts:
            j += 1
        fn(ticks[i:j])
        i = j


def durum_al(motor):
    for ad in ("snapshot", "ozet", "state", "rapor"):
        fn = getattr(motor, ad, None)
        if callable(fn):
            try:
                veri = fn()
                if isinstance(veri, dict):
                    return veri
            except Exception:
                continue
    return {}


def _bul(sozluk, *anahtarlar, varsayilan=0.0):
    for k in anahtarlar:
        if k in sozluk and sozluk[k] is not None:
            return sozluk[k]
    return varsayilan


def normalize(snap):
    hesap = snap.get("account") or {}
    evren = snap.get("universe") or {}
    filtre = snap.get("filtre") or {}
    return {
        "kasa": _bul(hesap, "live_equity_usd", "equity_usd", "equity", "live_equity"),
        "realize": _bul(hesap, "realized_pnl_usd", "realized_pnl"),
        "acik_pnl": _bul(hesap, "unrealized_pnl_usd", "unrealized_pnl"),
        "acik_adet": _bul(hesap, "open_count", "open_positions_count"),
        "kapanan": _bul(hesap, "closed_count"),
        "wr": _bul(hesap, "win_rate"),
        "pf": _bul(hesap, "profit_factor", varsayilan=None),
        "teminat": _bul(hesap, "used_margin_usd", "used_margin"),
        "risk": _bul(hesap, "open_risk_usd"),
        "sembol": _bul(evren, "total_symbols"),
        "tick": _bul(evren, "total_ticks"),
        "veto": (filtre.get("veto_sayaci") or {}),
    }


# ------------------------------------------------------------------ senaryo
def senaryo():
    """Deterministik (rastgelelik yok) sentetik akis - SADECE kod dogrulamasi.

    AAA     : 5x+ hacim patlamasi + yukari -> LONG, zirve sonrasi trail ile kar
    BBB     : 5x+ hacim cokusu -> SHORT, ters hareket -> -20 $ stop
    CCC     : zayif burst (4.000 $) -> filtre reddi
    W01..W20: ayni saniyede 20 sembol patlar -> APEX risk tavani (12),
              HYBRID marjin sinirina kadar (18) girer. Fark buradan cikar.
    """
    t0 = 1760000000.0
    ticks = []

    def ekle(ex, sym, px, usd, buy, ts):
        ticks.append({"exchange": ex, "symbol": sym, "price": round(px, 6),
                      "delta_usd": float(usd), "buy_usd": float(buy), "ts": float(ts)})

    taban = [("binance", "AAAUSDT", 100.0),
             ("binance", "BBBUSDT", 50.0),
             ("okx", "CCC-USDT-SWAP", 20.0)]
    for n in range(1, 21):
        taban.append(("binance", "W%02dUSDT" % n, 10.0))
    for sn in range(60):
        for ex, sym, px in taban:
            ekle(ex, sym, px, 300, 150, t0 + sn)

    # AAA - yukari patlama + trail
    ekle("binance", "AAAUSDT", 100.35, 30000, 27000, t0 + 60)
    for i, px in enumerate([100.90, 101.50, 102.10, 102.50, 102.50], start=61):
        ekle("binance", "AAAUSDT", px, 6000, 5400, t0 + i)
    for i, px in enumerate([102.00, 101.90, 101.90], start=66):
        ekle("binance", "AAAUSDT", px, 4000, 1200, t0 + i)

    # BBB - asagi patlama -> SHORT, sonra ters hareket -> stop
    ekle("binance", "BBBUSDT", 49.80, 26000, 2600, t0 + 60)
    px = 49.80
    for i in range(61, 81):
        px *= 1.005
        ekle("binance", "BBBUSDT", px, 9000, 8100, t0 + i)

    # CCC - zayif burst -> filtre reddi
    ekle("okx", "CCC-USDT-SWAP", 20.10, 4000, 3800, t0 + 60)
    ekle("okx", "CCC-USDT-SWAP", 20.12, 2200, 2000, t0 + 61)

    # W01..W20 - ayni saniyede toplu patlama
    for n in range(1, 21):
        sym = "W%02dUSDT" % n
        ekle("binance", sym, 10.025, 20000, 18000, t0 + 70)
        for i in (71, 72, 73):
            ekle("binance", sym, 10.025, 1500, 800, t0 + i)

    ticks.sort(key=lambda x: x["ts"])
    return ticks


def dosyadan(yol):
    ticks = []
    with open(yol, "r", encoding="utf-8") as fh:
        for satir in fh:
            satir = satir.strip()
            if not satir:
                continue
            try:
                veri = json.loads(satir)
            except ValueError:
                continue
            ticks.extend(veri if isinstance(veri, list) else [veri])
    return ticks


# ------------------------------------------------------------------ rapor
def tablo_yaz(satirlar):
    basliklar = ["BOT", "Kasa", "Getiri%", "Realize", "Acik PnL", "Acik",
                 "Kapanan", "WR", "PF", "Teminat", "Risk"]
    genislik = [13, 10, 9, 9, 10, 6, 9, 7, 6, 9, 8]

    def b(deger, w):
        return ("%s" % deger).rjust(w)

    print("".join(b(x, w) for x, w in zip(basliklar, genislik)))
    print("-" * sum(genislik))
    for s in satirlar:
        if s.get("yok"):
            print(b(s["bot"], 13) + b("YOK (modul bulunamadi)", sum(genislik) - 13))
            continue
        d = s["d"]
        try:
            getiri = (float(d["kasa"]) - 1000.0) / 10.0
        except (TypeError, ValueError):
            getiri = 0.0
        pf = d["pf"]
        deger = [s["bot"],
                 "%.2f" % float(d["kasa"]),
                 "%+.2f" % getiri,
                 "%+.2f" % float(d["realize"]),
                 "%+.2f" % float(d["acik_pnl"]),
                 "%d" % int(d["acik_adet"]),
                 "%d" % int(d["kapanan"]),
                 "%%%.0f" % (100.0 * float(d["wr"])),
                 "-" if pf is None else "%.2f" % float(pf),
                 "%.0f" % float(d["teminat"]),
                 "%.0f" % float(d["risk"])]
        print("".join(b(v, w) for v, w in zip(deger, genislik)))


def main():
    ap = argparse.ArgumentParser(description="4 bot yan yana test")
    ap.add_argument("--senaryo", action="store_true", help="gomsulu sentetik senaryo")
    ap.add_argument("--ticks", default=None, help="JSONL tick dosyasi")
    ap.add_argument("--json", default=None, help="sonuclari bu dosyaya yaz")
    ap.add_argument("--toplu", action="store_true", help="tek blokta besle (gercekci degil)")
    args = ap.parse_args()

    if args.ticks:
        ticks = dosyadan(args.ticks)
        kaynak = args.ticks
    else:
        ticks = senaryo()
        kaynak = "gomsulu senaryo"

    print("kaynak: %s | tick: %d | besleme: %s"
          % (kaynak, len(ticks), "toplu" if args.toplu else "zaman grubu"))
    print("")

    sonuclar = []
    for ad, adaylar in BOT_TANIMLARI:
        motor = motor_yukle(adaylar)
        if motor is None:
            sonuclar.append({"bot": ad, "yok": True})
            continue
        try:
            besle(motor, ticks, toplu=args.toplu)
            snap = durum_al(motor)
            sonuclar.append({"bot": ad, "d": normalize(snap), "ham": snap})
        except Exception:
            print("%s HATA:" % ad)
            traceback.print_exc()
            sonuclar.append({"bot": ad, "yok": True})

    tablo_yaz(sonuclar)
    print("")

    for s in sonuclar:
        if s.get("yok"):
            continue
        veto = s.get("d", {}).get("veto") or {}
        if veto:
            print("%s filtre veto: %s" % (s["bot"], json.dumps(veto, ensure_ascii=False)))

    kosanlar = [s for s in sonuclar if not s.get("yok")]
    if kosanlar:
        kazanan = max(kosanlar, key=lambda s: float(s["d"]["kasa"] or 0))
        print("")
        print("KAZANAN: %s (kasa %.2f $)" % (kazanan["bot"], float(kazanan["d"]["kasa"])))

    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump([{k: v for k, v in s.items() if k != "ham"} for s in sonuclar],
                          fh, ensure_ascii=False, indent=2)
            print("sonuclar yazildi: %s" % args.json)
        except OSError as exc:
            print("yazilamadi: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
