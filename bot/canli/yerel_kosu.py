"""Yerel koşu — gerçek OKX mumlarıyla (fetch_page ile çekildi, sandbox'ta borsa yok).

Kullanım:
    python3 -m bot.canli.yerel_kosu veri/*_1h.json
Sıralama: mumlar yeniden eskiye gelir; eskiden yeniye çevrilir, altı bot motoru
aynı gerçek mumlarda koşar. Kural seti bot/canli/botlar.py içindeki Taban'da.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from bot.canli.botlar import Taban, MotorV1, MotorV2, MotorV3


def yukle(yol: Path):
    ham = json.loads(yol.read_text())
    # OKX: [ts, o, h, l, c, vol, volCcy, volUsd, confirm] — yeniden eskiye
    mumlar = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in ham]
    mumlar.sort(key=lambda x: x[0])
    return mumlar


def kos(dosyalar, ayar: Taban | None = None):
    ayar = ayar or Taban()
    motorlar = [MotorV1(ayar), MotorV2(ayar), MotorV3(ayar)]
    adlar = ["v1 kbot (EMA+hacim)", "v2 kbot2 (rejim+komite)", "v3 kbot3 (kanit esikleri)"]

    bar = 0
    for f in dosyalar:
        sembol = Path(f).name.split("_")[0]
        mumlar = yukle(Path(f))
        bar += len(mumlar)
        for ts, o, h, l, c, v in mumlar:
            for m in motorlar:
                m.tick(sembol, o, h, l, c, v)

    sonuc = []
    for ad, m in zip(adlar, motorlar):
        s = m.ozet()
        s["surum"] = ad
        s["acik_pozisyon"] = len(m.pozlar)
        # açık pozisyonların son fiyata göre PnL'i
        pnl = 0.0
        for sym, p in m.pozlar.items():
            son = m.c[sym][-1]
            pnl += (son - p.giris) * p.miktar * p.yon
        s["acik_pnl_usd"] = round(pnl, 2)
        sonuc.append(s)
    return sonuc, bar, len(dosyalar)


def yaz(sonuc, bar, sembol_sayisi):
    print(f"\n=== {bar} bar · {sembol_sayisi} sembol · GERÇEK OKX mumları (1h) ===\n")
    hdr = f"{'surum':<30}{'islem':>6}{'WR':>8}{'PF':>8}{'net':>12}{'acik':>6}{'acikPnL':>10}"
    print(hdr)
    print("-" * len(hdr))
    for s in sonuc:
        print(f"{s['surum']:<30}{s['islem']:>6}{s['kazanma_orani']*100:>7.1f}%"
              f"{s['kar_faktoru']:>8.2f}{s['realize_usd']:>11.2f}${s['acik_pozisyon']:>6}"
              f"{s['acik_pnl_usd']:>9.2f}${'   ' + str(s.get('cikis_nedenleri', ''))}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dosyalar = []
    for a in args or ["veri/*_1h.json"]:
        dosyalar.extend(sorted(glob.glob(a)))
    if not dosyalar:
        sys.exit(f"veri bulunamadı: {args}")
    sonuc, bar, n = kos(dosyalar)
    yaz(sonuc, bar, n)
    cikti = Path("runs/yerel_okx")
    cikti.mkdir(parents=True, exist_ok=True)
    (cikti / "ozet.json").write_text(json.dumps(
        {"bar": bar, "sembol": n, "kaynak": "okx 1H candles (gerçek)",
         "sonuclar": sonuc}, ensure_ascii=False, indent=2))
    print(f"\nyazildi: {cikti}/ozet.json")


if __name__ == "__main__":
    main()
