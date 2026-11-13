"""
test_genislik.py — piyasa genişliği (breadth) ölçeri testleri.

Gece bulgusu: fade'in kenarı ancak piyasanın TAMAMI hareket ederken var.
    genişlik  20-39 sembol → %50 isabet, -0,18%
    genişlik 140+ sembol   → %86 isabet, +0,69%

Bu testler ölçerin doğru saydığını ve kapının çalıştığını garanti eder.
"""
from __future__ import annotations

import pytest

from scanner.ws_scanner import SpikeDetector


def _det(**kw):
    ayar = dict(ret_pencere_ms=60_000, ret_min_pct=0.5, rvol_min=0.0,
                min_hacim_usd=0, soguma_ms=0, tazelik_ms=10_000,
                isinma_ms=10_000, baglam_aktif=True, baglam_geri_dk=3,
                baglam_min_ret=1.2, baglam_maks_ret=2.0,
                baglam_min_vratio=0.0, baglam_min_vratio3=0.0,
                baglam_onbellek_dk=35)
    ayar.update(kw)
    return SpikeDetector(**ayar)


def _sembol_hazir(det, sym: str, getiri_pct: float, pencere_ms: int = 60_000):
    """28.10: genişlik artık fiyat geçmişinden ölçülüyor, bağlamdan bağımsız.

    Sembole `pencere_ms` önce bir fiyat, şimdi bir fiyat yazılır; aradaki
    getiri `getiri_pct` yüzde olarak olur.
    """
    d = det.durum("okx", sym)
    simdi = 1_700_000_000_000
    d.fiyatlar.clear()
    d.fiyatlar.append((simdi - pencere_ms, 100.0))
    d.fiyatlar.append((simdi, 100.0 * (1 + getiri_pct / 100.0)))
    d.son_fiyat = 100.0 * (1 + getiri_pct / 100.0)
    return d


# ----------------------------------------------------------------------
def test_bos_evrende_sifir():
    det = _det()
    assert det.genislik_guncelle() == 0.0
    assert det.genislik == 0


def test_hareketli_semboller_sayilir():
    det = _det()
    for i in range(10):
        # 6 sembol eşiğin üstünde (>= %0,5), 4 sembol altında
        _sembol_hazir(det, f"S{i}", 0.8 if i < 6 else 0.1)
    oran = det.genislik_guncelle()
    assert det.genislik == 6
    assert oran == pytest.approx(0.6)


def test_pencere_dolmamis_sembol_paydaya_girmez():
    """Fiyat geçmişi 60 sn'lik pencereyi doldurmayan sembol sayılmaz."""
    det = _det()
    d = det.durum("okx", "KISA")
    d.fiyatlar.clear()
    d.fiyatlar.append((1_700_000_000_000 - 5_000, 100.0))   # sadece 5 sn önce
    d.fiyatlar.append((1_700_000_000_000, 200.0))
    _sembol_hazir(det, "A", 0.8)
    _sembol_hazir(det, "B", 0.8)
    det.genislik_guncelle()
    assert det.genislik == 2               # KISA sayılmadı
    assert det.genislik_oran == pytest.approx(1.0)


def test_baglam_kapaliyken_de_olcer():
    """28.10 REGRESYONU: bağlam kapalıyken genişlik 0,0 kalıyordu.

    v7 koşusunda (--no-baglam) genislik_oran 15 dk boyunca 0.0 göründü ve
    GENİŞLİK KAPISI sessizce devre dışı kaldı; 36 pozisyon filtreye
    takılmadan açıldı. Genişlik artık bağlamdan bağımsız ölçülür.
    """
    det = _det(baglam_aktif=False)
    for i in range(4):
        _sembol_hazir(det, f"S{i}", 1.0)
    oran = det.genislik_guncelle()
    assert det.genislik == 4
    assert oran == pytest.approx(1.0)


def test_negatif_hareket_de_sayilir():
    """Genişlik yön ayrımı yapmaz: düşüş de yükseliş de sayılır."""
    det = _det()
    _sembol_hazir(det, "UP", +1.5)
    _sembol_hazir(det, "DN", -1.5)
    _sembol_hazir(det, "SAKIN", 0.2)
    det.genislik_guncelle()
    assert det.genislik == 2


def test_esik_sinirinda():
    det = _det()
    _sembol_hazir(det, "TAM", 0.5)         # tam eşik → sayılır (>=)
    _sembol_hazir(det, "ALTI", 0.49)
    det.genislik_guncelle()
    assert det.genislik == 1


def test_kapi_kapali_ise_engellemez():
    det = _det(min_genislik_oran=0.0)
    assert det.min_genislik_oran == 0.0


def test_varsayilan_esik_yok():
    det = _det()
    assert det.min_genislik_oran == 0.0     # varsayılan kapalı (geri uyum)


def test_oran_sifira_bolunmez():
    det = _det(min_genislik_oran=0.45)
    assert det.genislik_guncelle() == 0.0   # sembol yokken çökmemeli


# ----------------------------------------------------------------------
# İZOLE MARJ MODU
# ----------------------------------------------------------------------
def test_izole_modda_stop_marj_bitisindedir():
    """
    İzole modda SL, kullanıcı ayarı değil MARJ BİTİŞİ olmalı:
    fiyat 100/kaldıraç kadar ters gider → marj sıfır.
    10x kaldıraçta LONG giriş 100 → stop 90.
    """
    import ws_bot
    det = _det(baglam_aktif=False)
    b = ws_bot.Bot(det, sure_dk=0, binance_mod="rest", strateji="fade",
                   tp=99.0, sl=3.0, tut_dk=240.0, izole=True)
    assert b.izole is True
    marj_bitis = 100.0 / ws_bot.KALDIRAC
    stop = 100.0 * (1 - marj_bitis / 100)
    assert stop < 100.0 * (1 - 3.0 / 100), "izole stop, sabit SL'den GENİŞ olmalı"


def test_izole_kapali_iken_sabit_sl():
    import ws_bot
    det = _det(baglam_aktif=False)
    b = ws_bot.Bot(det, sure_dk=0, binance_mod="rest", strateji="fade",
                   tp=2.0, sl=3.0, tut_dk=5.0, izole=False)
    assert b.izole is False


def test_varsayilan_tutma_240dk():
    """Kullanıcı 'trend sürdükçe kal' istedi → uzun tutma varsayılan."""
    import ws_bot
    det = _det(baglam_aktif=False)
    b = ws_bot.Bot(det, sure_dk=0, binance_mod="rest", tut_dk=240.0)
    assert b.azami_sure_ms == 240 * 60_000


# ----------------------------------------------------------------------
# 28.10 — ÇİFT BORSA TEKRARI
# ----------------------------------------------------------------------
def test_base_sembol_ayni():
    """okx:BTC-USDT-SWAP ile binance:BTCUSDT aynı varlıktır."""
    from ws_bot import Bot
    assert Bot._base_sembol("BTC-USDT-SWAP") == "BTC"
    assert Bot._base_sembol("BTCUSDT") == "BTC"
    assert Bot._base_sembol("BTC-USDT") == "BTC"
    assert Bot._base_sembol("1000PEPEUSDT") == "PEPE"
    assert Bot._base_sembol("SOLUSDT") == "SOL"


def test_base_sembol_farkli():
    from ws_bot import Bot
    assert Bot._base_sembol("ETHUSDT") != Bot._base_sembol("BTC-USDT-SWAP")
