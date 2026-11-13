import asyncio,json,time
from unittest.mock import Mock,AsyncMock
from scanner.ws_scanner import Sinyal
from test_v78_onarim_regresyon import bot_factory


def signal(tag):return Sinyal(int(time.time()*1000),'binance','BTCUSDT','LONG',tag,100,1,2,1000,2000)

def test_audit_has_stable_event_id_and_counters(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);s=signal('ANI_YUKSELIS')
    b._v78_say(s,'candidate_dispatch_attempt');b._v78_say(s,'enrichment_rejected')
    records=[json.loads(x) for x in open(b.eski_v78_motor.audit.path,encoding='utf-8')]
    assert len(records)==2 and records[0]['id']==records[1]['id']
    assert records[0]['source']=='v4' and records[0]['ready']
    assert b.eski_v78_motor.stats['audit_calls']==2 and b.eski_v78_motor.stats['audit_total_ns']>0

def test_audit_failure_stops_only_new_source_without_raising_for_v4(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);b.eski_v78_motor.audit.path=str(tmp_path/'missing_parent_as_file'/'a')
    (tmp_path/'missing_parent_as_file').write_text('not a directory')
    b._v78_say(signal('ANI_YUKSELIS'),'candidate_dispatch_attempt')
    assert b.eski_v78_motor.stats['audit_errors']==1 and b.eski_v78_motor.watchdog_stopped.is_set()
    assert not b.durdu

def test_watchdog_stopped_source_survives_actual_v4_readiness_task_check(tmp_path,monkeypatch):
    import ws_bot
    from types import SimpleNamespace
    b=bot_factory(tmp_path,monkeypatch);m=b.eski_v78_motor
    m.watchdog_stopped.set();m.watchdog_fired.set()
    report={'borsalar':{'binance':{'toplam':1,'mum_ve_fiyat_hazir':1,'hazir_yuzde':100},
                        'okx':{'toplam':1,'mum_ve_fiyat_hazir':1,'hazir_yuzde':100}}}
    monkeypatch.setattr(ws_bot,'kapsam',lambda *args:report)
    monkeypatch.setattr(b,'durum_yaz',lambda:None)
    async def go():
        task=asyncio.create_task(m.run(),name='eski-v78-paper-sinyal')
        await asyncio.sleep(0)
        await b._indikator_hazirligini_bekle(SimpleNamespace(semboller=['OKX']),SimpleNamespace(semboller=['BN']),[task])
        assert b.indikator_hazir and not task.done() and not b.durdu
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(go())
