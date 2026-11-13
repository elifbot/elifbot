"""D-11/D-12 sentetik testler: ağ/emir yok; RTT uydurulmaz."""
import asyncio
from types import SimpleNamespace
from reports.process_diagnostics import ws_ping_kayit,event_yuk_kayit

class FakeOKX:
    _son_receive_utc=1234567890.5
class FakeBNC:
    _son_receive_utc=None
class FakeBot:
    def __init__(self,akis=None,regime=None,agg_tasks=None):
        self._akis_gorevler=akis if akis is not None else set()
        self._regime_tasks=regime if regime is not None else set()
        # Üretimde görevler _bnc_akis değil _real_volume.tasks içinde.
        self._real_volume=SimpleNamespace(tasks=agg_tasks if agg_tasks is not None else set())

def test_d11_rtt_olculmedi_sayisal_degil():
    k=ws_ping_kayit(FakeOKX(),FakeBNC())
    assert k['rtt']=='olculmedi' and not isinstance(k['rtt'],(int,float))
    assert 'aiohttp' in k['rtt_neden']

def test_d11_son_receive_durust():
    k=ws_ping_kayit(FakeOKX(),FakeBNC())
    assert k['okx_son_receive_unix']==1234567890.5 and k['binance_son_receive_unix'] is None
    assert k['heartbeat_sn']==20

def test_d12_queue_anahtari_yok():
    k=asyncio.run(_make(FakeBot()))
    keys=' '.join(k.keys()).lower()
    assert 'queue' not in keys and 'kuyruk' not in keys
    assert k['not']=='queue yok; aktif gorev sayisi'

async def _make(bot):return event_yuk_kayit(bot)

def test_d12_gorev_sayilari_int():
    bot=FakeBot(akis={1,2,3},regime={4,5},agg_tasks={6,7,8,9,10,11,12})
    k=asyncio.run(_make(bot))
    assert (k['akis_gorev'],k['regime_gorev'],k['aggtrade_gorev'])==(3,2,7)
    assert isinstance(k['asyncio_toplam'],int) and k['asyncio_toplam']>=1


def test_emit_imzasi_self_emit_event_fields():
    event_data=asyncio.run(_make(FakeBot()))
    for d in (ws_ping_kayit(FakeOKX(),FakeBNC()),event_data):
        assert 'tip' not in d and 'event' not in d
