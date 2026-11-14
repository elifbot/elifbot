"""Çoklu sembol simülasyon motoru (1 pozisyon/sembol, pozisyon limiti yok, teminat fiziği var).

Kurallar (kurallar.py):
  * giriş: sinyal barı i kapanınca, i+1 barının açılışında
  * notional 500 $, teminat 50 $, gidiş-dönüş taker 0.50 $
  * stop: fiyat mesafesi %1.90 (net −10 $). Bar içi düşük/yüksek ile tetiklenir; boşlukta açılışta kapanır.
  * kâr kilidi: unrealized ≥ KAR_KILIDI_USD olunca stop başabaş+komisyona çekilir
  * zaman stopu: MAX_BAR sonra kapanış
  * serbest teminat < 50 $ ise yeni giriş yok (borsa fiziği)
Varsayım: slipaj parametresi 0 (ölçülmemiş). Sonuçlar bu varsayımla yorumlanmalıdır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import indikator as ind
from .kurallar import GIDIS_DONUS_KOMISYON_USD, NOTIONAL_USD, STOP_FIYAT_ORANI, TAKER_ORAN, KASA_USD, TEMINAT_USD
from .veri import Seri

KAR_KILIDI_USD = 4.5
MAX_BAR = 48          # 15 dk barda 12 saat
WARMUP = 60


@dataclass
class Islem:
    sembol: str
    yon: int
    giris_ts: float
    cikis_ts: float
    giris: float
    cikis: float
    bar_sayisi: int
    neden: str
    brut: float
    net: float
    ozellik: dict = field(default_factory=dict)


@dataclass
class Sonuc:
    islemler: list[Islem]
    kasa_son: float
    zaman_kapali: int


def _ozellik(f: dict, i: int) -> dict:
    fund = f.get("funding")
    oi = f.get("oi")
    d = {
        "adx": f["adx"][i], "bbw": f["bbw"][i],
        "rsi_sapma": None if f["rsi"][i] is None else abs(f["rsi"][i] - 50),
        "funding": None if fund is None else fund[i],
    }
    if oi is not None and i >= 1 and oi[i] is not None and oi[i - 1]:
        d["oi_degisim"] = oi[i] / oi[i - 1] - 1
    return d


def hazirla(seri: Seri) -> dict:
    b = seri.bars
    c = [x.c for x in b]
    h = [x.h for x in b]
    l = [x.l for x in b]
    o = [x.o for x in b]
    f = {
        "ts": [x.ts for x in b], "c": c, "h": h, "l": l, "o": o,
        "e9": ind.ema(c, 9), "e21": ind.ema(c, 21), "rsi": ind.rsi(c, 14),
        "adx": ind.adx(h, l, c, 14), "bbw": ind.bb_genislik(c, 20),
        "funding": [x.funding for x in b] if any(x.funding is not None for x in b) else None,
        "oi": [x.oi for x in b] if any(x.oi is not None for x in b) else None,
    }
    return f


def simule(seriler: list[Seri], strateji, kasa0: float = KASA_USD, kar_kilidi: float = KAR_KILIDI_USD,
           max_bar: int = MAX_BAR) -> Sonuc:
    fs = {s.sembol: hazirla(s) for s in seriler}
    # ts → sembol → indeks
    idx = {s: {t: k for k, t in enumerate(fs[s]["ts"])} for s in fs}
    zaman = sorted(set(t for s in fs for t in fs[s]["ts"]))
    acik: dict[str, dict] = {}
    islemler: list[Islem] = []
    kasa = kasa0
    kapali_zaman = 0
    for t in zaman:
        # 1) açık pozisyonları yönet
        for sem in list(acik):
            p = acik[sem]
            f = fs[sem]
            if t not in idx[sem]:
                continue
            j = idx[sem][t]
            if j < p["gi"]:
                continue
            y = p["yon"]
            stop = p["stop"]
            # stop kontrolü (boşlukta açılış fiyatı)
            if (y == 1 and f["l"][j] <= stop) or (y == -1 and f["h"][j] >= stop):
                cikis = min(f["o"][j], stop) if y == 1 else max(f["o"][j], stop)
                neden = "stop" if p["stop"] == p["ilk_stop"] else "kar_kilidi"
                kasa = _kapat(islemler, sem, p, t, cikis, j, neden, kasa)
                kapali_zaman += 1
                del acik[sem]
                continue
            # kâr kilidi güncelle (bar yüksek/düşüğü ile)
            ext = f["h"][j] if y == 1 else f["l"][j]
            p["ext"] = max(p["ext"], ext) if y == 1 else min(p["ext"], ext)
            unreal = (p["ext"] / p["giris"] - 1) * y * NOTIONAL_USD
            if unreal >= kar_kilidi and p["stop"] == p["ilk_stop"]:
                p["stop"] = p["giris"] * (1 + y * TAKER_ORAN * 2)
            if j - p["gi"] >= max_bar:
                kasa = _kapat(islemler, sem, p, t, f["c"][j], j, "zaman", kasa)
                kapali_zaman += 1
                del acik[sem]
        # 2) yeni girişler (sinyal bu barın kapanışında; giriş bir sonraki barın açılışı)
        for sem in fs:
            if sem in acik or t not in idx[sem]:
                continue
            f = fs[sem]
            i = idx[sem][t]
            if i < WARMUP or i + 1 >= len(f["c"]):
                continue
            if kasa - TEMINAT_USD * (len(acik) + 1) < 0:
                continue  # serbest teminat yetmez
            s = strateji(f, i)
            if s == 0:
                continue
            gi = i + 1
            giris = f["o"][gi]
            ilk = giris * (1 - s * STOP_FIYAT_ORANI)
            acik[sem] = {"yon": s, "giris": giris, "gi": gi, "giris_ts": f["ts"][gi],
                         "stop": ilk, "ilk_stop": ilk, "ext": giris, "ozellik": _ozellik(f, i)}
    # açık kalanları son kapanışla kapat (raporlama için, "sonda_kapat")
    for sem in list(acik):
        f = fs[sem]
        p = acik[sem]
        j = len(f["c"]) - 1
        kasa = _kapat(islemler, sem, p, f["ts"][j], f["c"][j], j, "veri_sonu", kasa)
    return Sonuc(islemler=islemler, kasa_son=kasa, zaman_kapali=kapali_zaman)


def _kapat(islemler, sem, p, t, cikis, j, neden, kasa) -> float:
    y = p["yon"]
    brut = (cikis / p["giris"] - 1) * y * NOTIONAL_USD
    net = brut - GIDIS_DONUS_KOMISYON_USD
    islemler.append(Islem(
        sembol=sem, yon=y, giris_ts=p["giris_ts"], cikis_ts=t, giris=p["giris"], cikis=cikis,
        bar_sayisi=j - p["gi"], neden=neden, brut=brut, net=net, ozellik=p["ozellik"]))
    return kasa + net
