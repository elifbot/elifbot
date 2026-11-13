"""İki paper kapanış + yeni girişin aynı anda denenmesi, sentetik ve ağsız."""
import json
import pytest
from test_v78_atomik_kapanis_yeni import child, rows, result

def test_aktif_kapanis_sirasinda_diger_islem_bekler_ve_sonra_tutarli_kapanir(tmp_path):
    p=child(tmp_path,'concurrent'); assert p.returncode==0,p.stdout+p.stderr
    r=result(p);intents,positions,trades,account=rows(tmp_path)
    assert intents==[('CLOSED',),('CLOSED',)]
    assert not positions and len(trades)==2
    assert r['result'] is True and r['locked'] is False
    assert account['balance']==pytest.approx(r['balance'])
