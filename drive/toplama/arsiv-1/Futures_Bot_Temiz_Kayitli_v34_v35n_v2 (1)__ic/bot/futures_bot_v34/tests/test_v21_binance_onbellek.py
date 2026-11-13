"""
v21 — Binance dakika önbelleği (REST ön-dolgusu) testleri.

NEDEN: v20'de kalan eksik #2 — bağlam filtresi 33 tamamlanmış dakika istiyor,
OKX'te REST ön-dolgusu vardı ama Binance'te yoktu. 15 dk'lık koşularda Binance
evreni tamamen "baglam_isinma" kapısında eleniyordu (528 eleme).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from scanner.ws_scanner import (
    BinanceRestAkisi,
    SpikeDetector,
    binance_dakika_onbellegi,
)


# ---------------------------------------------------------------------------
# Sahte aiohttp oturumu
# ---------------------------------------------------------------------------
class _SahteYanit:
    def __init__(self, govde):
        self._govde = govde

    async def json(self):
        return self._govde

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class SahteOturum:
    def __init__(self, veri: dict[str, object]):
        self.veri = veri
        self.cagrilar: list[dict] = []

    def get(self, url, params=None, timeout=None):
        sym = (params or {}).get("symbol")
        self.cagrilar.append({"url": url, "params": params or {}})
        if sym in self.veri:
            return _SahteYanit(self.veri[sym])
        return _SahteYanit({"code": -1121, "msg": "Invalid symbol."})


def _klines(simdi_ms: int, adet: int = 45, kapanis: float = 100.0,
            hacim: float = 1_000_000.0):
    """`adet` mumluk klines listesi üretir; SON satır cari (tamamlanmamış) dakika."""
    cari_mid = simdi_ms // 60_000
    satirlar = []
    for i in range(adet):
        mid = cari_mid - (adet - 1 - i)
        open_ts = mid * 60_000
        close_ts = open_ts + 59_999
        satirlar.append([
            open_ts, f"{kapanis}", f"{kapanis}", f"{kapanis}", f"{kapanis}",
            "10.0", close_ts, f"{hacim}", 42, "0", "0", "0",
        ])
    return satirlar


# ---------------------------------------------------------------------------
# 1) Ön-dolgu: yalnızca TAMAMLANMIŞ dakikalar geçmişe yazılır
# ---------------------------------------------------------------------------
def test_onbellek_yalnizca_tamamlanmis_dakikalari_yazar():
    simdi = int(time.time() * 1000)
    oturum = SahteOturum({"BTCUSDT": _klines(simdi, adet=45)})
    detektor = SpikeDetector(baglam_aktif=True)

    dolu = asyncio.run(
        binance_dakika_onbellegi(oturum, detektor, {"BTCUSDT"}, bekleme=0))

    assert dolu == 1
    d = detektor.durum("binance", "BTCUSDT")
    assert len(d.dakika_kapanis) == 44          # 45 - cari dakika
    assert len(d.dakika_hacim) == 44
    # Canli dakika ilk canli hacim tikinde baslatilir.
    assert d.dakika_id == -1
    assert d.dakika_kapanis[-1][0] < simdi // 60_000


# ---------------------------------------------------------------------------
# 2) ASIL DÜZELTME: ön-dolgu sonrası bağlam ANINDA hazır (35 dk bekleme yok)
# ---------------------------------------------------------------------------
def test_onbellek_baglami_aninda_hazir_yapar():
    simdi = int(time.time() * 1000)
    detektor = SpikeDetector(baglam_aktif=True)
    d = detektor.durum("binance", "ETHUSDT")
    # Ön-dolgu ÖNCESİ: 35 dakikalık ısınma şartı sağlanmaz
    assert detektor.baglam_guncelle(d, simdi) is False

    oturum = SahteOturum({"ETHUSDT": _klines(simdi, adet=45)})
    asyncio.run(binance_dakika_onbellegi(oturum, detektor, {"ETHUSDT"}, bekleme=0))

    # Ön-dolgu SONRASI: ilk tikte bağlam kapısı çalışır
    assert detektor.baglam_guncelle(d, simdi) is True
    # vratio3 (son 3 TAM dakika / önceki 30 dk medyanı) ön-dolgudan hemen hesaplanır;
    # vratio cari (yarım) dakikanın hacmini beklediği için ilk tikte 0 olabilir.
    assert d.baglam_vratio3 > 0
    assert d.baglam_hazir is True


# ---------------------------------------------------------------------------
# 3) Ban / geçersiz sembol yanıtı (dict) sayılmaz, çökmez
# ---------------------------------------------------------------------------
def test_onbellek_hatali_yaniti_saymaz():
    simdi = int(time.time() * 1000)
    oturum = SahteOturum({
        "AAAUSDT": _klines(simdi, adet=45),
        "BBBUSDT": {"code": -1003, "msg": "Way too many requests"},
        "CCCUSDT": [],
    })
    detektor = SpikeDetector(baglam_aktif=True)
    dolu = asyncio.run(binance_dakika_onbellegi(
        oturum, detektor, {"AAAUSDT", "BBBUSDT", "CCCUSDT"}, bekleme=0))
    assert dolu == 1
    assert len(detektor.durum("binance", "AAAUSDT").dakika_kapanis) == 44
    assert len(detektor.durum("binance", "BBBUSDT").dakika_kapanis) == 0


# ---------------------------------------------------------------------------
# 4) Sıfır/eksi fiyatlı bozuk satırlar atlanır
# ---------------------------------------------------------------------------
def test_onbellek_bozuk_satirlari_atlar():
    simdi = int(time.time() * 1000)
    satirlar = _klines(simdi, adet=45)
    satirlar[3][4] = "0.0"                      # kapanış 0 -> atla
    satirlar[4] = ["bozuk"]                     # eksik alan  -> atla
    oturum = SahteOturum({"XUSDT": satirlar})
    detektor = SpikeDetector(baglam_aktif=True)
    dolu = asyncio.run(binance_dakika_onbellegi(oturum, detektor, {"XUSDT"}, bekleme=0))
    assert dolu == 1
    d = detektor.durum("binance", "XUSDT")
    assert len(d.dakika_kapanis) == 42          # 44 - 2 bozuk satır
    assert all(k > 0 for _, k in d.dakika_kapanis)


# ---------------------------------------------------------------------------
# 5) Akış sınıfı bayrağı taşır ve varsayılan AÇIK
# ---------------------------------------------------------------------------
def test_rest_akisi_onbellek_bayragi():
    detektor = SpikeDetector()
    akis = BinanceRestAkisi(detektor, sinyal_cb=lambda s: None, fiyat_cb=None)
    assert akis.onbellek is True
    assert akis.onbellek_dolu == 0
    kapali = BinanceRestAkisi(detektor, sinyal_cb=lambda s: None, onbellek=False)
    assert kapali.onbellek is False


# ---------------------------------------------------------------------------
# 6) Genişlik aday gözlemi: son kapıya gelen adayın genişlik oranı kaydedilir
# ---------------------------------------------------------------------------
def test_genislik_aday_orani_kaydedilir():
    d = SpikeDetector(baglam_aktif=False, min_genislik_oran=0.02)
    d._genislik_esik_pct = 0.5
    d.genislik_oran = 0.031
    durum = d.durum("okx", "AAA-USDT-SWAP")
    durum.ret_2s = 0.6
    durum.hiz_uzun = 1.0
    durum.rvol = 50.0
    durum.hiz_kisa = 100_000.0
    durum.son_fiyat_ts = 1_000_000
    durum.son_hacim_ts = 1_000_000
    simdi = 1_000_500
    sonuc = d._degerlendir(durum, simdi)
    assert d.genislik_aday == [0.031]
    # 0.031 >= 0.02 -> kapı geçildi, sinyal üretildi; kritik olan oranın kaydı.
    assert sonuc is not None
    assert d.kapi_sayaclari.get("genislik") is None
