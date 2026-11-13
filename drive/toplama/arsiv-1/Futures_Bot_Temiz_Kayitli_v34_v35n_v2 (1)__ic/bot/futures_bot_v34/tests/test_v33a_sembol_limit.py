"""v33a sembol evreni — çevrimdışı sentetik testler; H-01 değildir."""
import asyncio
import json
from types import SimpleNamespace
import pytest
import ws_bot
from scanner.ws_scanner import BinanceAkisi, BinanceRestAkisi, SpikeDetector


def test_constructor_limit_and_validation(monkeypatch):
    monkeypatch.setattr(ws_bot.Bot, '_olay_dosyasi_hazirla', lambda self: None)
    bot=ws_bot.Bot(SpikeDetector(), sembol_limit=30)
    assert bot.sembol_limit==30
    for value in (-1, 1.1, True, '30'):
        with pytest.raises(ValueError): ws_bot.Bot(SpikeDetector(), sembol_limit=value)
    assert ws_bot._negatif_olmayan_tam_sayi('0') == 0
    assert ws_bot._negatif_olmayan_tam_sayi('30') == 30
    with pytest.raises(Exception): ws_bot._negatif_olmayan_tam_sayi('-1')


class _Reply:
    def __init__(self, body): self.body=body
    async def __aenter__(self): return self
    async def __aexit__(self,*a): pass
    async def json(self): return self.body
class _Session:
    def __init__(self, body): self.body=body
    def get(self,*a,**kw): return _Reply(self.body)

def _info(symbols):
    return {'symbols':[{'symbol':s,'contractType':'PERPETUAL','quoteAsset':'USDT','status':'TRADING'} for s in symbols]}

@pytest.mark.parametrize('allow,expected', [(None, {'AUSDT','BUSDT','CUSDT'}), ({'BUSDT','CUSDT'}, {'BUSDT','CUSDT'})])
def test_rest_symbol_filter_before_prefill(allow,expected):
    b=BinanceRestAkisi(SpikeDetector(),lambda x:None,sembol_izin=allow)
    count=asyncio.run(b.sembolleri_yukle(_Session(_info(['AUSDT','BUSDT','CUSDT']))))
    assert b.semboller==expected and count==len(expected)

def test_rest_missing_selected_symbol_fails_closed():
    b=BinanceRestAkisi(SpikeDetector(),lambda x:None,sembol_izin={'AUSDT','XUSDT'})
    with pytest.raises(RuntimeError,match='XUSDT'):
        asyncio.run(b.sembolleri_yukle(_Session(_info(['AUSDT','BUSDT']))))
    assert b.semboller==set()

@pytest.mark.parametrize('source',[BinanceRestAkisi, BinanceAkisi])
def test_empty_allow_list_rejected(source):
    with pytest.raises(ValueError): source(SpikeDetector(),lambda x:None,sembol_izin=set())


def test_ws_ticker_filter():
    class Detector:
        def __init__(self): self.seen=[]
        def besle_fiyat(self,*x): self.seen.append(x);return None
    d=Detector(); b=BinanceAkisi(d,lambda _:None,sembol_izin={'AUSDT'})
    asyncio.run(b._isle(json.dumps([{'s':'AUSDT','c':'1','q':'3','E':1000}, {'s':'BUSDT','c':'1','q':'3','E':1000}])))
    assert [x[1] for x in d.seen]==['AUSDT']


@pytest.mark.parametrize('limit',[0,30])
def test_bot_calistir_passes_same_limit_to_okx_and_binance(monkeypatch,limit):
    async def run():
        capture={}
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        async def okx_symbols(session): return [f'S{i:02}-USDT-SWAP' for i in range(40)][::-1], {'S01','S02'}
        async def bnc_symbols(session): return {f'S{i:02}USDT' for i in range(40)}
        async def forever(*args,**kwargs): await asyncio.Event().wait()
        class OKX:
            def __init__(self, detector, symbols, *a, **kw):capture['okx']=symbols
            async def calistir(self,*a):await forever()
        class BNC:
            def __init__(self,*a,**kw):capture['rest_izin']=kw.get('sembol_izin');self.hazir=asyncio.Event()
            async def calistir(self,*a):self.hazir.set();await forever()
        class Flow:
            def __init__(self,symbols,*a,**kw):capture['agg']=set(symbols)
            async def calistir(self,*a):await forever()
        monkeypatch.setattr(ws_bot.aiohttp,'ClientSession',Session)
        monkeypatch.setattr(ws_bot,'okx_enstrumanlari',okx_symbols)
        monkeypatch.setattr(ws_bot,'binance_sembolleri',bnc_symbols)
        monkeypatch.setattr(ws_bot,'OKXAkisi',OKX)
        monkeypatch.setattr(ws_bot,'BinanceRestAkisi',BNC)
        monkeypatch.setattr(ws_bot,'BinanceAggTradeFlow',Flow)
        monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
        b=ws_bot.Bot(SpikeDetector(baglam_aktif=False),sure_dk=.00001,binance_hacim_kaynagi='aggtrade',sembol_limit=limit,defter_golge=False,funding_aktif=False)
        b.olay_yazici=SimpleNamespace(close=lambda:None)
        b.cikis_yonetimi=forever;b._sayac_dongusu=forever
        b._tumunu_kapat=lambda *a:None;b.durum_yaz=lambda:None
        await b.calistir()
        n=limit or 40
        assert len(capture['okx'])==n and len(capture['agg'])==n
        if limit:
            assert capture['okx']==sorted(capture['okx'])
            assert capture['rest_izin']==capture['agg']=={f'S{i:02}USDT' for i in range(limit)}
        else: assert capture['rest_izin'] is None
    asyncio.run(run())
