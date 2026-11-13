import importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('paper_supervisor',Path(__file__).parents[2]/'paper_30dk_supervisor.py')
sup=importlib.util.module_from_spec(spec);spec.loader.exec_module(sup)


def test_supervisor_keeps_v4_process_alive_after_source_watchdog(tmp_path,monkeypatch):
    logs=tmp_path/'logs';logs.mkdir()
    monkeypatch.setattr(sup,'ROOT',tmp_path);monkeypatch.setattr(sup,'LOG',logs)
    monkeypatch.setattr(sup,'status',logs/'ws_durum.json');monkeypatch.setattr(sup,'logfile',logs/'supervisor.jsonl')
    monkeypatch.setattr(sup,'sample',lambda:{'ok':True})
    (tmp_path/'ws_bot.py').write_text('''import json,os,time\nfrom pathlib import Path\np=Path("logs/ws_durum.json")\nfor i in range(5):\n d={"pid":os.getpid(),"son_heartbeat_utc":str(i),"asama":"tarama","sure_sn":i,"tarama_baslangic_utc":"test","eski_v78_paper":{"watchdog_stopped":i>=1,"stop_reason":"deadline","watchdog_stage":"candles"}}\n p.write_text(json.dumps(d));time.sleep(.4)\n''')
    result=sup.run();r=json.loads((logs/'supervisor_result.json').read_text())
    assert result==0 and r['reason']=='bot_exited' and r['bot_exit_code']==0
    assert r['new_source_stop']['stop_reason']=='deadline'
    assert r['last_scan_elapsed_sec']==4
