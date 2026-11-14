# -*- coding: utf-8 -*-
"""canli_test.py — Binance/OKX public klines ile 30 dakikalık gerçek veri testi.

API anahtarı GEREKMEZ: yalnız halka açık klines ucu kullanılır.

    python3 -m bot.canli.canli_test --borsa binance --sembol 20 --dakika 30
    python3 -m bot.canli.canli_test --borsa okx     --sembol 20 --dakika 30
    python3 -m bot.canli.canli_test --kuru          # ağ olmadan kendini dener

Çıktı: runs/canli_<zaman>/ozet.json + konsol tablosu.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

try:                                    # paket içinden
    from .botlar import MotorV1, MotorV2, MotorV3, Taban, uret
except ImportError:                     # doğrudan betik olarak
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from botlar import MotorV1, MotorV2, MotorV3, Taban, uret  # type: ignore

UA = {"User-Agent": "Mozilla/5.0 (kbot canli test)"}


def _get(url: str, deneme: int = 3, bekle: float = 1.5):
    son: Exception | None = None
    for i in range(deneme):
        try:
            istek = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(istek, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:                     # noqa: BLE001
            son = e
            time.sleep(bekle * (i + 1))
    raise RuntimeError(f"{url} alınamadı: {son}")


def binance_semboller(adet: int) -> list[str]:
    d = _get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    usdt = [x for x in d if x["symbol"].endswith("USDT")]
    usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
    return [x["symbol"] for x in usdt[:adet]]


def binance_klines(sembol: str, dakika: int) -> list[tuple]:
    sinir = min(1500, max(120, dakika + 300))
    d = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sembol}"
             f"&interval=1m&limit={sinir}")
    return [(float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in d]


def okx_semboller(adet: int) -> list[str]:
    d = _get("https://www.okx.com/api/v5/market/tickers?instType=SWAP")["data"]
    swap = [x for x in d if x["instId"].endswith("-USDT-SWAP")]
    swap.sort(key=lambda x: float(x.get("volCcy24h") or 0), reverse=True)
    return [x["instId"] for x in swap[:adet]]


def okx_klines(sembol: str, dakika: int) -> list[tuple]:
    sinir = min(300, max(120, dakika + 100))
    d = _get(f"https://www.okx.com/api/v5/market/candles?instId={sembol}"
             f"&bar=1m&limit={sinir}")["data"]
    d.reverse()                                    # OKX yeniden eskiye verir
    return [(float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in d]


def kos(sinif, ayar, seriler: dict[str, list[tuple]]) -> dict:
    m = sinif(ayar)
    n = max(len(v) for v in seriler.values())
    for i in range(n):
        for s, seri in seriler.items():
            if i < len(seri):
                m.tick(s, *seri[i])
    o = m.ozet()
    o["acik_pozisyon"] = len(m.pozlar)
    return o


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--borsa", default="binance", choices=["binance", "okx"])
    ap.add_argument("--sembol", type=int, default=20)
    ap.add_argument("--dakika", type=int, default=30)
    ap.add_argument("--kuru", action="store_true", help="ağ yok: sentetik veri")
    ap.add_argument("--etiket", default="")
    a = ap.parse_args(argv)

    if a.kuru:
        semboller = [f"S{i:02d}" for i in range(1, a.sembol + 1)]
        seriler = {s: uret(s, max(120, a.dakika + 300)) for s in semboller}
        kaynak = "SENTETIK (kuru kosu)"
    else:
        semboller = (binance_semboller if a.borsa == "binance" else okx_semboller)(a.sembol)
        cek = binance_klines if a.borsa == "binance" else okx_klines
        seriler = {}
        for s in semboller:
            try:
                seriler[s] = cek(s, a.dakika)
            except Exception as e:                 # noqa: BLE001
                print(f"  ! {s}: {e}", file=sys.stderr)
            time.sleep(0.08)                       # oran sınırı
        kaynak = f"{a.borsa.upper()} canli (public klines)"

    if not seriler:
        print("veri alinamadi", file=sys.stderr)
        return 2

    bar = max(len(v) for v in seriler.values())
    print(f"kaynak: {kaynak} · sembol {len(seriler)} · bar {bar} · "
          f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    print(f"{'surum':<30}{'islem':>7}{'WR':>8}{'PF':>8}{'net':>12}{'acik':>6}")
    satirlar = []
    for ad, sinif in (("v1 kbot (EMA+hacim)", MotorV1),
                      ("v2 kbot2 (rejim+komite)", MotorV2),
                      ("v3 kbot3 (kanit esikleri)", MotorV3)):
        o = kos(sinif, Taban(), seriler)
        satirlar.append({"surum": ad, **o})
        print(f"  {ad:<28}{o['islem']:>7}{o['kazanma_orani']*100:>7.1f}%"
              f"{o['kar_faktoru']:>8.2f}{o['realize_usd']:>+11.2f}${o['acik_pozisyon']:>6}")

    etiket = a.etiket or time.strftime("canli_%Y%m%d_%H%M%S")
    d = Path("runs") / etiket
    d.mkdir(parents=True, exist_ok=True)
    (d / "ozet.json").write_text(json.dumps(
        {"kaynak": kaynak, "borsa": a.borsa, "bar": bar,
         "semboller": list(seriler)[:60], "sonuclar": satirlar},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nyazildi: {d / 'ozet.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
