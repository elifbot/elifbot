import asyncio
import json
import time
from types import SimpleNamespace
import scanner.v7_compare as mod
from scanner.ws_scanner import SpikeDetector

def setup(tmp_path, monkeypatch, *, context_result='baglam_ret_alt', indicator=True):
    now=int(time.time()*1000)
    det=SpikeDetector(ret_pencere_ms=60000,ret_min_pct=.5,rvol_min=5,baglam_aktif=True, min_genislik_oran=0)
    d=det.durum('okx','TEST-USDT-SWAP');d.son_fiyat=100;d.son_fiyat_ts=now;d.son_hacim_ts=now
    d.hiz_uzun=100;d.hiz_kisa=600;d.rvol=6;d.ret_2s=.7
    def context(d,ts):
        d.baglam_ret=.5 if context_result=='baglam_ret_alt' else 1.5
        d.baglam_vratio=2;d.baglam_vratio3=12
        return True
    det.baglam_guncelle=context
    monkeypatch.setattr(mod,'giris_karari',lambda *a:(indicator,'ok' if indicator else 'indikator_vwap_yon',{'vwap':100}))
    seen=[]
    async def dispatch(sig): seen.append(sig)
    bot=SimpleNamespace(detektor=det,asama='tarama',indikator_hazir=True,yeni_giris_kapali=False,
         profit_protection_csv=str(tmp_path/'profit.csv'),_akis_gorevler=set(),_real_volume=None,_sinyal_dispatch=dispatch)
    obs=mod.V7Compare(bot);det.v7_observer=obs
    return now,det,d,obs,seen

def test_legacy_context_rejected_candidate_sent_without_altering_primary(tmp_path,monkeypatch):
    async def run():
        now,det,d,obs,seen=setup(tmp_path,monkeypatch)
        assert det._degerlendir(d,now) is None
        assert d.son_sinyal_ts==0
        await asyncio.gather(*list(obs.bot._akis_gorevler))
        assert len(seen)==1 and seen[0].yon=='LONG' and seen[0].etiket=='V7_FADE_ADAY'
        rec=json.loads(open(obs.path).read())
        assert rec['v7_fade_direction']=='SHORT' and rec['v37_context_first_result']=='baglam_ret_alt'
        det._degerlendir(d,now+100)
        assert obs.counts['legacy_candidate']==1
    asyncio.run(run())

def test_indicator_block_prevents_dispatch(tmp_path,monkeypatch):
    async def run():
        now,det,d,obs,seen=setup(tmp_path,monkeypatch,indicator=False)
        det._degerlendir(d,now);await asyncio.sleep(0)
        assert not seen and obs.counts['v7_side_ind_indikator_vwap_yon']==1
    asyncio.run(run())

def test_context_pass_left_to_primary_no_duplicate(tmp_path,monkeypatch):
    async def run():
        now,det,d,obs,seen=setup(tmp_path,monkeypatch,context_result='pass')
        sig=det._degerlendir(d,now);await asyncio.sleep(0)
        assert sig and not seen
        assert obs.counts['context_pass']==1
    asyncio.run(run())

def test_not_ready_or_stale_does_not_produce_candidate(tmp_path,monkeypatch):
    now,det,d,obs,seen=setup(tmp_path,monkeypatch)
    obs.bot.indikator_hazir=False;det._degerlendir(d,now)
    assert not obs.counts

def test_record_error_fails_closed(tmp_path,monkeypatch):
    async def run():
        now,det,d,obs,seen=setup(tmp_path,monkeypatch)
        obs.path=str(tmp_path/'nonexistent'/'record.jsonl')
        det._degerlendir(d,now);await asyncio.sleep(0)
        assert not seen and obs.counts['record_error']==1
    asyncio.run(run())
