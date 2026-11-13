"""v18 duzeltmeleri: gercek extended feed'ler (mock), risk varsayilani,
kayma modeli, kalici durum kurtarma, katalog tutarliligi."""
from __future__ import annotations
import time
from types import SimpleNamespace
import pytest
import ws_bot
from scanner.ws_scanner import Sinyal

class _Resp:
    status_code = 200
    def __init__(self, payload): self._p = payload
    def json(self): return self._p

class _Session:
    def __init__(self, payload): self._p = payload
    def get(self, url, params=None, timeout=None): return _Resp(self._p)

def test_funding_feed_binance_mock():
    from data.extended.funding_feed import FundingFeed
    f = FundingFeed(session=_Session({"lastFundingRate": "0.0001"}))
    assert f.fetch_funding_rate("binance", "BTCUSDT") == pytest.approx(0.0001)

def test_oi_ve_mark_okx_mock():
    from data.extended.oi_feed import OpenInterestFeed
    from data.extended.markprice_feed import MarkPriceFeed
    assert OpenInterestFeed(session=_Session({"code":"0","data":[{"oi":"123.5"}]})).fetch_open_interest("okx","BTC-USDT-SWAP") == 123.5
    assert MarkPriceFeed(session=_Session({"code":"0","data":[{"markPx":"100.5"}]})).fetch_mark_price("okx","BTC-USDT-SWAP") == 100.5

def test_katalog_cvd_ve_f_ailesi_aktif():
    from indicators.catalog import CATALOG
    assert CATALOG.get("CVD").status == "ACTIVE"
    assert CATALOG.get("Funding Rate").status == "ACTIVE"
    assert CATALOG.get("Open Interest").status == "ACTIVE"

@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    bots=[]
    def _yap(**kw):
        ayar=dict(strateji="fade", tp=99.0, sl=2.0, tut_dk=240.0, giris_modu="market", min_genislik=0.0, acilis_freni=0)
        ayar.update(kw)
        b=ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}), sure_dk=0, binance_mod="rest", **ayar)
        b.durum_dosya=str(tmp_path/"ws_state.json"); bots.append(b); return b
    yield _yap
    for b in bots: b.olay_yazici.close()

def _sinyal(symbol="BTCUSDT", yon="LONG"):
    return Sinyal(ts_ms=int(time.time()*1000), exchange="binance", symbol=symbol, yon=yon, etiket="T", fiyat=100.0, ret_pct=-0.6, rvol=6.0, hacim_usd=10000.0, gecen_ms=60000)

def test_v18_varsayilan_risk_limitleri_acik(bot_yap):
    pf=bot_yap().portfoy
    assert pf.max_open_positions == 40 and pf.max_same_direction == 40
    assert pf.max_utilisation == pytest.approx(0.95)
    assert pf.balance_floor == 100.0 and pf.daily_loss_limit_pct == pytest.approx(0.05)

def test_kayma_giris_cikis_olumsuz_yonde(bot_yap):
    b=bot_yap(kayma_pct=0.05)
    assert b._kaymali_giris(100.0,"LONG") == pytest.approx(100.05)
    assert b._kaymali_giris(100.0,"SHORT") == pytest.approx(99.95)
    assert b._kaymali_cikis(100.0,"LONG") == pytest.approx(99.95)
    assert b._pozisyon_ac(_sinyal())=="acildi"
    pos=b.portfoy.positions[("binance","BTCUSDT")]
    assert pos.entry_price == pytest.approx(100.05)

def test_durum_kaydet_yukle_kurtarma(bot_yap):
    b=bot_yap(); assert b._pozisyon_ac(_sinyal())=="acildi"; b._durum_kaydet()
    b2=bot_yap()
    assert b2._durum_yukle()==1
    assert ("binance","BTCUSDT") in b2.portfoy.positions
