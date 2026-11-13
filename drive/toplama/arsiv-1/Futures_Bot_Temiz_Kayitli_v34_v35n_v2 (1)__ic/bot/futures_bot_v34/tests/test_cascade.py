"""
test_cascade.py — cascade (tasfiye zinciri) filtresi testleri.

Gece bulgusu: aynı 60 saniyede çok sayıda sembol sinyal veriyorsa bu bir
zincirleme tasfiyedir ve fade kenarı çok güçlenir. Bota eklenen kapı
şunları garanti etmeli:
  1. Eşik altında işlem açılmaz
  2. Eşiğe ulaşınca açılır
  3. Pencere dışına düşen sinyaller sayımdan çıkar
  4. Reddedilen sinyaller de sayılır (zinciri onlar da doğrular)
"""
from __future__ import annotations

import pytest

from scanner.ws_scanner import Sinyal

# ws_bot'u import etmek aiohttp ister; yoksa test atlanır
try:
    import ws_bot
except Exception:                                     # pragma: no cover
    ws_bot = None

pytestmark = pytest.mark.skipif(ws_bot is None, reason="ws_bot import edilemedi")


def _bot(esik: int, tmp_path):
    """Portföyü geçici dizinde olan, ağa çıkmayan bir Bot."""
    det = ws_bot.SpikeDetector(ret_min_pct=0.0, rvol_min=0.0, min_hacim_usd=0,
                               baglam_aktif=False)
    b = ws_bot.Bot(det, sure_dk=0, binance_mod="rest", sadece_kayit=False,
                   strateji="fade", tp=99.0, sl=2.0, tut_dk=5.0,
                   cascade_esik=esik)
    return b


def _sinyal(ts: int, sembol: str = "X") -> Sinyal:
    return Sinyal(ts_ms=ts, exchange="okx", symbol=sembol, yon="LONG",
                  etiket="ANI_YUKSELIS", fiyat=100.0, ret_pct=0.5, rvol=2.0,
                  hacim_usd=10_000.0, gecen_ms=2000)


# ----------------------------------------------------------------------
def test_esik_altinda_islem_yok(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b = _bot(3, tmp_path)
    b.sinyal_gecmisi = []
    # 1. ve 2. sinyal reddedilmeli
    for i in range(2):
        b.sinyal_gecmisi = [t for t in b.sinyal_gecmisi if 0 <= i * 1000 - t <= 60_000]
        b.sinyal_gecmisi.append(i * 1000)
        assert len(b.sinyal_gecmisi) < 3
    assert b.acilan == 0


def test_sayac_pencere_disini_atar(tmp_path):
    b = _bot(2, tmp_path)
    b.sinyal_gecmisi = [0, 1_000, 2_000]
    simdi = 70_000                        # hepsi pencerenin dışında
    b.sinyal_gecmisi = [t for t in b.sinyal_gecmisi if simdi - t <= 60_000]
    assert b.sinyal_gecmisi == []


def test_pencere_ici_sayilir(tmp_path):
    b = _bot(2, tmp_path)
    b.sinyal_gecmisi = [10_000, 30_000]
    simdi = 65_000                        # 10.000 → 55 sn önce (içeride)
    b.sinyal_gecmisi = [t for t in b.sinyal_gecmisi if simdi - t <= 60_000]
    assert len(b.sinyal_gecmisi) == 2


def test_esik_1_ise_kapi_kapali(tmp_path):
    """cascade_esik <= 1 → filtre uygulanmaz (geri uyum)."""
    b = _bot(1, tmp_path)
    b.sinyal_gecmisi = [1]
    assert b.cascade_esik == 1
    # kapı koşulu: cascade_esik > 1 and len < esik
    aktif = b.cascade_esik > 1 and len(b.sinyal_gecmisi) < b.cascade_esik
    assert aktif is False


def test_varsayilan_esik_kapali():
    """28.10: cascade tamamen kapatıldı (0).

    Neden: Aşama 1 penceresi 2 sn -> 60 sn, rvol eşiği 1 -> 5 oldu. Artık
    sinyalin kendisi "1 dakikalık hacim patlamalı gerçek hareket".
    7 günlük taramada cascade 0/2/3/4 aynı sonucu verdi (sinyaller zaten
    seyrek); ek katman sadece işlem sayısını kısıyordu.
    """
    assert ws_bot.CASCADE_ESIK == 0
    assert ws_bot.CASCADE_PENCERE_MS == 60_000


def test_esik_3_kapi_acilir(tmp_path):
    b = _bot(3, tmp_path)
    b.sinyal_gecmisi = [1, 2, 3]
    assert len(b.sinyal_gecmisi) >= b.cascade_esik
