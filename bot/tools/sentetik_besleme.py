# -*- coding: utf-8 -*-
"""sentetik_besleme.py — OKX/Binance erişimi olmayan ortamlar için deterministik piyasa üreteci.

NEDEN VAR
---------
Bu depo, canlı borsa WebSocket'ine çıkışı olmayan (yalnızca GitHub/pypi açık) bir
sandbox'ta da çalışabilmelidir. Gerçek emir/tick olmadan 6 botun **davranışını**
(hangi kural ne zaman tetikleniyor,BE kâr koruması kaç işlemde zarara dönüyor,
kasa kaç pozisyonda 12x kaldıraca çıkıyor) ölçebilmek için piyasa burada üretilir.

ÜRETİLEN VERİ GERÇEK PİYASA DEĞİLDİR. Bu besleme ile alınan sonuç yalnızca
"motorun mantığı doğru çalışıyor mu" sorusunu yanıtlar; "bu bot para kazanır mı"
sorusunu YANITLAMAZ. Kenar (edge) ölçümü için gerçek tick arşivi gerekir
(bkz. docs/05-test-protokolu.md).

ÜRETİM MODELİ
-------------
Sembol başına:
  * işlem yoğunluğu  lambda ~ lognormal (likit semboller daha yoğun)
  * işlem büyüklüğü  lognormal (medyan ~800 $)
  * fiyat: OU-benzeri rastgele yürüyüş + ara sıra "patlama rejimi"
  * patlama rejimi: hacim x(6..25), 12 sn'de %0.4-2.5 yönlü hareket,
    alıcı/satıcı baskısı 0.5-0.9 -> motorların sinyal eşiklerini gerçekten aşar
  * patlama bitişinde hacim çöküşü (HACIM_COKUSU sinyalleri için)

Çıktı tick sözlüğü, canlı koşucunun (canli_6bot.py) ürettiği şemanın aynısıdır:
  {exchange, symbol, price, delta_usd, buy_usd, ts, quote_vol_24h, pct_24h}
yani motor kodu **hiç değiştirilmeden** beslenir.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class SembolParam:
    ad: str
    px0: float
    hacim24_usd: float
    islem_hizi: float          # işlem/sn
    boyut_mu: float            # lognormal log-medyanı (USD)
    boyut_sigma: float
    volatilite: float          # bucket başına log-getiri std
    # patlama rejimi durumu
    kalan: int = 0
    hacim_mult: float = 1.0
    drift: float = 0.0
    bias: float = 0.0
    yon: int = 1


@dataclass
class PiyasaAyari:
    sure_sn: float = 3600.0
    bucket_sn: float = 0.5
    seed: int = 20261113
    likit_sembol_sayisi: int = 30
    patlama_olasilik: float = 0.000015  # bucket başına, sembol başına (~55 patlama/saat)
    patlama_sure_araligi: tuple = (20, 70)      # bucket (10-35 sn)
    patlama_hacim_araligi: tuple = (6.0, 25.0)
    patlama_drift_araligi: tuple = (0.00025, 0.0011)  # bucket başına


def _fiyat_uret(rng: random.Random) -> float:
    """Log-düzgün fiyat: 0.0001 .. 60000 (kripto + tokenize hisse evreni gibi)."""
    return round(math.exp(rng.uniform(math.log(0.0001), math.log(60000.0))), 8)


class SentetikPiyasa:
    """Aynı seed + aynı süre -> birebir aynı tick dizisi (tekrarlanabilir test)."""

    def __init__(self, semboller: list[str], ayar: PiyasaAyari | None = None) -> None:
        self.ayar = ayar or PiyasaAyari()
        self.rng = random.Random(self.ayar.seed)
        self.parametreler: list[SembolParam] = []
        for i, ad in enumerate(semboller):
            likit = i < self.ayar.likit_sembol_sayisi
            hiz = math.exp(self.rng.gauss(-0.2, 1.0)) * (4.0 if likit else 1.0)
            self.parametreler.append(SembolParam(
                ad=ad,
                px0=_fiyat_uret(self.rng),
                hacim24_usd=round(math.exp(self.rng.uniform(math.log(30_000), math.log(4e9))), 0),
                islem_hizi=max(0.05, hiz),
                boyut_mu=self.rng.uniform(5.6, 7.4),
                boyut_sigma=self.rng.uniform(0.8, 1.6),
                volatilite=self.rng.uniform(0.00008, 0.00060) * (1.2 if likit else 1.0),
            ))
        self.adim = 0

    # ------------------------------------------------------------------ iç
    def _patlama_baslat(self, p: SembolParam) -> None:
        a = self.ayar
        p.kalan = self.rng.randint(*a.patlama_sure_araligi)
        p.hacim_mult = self.rng.uniform(*a.patlama_hacim_araligi)
        p.drift = self.rng.uniform(*a.patlama_drift_araligi)
        p.yon = 1 if self.rng.random() < 0.5 else -1
        p.bias = self.rng.uniform(0.10, 0.55) * p.yon

    def _bucket(self, p: SembolParam, ts: float) -> dict | None:
        rng, dt = self.rng, self.ayar.bucket_sn
        if p.kalan > 0:
            p.kalan -= 1
            if p.kalan == 0:
                p.hacim_mult, p.drift, p.bias = 1.0, 0.0, 0.0
        elif rng.random() < self.ayar.patlama_olasilik:
            self._patlama_baslat(p)

        yogunluk = p.islem_hizi * dt * (p.hacim_mult if p.kalan > 0 else 1.0)
        adet = 0
        # Poisson(yogunluk) — Knuth, küçük lambda için yeterli
        L, k, q = math.exp(-yogunluk), 0, 1.0
        while True:
            q *= rng.random()
            if q <= L:
                break
            k += 1
            if k > 3000:
                break
        adet = k
        if adet == 0:
            return None

        hacim, alis = 0.0, 0.0
        for _ in range(adet):
            b = math.exp(rng.gauss(p.boyut_mu, p.boyut_sigma))
            hacim += b
            alis_olasilik = min(0.92, max(0.08, 0.5 + p.bias * 0.5))
            if rng.random() < alis_olasilik:
                alis += b

        # fiyat: OU-benzeri + patlama drifti + mikro gürültü
        sok = rng.gauss(0.0, p.volatilite) + p.drift * p.yon * (p.kalan > 0)
        p.px0 *= math.exp(sok)
        if p.px0 <= 1e-12:
            p.px0 = 1e-12

        return {
            "exchange": "sentetik",
            "symbol": p.ad,
            "price": p.px0,
            "delta_usd": round(hacim, 4),
            "buy_usd": round(alis, 4),
            "ts": ts,
            "quote_vol_24h": p.hacim24_usd,
            "pct_24h": 0.0,
        }

    # ------------------------------------------------------------------ dışa
    def ticks(self, ts: float) -> list[dict]:
        self.adim += 1
        cikti = []
        for p in self.parametreler:
            t = self._bucket(p, ts)
            if t is not None:
                cikti.append(t)
        return cikti

    @property
    def fiyatlar(self) -> dict[str, float]:
        return {p.ad: p.px0 for p in self.parametreler}


def evren_yukle(yol: str, adet: int = 510) -> list[str]:
    """Kayıtlı durum JSON'undan gerçek sembol listesini al (isimler gerçek, fiyatlar değil)."""
    import json
    import os
    if not os.path.exists(yol):
        raise FileNotFoundError(f"evren dosyasi yok: {yol}")
    with open(yol, encoding="utf-8") as fh:
        d = json.load(fh)
    semboller = list(d.get("semboller") or [])
    if not semboller:
        raise ValueError(f"{yol} icinde 'semboller' yok")
    return semboller[:adet]


if __name__ == "__main__":  # küçük duman testi
    import time
    p = SentetikPiyasa([f"TEST{i}-USDT-SWAP" for i in range(200)])
    t0 = time.time()
    toplam = 0
    for i in range(7200):
        toplam += len(p.ticks(1_800_000_000 + i * 0.5))
    print(f"7200 bucket (60 dk) | tick satiri: {toplam} | {time.time()-t0:.1f} sn")
