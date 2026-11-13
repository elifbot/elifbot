"""Offline integration of scheduled watcher, UTC snapshot and cancellation."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
import ws_bot

NOW=int(datetime(2026,10,31,12,0,30,tzinfo=timezone.utc).timestamp()*1000)
END=NOW//60000

def make_bot():
    b=object.__new__(ws_bot.Bot);b.durdu=False
    b.detektor=SimpleNamespace(durumlar={('binance','X'):SimpleNamespace(
        ind_mum={mid:(1,1,1,1,1) for mid in range(END-60,END) if mid!=END-2})})
    return b


def test_watcher_records_exact_missing_utc_runs_twice_and_cancels(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot.time,'time',lambda:NOW/1000)
    calls=[]
    async def go():
        b=make_bot();done=asyncio.Event()
        async def fake_repair(session,det,syms,**kw):
            calls.append((set(syms),kw))
            if len(calls)>=2:done.set()
            return {'mum_eklenen':0,'hata':0}
        monkeypatch.setattr(ws_bot,'binance_indikator_mum_eksiklerini_doldur',fake_repair)
        task=asyncio.create_task(b._binance_mum_izleyici(object(),{'X'},'https://example.invalid',interval=.001,timeout=.1))
        await asyncio.wait_for(done.wait(),1)
        task.cancel()
        result=await asyncio.gather(task,return_exceptions=True)
        assert isinstance(result[0],asyncio.CancelledError)
    asyncio.run(go())
    rows=[json.loads(x) for x in (tmp_path/'logs/binance_mum_bosluklari.jsonl').read_text().splitlines()]
    snapshots=[r for r in rows if r['event']=='snapshot']
    assert len(calls)>=2 and len(snapshots)>=2
    expected=datetime.fromtimestamp((END-2)*60,timezone.utc).isoformat()
    assert snapshots[0]['missing_utc_minutes']=={'X':[expected]}
    assert calls[0][1]['simdi_ms']==NOW


def test_watcher_rest_timeout_records_and_continues(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot.time,'time',lambda:NOW/1000)
    async def go():
        b=make_bot();logged=asyncio.Event();original=b._binance_bosluk_kaydi
        def record(event):
            original(event)
            if event.get('error')=='timeout':logged.set()
        b._binance_bosluk_kaydi=record
        async def stuck(*args,**kw):await asyncio.Event().wait()
        monkeypatch.setattr(ws_bot,'binance_indikator_mum_eksiklerini_doldur',stuck)
        task=asyncio.create_task(b._binance_mum_izleyici(None,{'X'},'https://example.invalid',interval=.001,timeout=.005))
        await asyncio.wait_for(logged.wait(),1)
        assert not task.done()
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(go())
    rows=[json.loads(x) for x in (tmp_path/'logs/binance_mum_bosluklari.jsonl').read_text().splitlines()]
    assert rows[0]['event']=='snapshot' and rows[1]['error']=='timeout'


def test_watcher_logs_later_observed_recovery_without_attributing_source(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot.time,'time',lambda:NOW/1000)
    async def go():
        b=make_bot();done=asyncio.Event();count=0
        async def repair(*args,**kwargs):
            nonlocal count
            count+=1
            if count==1:b.detektor.durumlar[('binance','X')].ind_mum[END-2]=(1,1,1,1,1)
            if count==2:done.set()
            return {'mum_eklenen':0,'hata':0}
        monkeypatch.setattr(ws_bot,'binance_indikator_mum_eksiklerini_doldur',repair)
        task=asyncio.create_task(b._binance_mum_izleyici(None,{'X'},'https://example.invalid',interval=.001,timeout=.1))
        await asyncio.wait_for(done.wait(),1);task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(go())
    rows=[json.loads(x) for x in (tmp_path/'logs/binance_mum_bosluklari.jsonl').read_text().splitlines()]
    snapshots=[r for r in rows if r['event']=='snapshot']
    expected=datetime.fromtimestamp((END-2)*60,timezone.utc).isoformat()
    assert snapshots[1]['observed_recovered_utc_minutes']=={'X':[expected]}
