"""Sentetik tanı kapsamı. Gerçek yük/ağ kanıtı değildir."""
import asyncio,concurrent.futures,gc,json,threading
from reports.process_diagnostics import Diagnostics

def read(tmp):return [json.loads(x) for x in (tmp/'logs/process_diagnostics.jsonl').read_text().splitlines()]

def test_on_tur_thread_snapshot(tmp_path):
    d=Diagnostics(str(tmp_path))
    for _ in range(10):d.thread_snapshot()
    rows=read(tmp_path)
    assert len(rows)==10 and all(x['event']=='thread_snapshot' and x['threads'] for x in rows)

def test_asyncio_unhandled_exception(tmp_path):
    d=Diagnostics(str(tmp_path))
    async def run():
        loop=asyncio.get_running_loop();d.attach_loop(loop)
        async def bad():raise ValueError('deneme')
        task=asyncio.create_task(bad());await asyncio.sleep(0);del task;gc.collect();await asyncio.sleep(0)
    asyncio.run(run())
    assert any(x['event']=='asyncio_exception' and x['exception']=='ValueError' for x in read(tmp_path))

def test_executor_future_exception_izlenirse(tmp_path):
    d=Diagnostics(str(tmp_path))
    def bad():raise RuntimeError('sentetik')
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        f=d.watch_future(pool.submit(bad))
        try:f.result()
        except RuntimeError:pass
    assert any(x['event']=='future_exception_observed' and x['exception']=='RuntimeError' for x in read(tmp_path))
