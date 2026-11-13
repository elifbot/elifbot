import json
import time
from types import SimpleNamespace

import pytest
import ws_bot
from scanner.ws_scanner import Sinyal


@pytest.fixture
def bot_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, 'TABAN', str(tmp_path))
    monkeypatch.setattr(ws_bot, 'OLAY_CSV', str(tmp_path / 'logs' / 'olay.csv'))
    monkeypatch.setattr(ws_bot, 'DURUM_JSON', str(tmp_path / 'logs' / 'durum.json'))
    made = []
    def make(**kw):
        kw.setdefault("giris_modu", "market")  # preserve immediate-fill test setup
        b = ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0, durumlar={}),
                       min_genislik=0, **kw)
        made.append(b)
        return b
    yield make
    for b in made:
        if not b.olay_yazici.closed:
            b.olay_yazici.close()


def signal(now):
    return Sinyal(ts_ms=now, exchange='binance', symbol='BTCUSDT', yon='LONG',
                  etiket='T', fiyat=100, ret_pct=-1, rvol=6, hacim_usd=10000,
                  gecen_ms=60000)


def test_drain_teyidi_iptal_eder_ve_sonradan_giris_olmaz(bot_factory):
    b = bot_factory(teyit_aktif=True, cikis_tamamlama_dk=1)
    t = int(time.time() * 1000)
    assert b._pozisyon_ac(signal(t)) == 'bekliyor:teyit'
    b._cikis_tamamlama_baslat()
    assert not b.teyit_bekleyen and b.teyit_iptal == 1
    b._fiyat_guncelle('binance', 'BTCUSDT', 100.2, t + 1000)
    assert not b.portfoy.positions
    assert b._pozisyon_ac(signal(t), teyitli=True) == 'engel:yeni_giris_kapali'


def test_tekrar_sinyal_teyit_suresini_uzatmaz(bot_factory):
    b = bot_factory(teyit_aktif=True)
    t = int(time.time() * 1000)
    s = signal(t)
    assert b._pozisyon_ac(s) == 'bekliyor:teyit'
    before = b.teyit_bekleyen[('binance', 'BTCUSDT')]
    assert b._pozisyon_ac(signal(t + 1000)) == 'engel:teyit_bekliyor'
    assert b.teyit_bekleyen[('binance', 'BTCUSDT')] == before


def test_limit_acilis_saati_dolum_anidir(bot_factory, monkeypatch):
    t = int(time.time() * 1000)
    b = bot_factory(giris_modu='limit', teyit_aktif=False)
    s = signal(t)
    assert b._pozisyon_ac(s) == 'bekliyor:limit'
    monkeypatch.setattr(ws_bot.time, 'time', lambda: (t + 5000) / 1000)
    b._bekleyenleri_isle('binance', 'BTCUSDT', 99)
    assert b.portfoy.positions[('binance', 'BTCUSDT')].opened_at == t + 5000


def test_kurtarma_funding_ve_son_fiyati_korur(bot_factory):
    b = bot_factory(teyit_aktif=False)
    now = int(time.time() * 1000)
    assert b._pozisyon_ac(signal(now)) == 'acildi'
    b.portfoy.apply_funding('binance', 'BTCUSDT', 0.001, 102, now_ms=now+10)
    b._durum_kaydet()
    saved = json.load(open(b.durum_dosya))
    assert saved['positions'][0]['funding_fee'] > 0
    b2 = bot_factory()
    assert b2._durum_yukle() == 1
    p = b2.portfoy.positions[('binance', 'BTCUSDT')]
    assert p.funding_fee == pytest.approx(saved['positions'][0]['funding_fee'])
    assert p.last_price == 100 and p.last_price_ts == now
    assert b2.portfoy.balance == pytest.approx(b.portfoy.balance)


def test_bozuk_kurtarma_dosyasi_sifirdan_baslatmaz(bot_factory, tmp_path):
    (tmp_path / 'logs').mkdir(exist_ok=True)
    (tmp_path / 'logs' / 'ws_state.json').write_text('{broken')
    with pytest.raises(RuntimeError, match='guvenlik icin baslatilmadi'):
        bot_factory(durum_devam=True)


def test_atomik_kayit_eski_dosyayi_yazma_hatasinda_korur(bot_factory, monkeypatch):
    b = bot_factory()
    b._durum_kaydet()
    old = open(b.durum_dosya).read()
    def broken_replace(*args):
        raise OSError('simule yazma hatasi')
    monkeypatch.setattr(ws_bot.os, 'replace', broken_replace)
    b.portfoy.balance -= 1
    b._durum_kaydet()
    assert open(b.durum_dosya).read() == old


def test_vratio3_yetersiz_gecmiste_eski_deger_kullanilmaz():
    from scanner.ws_scanner import SpikeDetector
    detector = SpikeDetector(baglam_min_vratio3=10, baglam_onbellek_dk=35)
    d = detector.durum('binance', 'BTCUSDT')
    for i in range(35):
        d.dakika_kapanis.append((i, 100))
        d.dakika_hacim.append((i, 100))
    d.son_fiyat = 100
    d.baglam_vratio3 = 50
    assert detector.baglam_guncelle(d, 35 * 60000) is False
    assert d.baglam_vratio3 == 0
