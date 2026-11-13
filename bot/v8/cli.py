# -*- coding: utf-8 -*-
"""cli.py — v8 komut satırı.

    python3 -m bot.v8.cli paper --dakika 60 --sembol 120 --seed 7
    python3 -m bot.v8.cli paper --dakika 10 --borsa okx
    python3 -m bot.v8.cli canli --borsa binance --sembol 80      # KİLİTLİ (env gerekir)
    python3 -m bot.v8.cli kurallar                                # kural/risk tablosu

`canli` modu yalnızca `ACARBOT_CANLI_ONAY=EVET-RISKI-ANLIYORUM` ortam değişkeni ve
geçerli API anahtarları varsa çalışır. Varsayılan davranış: hiçbir yere emir gitmez.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

from .broker import SimuleBorsa
from .config import KasaKurallari, MotorAyarlari, RiskProfili
from .engine import Motor
from .feed import SentetikBesleme
from .sizing import guvenli_max_pozisyon, stop_mesafesi_pct, tasfiye_mesafesi_pct
from .types import Enstruman, Tick

KOK = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ evren
def sentetik_evren(semboller: list[str], fiyatlar: dict[str, float]) -> dict[str, Enstruman]:
    cikti = {}
    for s in semboller:
        px = fiyatlar.get(s, 1.0)
        # fiyat ölçeğine göre gerçekçi adımlar (gerçek borsada da böyle)
        if px >= 1000:
            adim, miktar = 0.1, 0.001
        elif px >= 10:
            adim, miktar = 0.01, 0.01
        elif px >= 0.1:
            adim, miktar = 0.0001, 1.0
        else:
            adim, miktar = 0.000001, 100.0
        baz = s.split("-")[0].replace("USDT", "")
        cikti[s] = Enstruman(borsa="sentetik", sembol=s, baz=baz, fiyat_adimi=adim,
                             miktar_adimi=miktar, min_miktar=miktar, min_notional_usd=5.0,
                             kontrat_carpani=1.0, max_kaldirac=125)
    return cikti


def _evren_isimleri(adet: int) -> list[str]:
    yol = KOK / "bot" / "acarbot_6bot" / "loglar" / "durum_6bot_ILK25DK.json"
    try:
        with open(yol, encoding="utf-8") as fh:
            d = json.load(fh)
        isimler = list(d.get("semboller") or [])
        if isimler:
            return isimler[:adet]
    except Exception:
        pass
    return [f"SYM{i}-USDT-SWAP" for i in range(adet)]


# ------------------------------------------------------------------ paper
def paper_kosu(dakika: float, sembol: int, seed: int, borsa: str, etiket: str) -> dict:
    kurallar = KasaKurallari()
    profil = RiskProfili(kurallar=kurallar, motor=MotorAyarlari())
    isimler = _evren_isimleri(sembol)

    sim = SimuleBorsa(ad=borsa, kurallar=kurallar, kasa_usd=kurallar.baslangic_kasa_usd)
    besleme = SentetikBesleme(isimler, seed=seed, bucket_sn=0.5, baslangic_ts=1_791_000_000.0)
    sim.enstrumanlar = sentetik_evren(isimler, besleme.fiyatlar())
    motor = Motor(borsa=sim, profil=profil)

    adim = int(dakika * 60 / 0.5)
    egri = []
    t0 = time.perf_counter()
    for i in range(adim):
        ticks: list[Tick] = besleme.sonraki()
        for t in ticks:
            motor.tick(t)
        if i % 60 == 0:
            egri.append({"dk": round(i * 0.5 / 60, 2),
                         "kasa": round(sim.kasa_usd + sim.acik_pnl(), 2),
                         "acik": len(sim.pozisyonlar)})
    rapor = motor.ozet()
    rapor.update({
        "etiket": etiket, "mod": "paper", "borsa": borsa, "dakika": dakika,
        "seed": seed, "sembol_sayisi": len(isimler),
        "duvar_suresi_sn": round(time.perf_counter() - t0, 1),
        "kasa_egrisi": egri,
        "en_iyi_tek_islem": max((k.net_pnl_usd for k in motor.kapananlar), default=0.0),
        "en_kotu_tek_islem": min((k.net_pnl_usd for k in motor.kapananlar), default=0.0),
        "islemler": [k.__dict__ | {"yon": k.yon} for k in motor.kapananlar[-200:]],
        "kural": {
            "teminat": kurallar.teminat_per_pozisyon_usd,
            "kaldirac": kurallar.kaldirac,
            "notional": kurallar.notional_per_pozisyon_usd,
            "stop_usd": kurallar.stop_net_usd,
            "stop_mesafesi_pct": round(100 * stop_mesafesi_pct(kurallar), 3),
            "marjin": kurallar.marjin_modu,
            "max_pozisyon_kurali": kurallar.max_pozisyon,
        },
    })
    return rapor


# ------------------------------------------------------------------ kurallar
def kural_tablosu() -> str:
    k = KasaKurallari()
    satir = [
        "KURAL (kullanıcı)                       DEĞER",
        "-" * 68,
        f"Başlangıç kasası                        {k.baslangic_kasa_usd:>10.2f} $",
        f"Pozisyon teminatı                       {k.teminat_per_pozisyon_usd:>10.2f} $",
        f"Kaldıraç                                {k.kaldirac:>10d} x",
        f"Pozisyon notional                       {k.notional_per_pozisyon_usd:>10.2f} $",
        f"Marjin modu                             {k.marjin_modu:>10}",
        f"Pozisyon limiti                         {'YOK':>10} (kural)",
        f"Zarar kes (net)                         {-k.stop_net_usd:>10.2f} $",
        "",
        "TÜRETİLMİŞ (aritmetik)",
        "-" * 68,
        f"Gidiş-dönüş taker komisyon              {k.gidis_donus_komisyon_usd:>10.2f} $",
        f"Stop fiyat mesafesi                     {100*stop_mesafesi_pct(k):>9.2f} %",
        f"Başabaş fiyat mesafesi                  {100*k.basabas_fiyat_mesafesi:>9.2f} %",
        f"Kasanın kaldıraç kapasitesi             {k.max_es_zamanli_pozisyon(k.baslangic_kasa_usd):>10d} pozisyon",
        f"Güvenli eşzamanlı pozisyon (%10 DD)     {guvenli_max_pozisyon(k.baslangic_kasa_usd, k):>10d} pozisyon",
        "",
        "CROSS TASFİYE MESAFESİ (bakım marjı %0.5)",
        "-" * 68,
    ]
    for n in (1, 5, 10, 20, 40, 100, 170):
        mesafe = tasfiye_mesafesi_pct(k.baslangic_kasa_usd, n, k)
        satir.append(f"{n:>3} eşzamanlı pozisyon -> %{100*mesafe:>6.2f} ters harekette tasfiye")
    satir.append("")
    satir.append("Not: 'sınırsız pozisyon' kuralı emir sayısını sınırlamaz; 20 pozisyondan")
    satir.append("sonra kasa matematiksel olarak tek bir piyasa hareketine rehin olur.")
    return "\n".join(satir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="v8", description="ACARBOT v8 (kural: 1000$/50$/10x/cross/-10$)")
    alt = ap.add_subparsers(dest="komut", required=True)

    p = alt.add_parser("paper", help="simülasyon borsasında koş")
    p.add_argument("--dakika", type=float, default=60.0)
    p.add_argument("--sembol", type=int, default=120)
    p.add_argument("--seed", type=int, default=20261113)
    p.add_argument("--borsa", default="binance")
    p.add_argument("--etiket", default="")
    p.add_argument("--json", default="")

    c = alt.add_parser("canli", help="gerçek borsa (KİLİTLİ)")
    c.add_argument("--borsa", default="binance")
    c.add_argument("--sembol", type=int, default=80)

    alt.add_parser("kurallar", help="kural ve türetilmiş risk tablosu")

    a = ap.parse_args(argv)

    if a.komut == "kurallar":
        print(kural_tablosu())
        return 0

    if a.komut == "canli":
        from .config import Guvenlik
        g = Guvenlik()
        if not g.canli_acik_mi():
            print(f"CANLI MOD KİLİTLİ.\n"
                  f"Açmak için: export {g.canli_izni_env}={g.canli_izni_degeri}\n"
                  f"ve borsa API anahtarlarını .env dosyasına koy.\n"
                  f"Bu kilit bilinçli: yanlışlıkla canlı emir gönderilmesini engeller.")
            return 2
        print("Canlı mod bu sürümde adaptör iskeletiyle sınırlıdır; "
              "önce paper modda 30 gün kesintisiz koşu gerekir (docs/06-yol-haritasi.md).")
        return 3

    etiket = a.etiket or f"v8_paper_{a.borsa}_{int(a.dakika)}dk"
    rapor = paper_kosu(a.dakika, a.sembol, a.seed, a.borsa, etiket)
    cikti = Path(a.json) if a.json else KOK / "runs" / etiket / "v8_rapor.json"
    cikti.parent.mkdir(parents=True, exist_ok=True)
    cikti.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"v8 paper · {a.borsa} · {a.sembol} sembol · {a.dakika:.0f} dk · seed {a.seed}")
    print("-" * 72)
    for k, v in rapor.items():
        if k in ("islemler", "kasa_egrisi", "kural", "red", "sinyal"):
            continue
        print(f"  {k:<24} {v}")
    print(f"  {'red':<24} {json.dumps(rapor['red'], ensure_ascii=False)}")
    print(f"  {'sinyal':<24} {json.dumps(rapor['sinyal'], ensure_ascii=False)}")
    print(f"\nrapor: {cikti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
