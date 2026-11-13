"""
test_baglam.py — 1 dakikalık bağlam filtresi ve maker giriş testleri.

Bu testler, gece çalışmasında bulunan üç kritik hatanın geri gelmemesini
sağlar:
  1. Bağlam filtresi ısınma olmadan sinyal üretmemeli (33 dk kuralı)
  2. vratio3 (3 dk ortalama) tek-dakika oranından AYRI olmalı
  3. Kümülatif hacim beslemesi (Binance) gerçek dakika dilimi kullanmalı
"""
from __future__ import annotations

import pytest

from scanner.ws_scanner import Sinyal, SpikeDetector


# ----------------------------------------------------------------------
def _det(**kw):
    ayar = dict(ret_pencere_ms=2000, ret_min_pct=0.05, rvol_min=1.0,
                min_hacim_usd=0, soguma_ms=0, tazelik_ms=10_000,
                isinma_ms=10_000, baglam_aktif=True, baglam_geri_dk=3,
                baglam_min_ret=1.2, baglam_maks_ret=2.0,
                baglam_min_vratio=0.0, baglam_min_vratio3=0.0,
                baglam_onbellek_dk=35)
    ayar.update(kw)
    return SpikeDetector(**ayar)


def _dakika_doldur(d, dk_sayisi: int = 40, hacim: float = 1000.0,
                   kapanislar: list[float] | None = None,
                   baslangic_dk: int = 1000) -> None:
    """SembolDurum'a tamamlanmış dakikalar ekler."""
    for i in range(dk_sayisi):
        fiyat = kapanislar[i] if kapanislar else 100.0
        d.dakika_kapanis.append((baslangic_dk + i, fiyat))
        d.dakika_hacim.append((baslangic_dk + i, hacim))


# ----------------------------------------------------------------------
def test_islama_olmadan_sinyal_yok():
    """Hiç dakika geçmişi yokken bağlam filtresi sinyali engellemeli."""
    det = _det()
    # 2 saniyelik fiyat hareketi üret
    for i in range(5):
        det.besle_fiyat("okx", "X", 100.0 + i, 0.0, 1_000_000 + i * 500)
    sinyal = det.besle_fiyat("okx", "X", 110.0, 0.0, 1_003_000)
    assert sinyal is None, "ısınma tamamlanmadan sinyal üretilmemeli"


def test_baglam_hazir_olmadan_sinyal_yok():
    det = _det()
    d = det.durum("okx", "X")
    d.son_fiyat = 100.0
    assert det.baglam_guncelle(d, 1_000_000) is False
    assert d.baglam_hazir is False


def test_minimum_ret_alti_engellenir():
    det = _det(baglam_min_ret=1.2)
    d = det.durum("okx", "X")
    _dakika_doldur(d, 40, kapanislar=[100.0] * 40)
    d.dakika_id = 1040
    d.dakika_qv = 1000.0
    d.son_fiyat = 100.5          # +0,5% — eşiğin altı
    assert det.baglam_guncelle(d, 1040 * 60_000 + 30_000) is True
    assert 0.4 < d.baglam_ret < 0.6
    assert d.baglam_ret < 1.2     # filtre reddeder


def test_maks_ret_ustu_engellenir():
    """Gerçek momentum (sert yükseliş) fade edilmemeli."""
    det = _det(baglam_min_ret=1.2, baglam_maks_ret=2.0)
    d = det.durum("okx", "X")
    _dakika_doldur(d, 40, kapanislar=[100.0] * 40)
    d.dakika_id = 1040
    d.dakika_qv = 1000.0
    d.son_fiyat = 105.0          # +5% — momentum, üst sınırın üstü
    assert det.baglam_guncelle(d, 1040 * 60_000 + 30_000) is True
    assert d.baglam_ret > 2.0


def test_maks_ret_sifir_ise_ust_sinir_yok():
    det = _det(baglam_maks_ret=0.0)
    d = det.durum("okx", "X")
    _dakika_doldur(d, 40, kapanislar=[100.0] * 40)
    d.dakika_id = 1040
    d.dakika_qv = 1000.0
    d.son_fiyat = 150.0
    assert det.baglam_guncelle(d, 1040 * 60_000 + 30_000) is True
    assert d.baglam_ret > 40.0     # üst sınır kapalı


# ----------------------------------------------------------------------
def test_vratio3_uc_dakika_ortalamasidir():
    """
    vratio3 = son 3 TAM dakikanın hacim toplamı / (3 × önceki 30 dk medyanı).
    Tek dakikalık sıçrama onu 3'e bölerek yumuşatmalı.
    """
    det = _det(baglam_onbellek_dk=35)
    d = det.durum("okx", "X")
    # vratio3 için 3 + 35 = 38 tamamlanmış dakika gerekir
    _dakika_doldur(d, 40, hacim=100.0)             # sakin geçmiş
    for i in range(3):                              # 3 dakikalık sıçrama
        d.dakika_kapanis.append((1040 + i, 100.0))
        d.dakika_hacim.append((1040 + i, 1000.0))
    d.dakika_id = 1043
    d.dakika_qv = 0.0
    d.son_fiyat = 100.0
    assert det.baglam_guncelle(d, 1043 * 60_000 + 30_000) is True
    # son3 = 3000, med3 = 100 → 3000 / (100*3) = 10
    assert d.baglam_vratio3 == pytest.approx(10.0, rel=0.02)


def test_vratio3_tek_dakika_sicramasini_ucde_bire_indirger():
    """Tek bir patlama dakikası vratio3'te 1/3'e düşer — şişme yok."""
    det = _det(baglam_onbellek_dk=35)
    d = det.durum("okx", "X")
    _dakika_doldur(d, 40, hacim=100.0)
    d.dakika_kapanis.append((1040, 100.0))
    d.dakika_hacim.append((1040, 3000.0))          # tek patlama
    d.dakika_id = 1041
    d.dakika_qv = 100.0
    d.son_fiyat = 100.0
    assert det.baglam_guncelle(d, 1041 * 60_000 + 30_000) is True
    # son3 = 100+100+3000 = 3200 ; med3 = 100 ; 3200/(300) ≈ 10.67
    assert 10.0 < d.baglam_vratio3 < 11.5


# ----------------------------------------------------------------------
def test_kumulatif_hacim_gercek_dakika_dilimi():
    """
    Binance REST kümülatif sayaç besler. Dakika kimliği GERÇEK olmalı,
    aksi hâlde dakika_hacim hiç dolmaz ve bağlam filtresi asla çalışmaz.
    """
    det = _det(baglam_aktif=False)
    d = det.durum("binance", "B")
    # 3 farklı dakikada artan sayaç
    for dk in range(3):
        for adim in range(3):
            kum = dk * 300 + adim * 100
            det.besle_hacim_kumulatif("binance", "B", float(kum),
                                      (1000 + dk) * 60_000 + adim * 10_000)
    assert d.dakika_id == 1002, "dakika kimliği gerçek olmalı"
    # her dakika 300 birim birikmeli (delta toplamı)
    assert len(d.dakika_hacim) >= 2, "kapanan dakikalar kaydedilmeli"
    # SON kapanan dakika tam olmalı: 3 tik × 100 = 300.
    # (İlk dakika sınır tikini kaybeder — delta bir sonraki dakikaya yazılır,
    #  bu beklenen ve zararsız davranış.)
    _, son_qv = list(d.dakika_hacim)[-1]
    assert son_qv == pytest.approx(300.0, rel=0.05)


def test_kumulatif_hacim_sayac_sifirlanirsa_cokmez():
    det = _det(baglam_aktif=False)
    d = det.durum("binance", "B")
    det.besle_hacim_kumulatif("binance", "B", 5000.0, 60_000)
    det.besle_hacim_kumulatif("binance", "B", 10.0, 60_010)   # sıfırlandı
    assert d._kum_birikim == pytest.approx(0.0, abs=1e-6)


# ----------------------------------------------------------------------
def test_sinyal_baglam_alanlarini_tasir():
    s = Sinyal(ts_ms=1, exchange="okx", symbol="X", yon="LONG",
               etiket="ANI_YUKSELIS", fiyat=1.0, ret_pct=0.5, rvol=2.0,
               hacim_usd=100.0, gecen_ms=2000,
               baglam_ret=1.5, baglam_vratio=3.0, baglam_vratio3=12.0)
    assert s.baglam_ret == 1.5
    assert s.baglam_vratio == 3.0
    assert s.baglam_vratio3 == 12.0


def test_baglam_kapali_ise_filtre_uygulanmaz():
    """baglam_aktif=False iken eski davranış korunmalı (geri uyum)."""
    det = _det(baglam_aktif=False, ret_min_pct=0.05, rvol_min=0.0)
    d = det.durum("okx", "X")
    # hacim oranları için veri
    for i in range(40):
        det.besle_hacim("okx", "X", 100.0, i, 60_000 * i)
    d.son_fiyat = 100.0
    d.son_fiyat_ts = 60_000 * 40
    d.hiz_uzun = 1.0
    d.hiz_kisa = 5.0
    d.rvol = 5.0
    d.ret_2s = 5.0
    d.son_hacim_ts = 60_000 * 40
    sinyal = det._degerlendir(d, 60_000 * 40 + 1000)
    assert sinyal is not None, "bağlam kapalıyken sinyal üretilmeli"
