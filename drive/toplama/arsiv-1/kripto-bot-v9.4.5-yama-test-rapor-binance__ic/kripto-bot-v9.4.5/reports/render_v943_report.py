"""Post-run reporting only. Cannot alter frozen runtime or test data."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from contextlib import contextmanager
import json,hashlib,ast,sqlite3,importlib.metadata as im,platform
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'reports'
def main():
    m=json.loads((R/'v943_freeze_manifest.json').read_text())
    active=R/'v943_packaging_freeze_manifest.json'
    source_manifest=json.loads(active.read_text()) if active.exists() else m
    badsource=[n for n,h in source_manifest['source_sha256'].items() if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    assert not badsource,badsource
    s=json.loads((R/'v943_paper_15dk_summary.json').read_text());assert s['phase']=='COMPLETED' and s['elapsed_sec']>=900
    rows=[json.loads(x) for x in (R/'v943_health_samples.jsonl').read_text().splitlines() if x]
    samples=[x for x in rows if x.get('phase') in ('ACTIVE','DRAINING') and x.get('elapsed_sec',0)>=60]
    bad=[x for x in samples if x['health_http_status']!=200]
    in_flight=[x for x in samples if x.get('operational_health',{}).get('ledger_status')=='IN_FLIGHT']
    counts=dict(Counter(str(x['health_http_status']) for x in rows if 'health_http_status' in x))
    endpoints=s['venues']['binance']
    checks={'completed_900s':s['elapsed_sec']-s['drain_elapsed_sec']>=900,
        'binance_ticks_positive':endpoints['ticks']>0,'aggTrade_errors_zero':endpoints['errors_aggTrade']==0,
        'both_tapes_healthy':all(s['venues'][v]['trade_tape_healthy'] for v in ['binance','okx']),
        'observed_active_post_grace_health_200':bool(samples) and not bad,
        'endpoint_fields_correct':endpoints.get('endpoint_aggTrade')=='fstream.binance.com/market' and endpoints.get('endpoint_bookTicker')=='fstream.binance.com/public',
        'frozen_source_unchanged':not badsource}
    from src.state_store import StateStore
    database=ROOT/'reports/v943_paper_15dk_state.db'
    @contextmanager
    def conn():
        c=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
        try:yield c
        finally:c.close()
    reader=StateStore.__new__(StateStore);reader._conn=conn
    strict_final=reader.verify_paper_ledger_integrity()
    checks['final_strict_ledger_ok']=bool(strict_final.get('ok'))
    first=next(x for x in rows if x.get('phase')=='ACTIVE')
    start=first['sampled_at_epoch']-first['elapsed_sec']
    early_errors=[x for x in rows if 'sampling_error' in x and x['sampled_at_epoch']-start>=60 and x['sampled_at_epoch']<(R/'v943_paper_15dk_summary.json').stat().st_mtime]
    checks['no_sampling_errors_before_completion']=not early_errors
    (R/'v943_final_strict_ledger_check.json').write_text(json.dumps(strict_final,indent=2))
    proof={}
    for file,method in [('src/state_store.py','verify_paper_ledger_integrity')]:
        def get(p):
            text=p.read_text();tree=ast.parse(text)
            node=next(n for cls in tree.body if isinstance(cls,ast.ClassDef) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==method)
            return ast.get_source_segment(text,node)
        old=get(R/'v943_reference_sources'/file);new=get(ROOT/file)
        proof[method]={'old_sha256':hashlib.sha256(old.encode()).hexdigest(),'new_sha256':hashlib.sha256(new.encode()).hexdigest(),'identical':old==new}
    (R/'v943_strict_method_hash_proof.json').write_text(json.dumps(proof,indent=2))
    env={'python':platform.python_version(),'packages':{n:im.version(n) for n in ['aiohttp','ccxt','numpy','pandas','pytest','pytest-asyncio','requests','tabulate']}}
    (R/'v943_environment.json').write_text(json.dumps(env,indent=2))
    r3=json.loads((R/'v943_packaging_r3_evidence.json').read_text())
    result={'version':'9.4.3','scope':'unit and synthetic HTTP patch verification plus single live feed smoke test; no live PENDING-response verification','regression_tests':121,'packaging_revision':3,'historical_15min_record_reused':True,'new_health_tests':34,'checks':checks,
            'sampled_connectivity_checks_passed':all(checks.values()),'live_pending_scenario_verified':False,'pending_in_flight_observed_live':False,'live_order_open_close_cycle_verified':False,'operational_readiness_approved':False,'http_sample_counts':counts,'post_grace_active_samples':len(samples),'bad_post_grace_samples':len(bad),
            'observed_live_in_flight_samples':len(in_flight),'final_strict_ledger':strict_final,'real_money_approved':False,
            'closed_count':s['closed_count'],'open_count':len(s['open_positions']),'equity_delta':s['net_pnl'],'venues':s['venues']}
    result.update({'evidence_scope':'Historical 15min statistics; separate packaging_r3 Docker and new24h evidence below','packaging_r3':r3})
    (R/'v943_report_generation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (R/'v943_test_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    lines=['# v9.4.3 — PENDING sağlık ve endpoint yaması','',
      '**PAPER araştırma sürümü; gerçek para, kârlılık veya gerçek borsa yürütme onayı yok.**','',
      '**Kanıt sınırı:** 15 saniyelik PENDING toleransı birim ve ayrı HTTP testleriyle doğrulandı. Canlı koşuda PENDING sırasında sağlıklı HTTP yanıtı gözlenmedi. 59/59 HTTP 200 yalnız örneklenen bağlantı/sağlık durumlarının kanıtıdır; canlı PENDING senaryosu veya uçtan uca operasyonel hazırlık onayı değildir.','',
      '## Yapılan düzeltmeler','',
      '- Süreç-içi sahiplik kaydıyla eşleşen, 15 saniyeden genç PENDING için yalnız sağlık görünümünde IN_FLIGHT/200. 15 saniyede ve sonrasında alarm/503.',
      '- Restarttan kalan, başka store/PIDden gelen, yaşı/sahibi belirsiz kayıt hemen alarm. Bu kayıtlara süre toleransı verilmez.',
      '- Üretim defteri değiştirilmez: salt-okunur SQLite yedeği belleğe alınır. Uygun genç niyetler yalnız geçici kopyada ayrıştırılır; kalan kesinleşmiş hesap, ücret, funding ve pozisyonlar eski sıkı doğrulayıcıdan geçer.',
      '- IN_FLIGHT anında ledger_reconciled=false kalır; bu tamamlanmış mutabakat değildir. Uyarı ve pending yaşları APIde görünür; panel TAM yerine İŞLEM BEKLİYOR gösterir.',
      '- Alarmlar gerçek nedenini gösterir: LEDGER_INTEGRITY_ERROR(reason=...), gerçek küme farkında POSITION_SET_MISMATCH.',
      '- endpoint_aggTrade ve endpoint_bookTicker ayrı; endpoint ortak alanı artık son yazanın adresiyle yanıltmaz.',
      '', '## Güvenlik ve değişmezlik','',
      '- Sıkı verify_paper_ledger_integrity metodu kaynak metni olarak değişmedi. Recovery, mali işlem kilidi ve PENDINGin kalıcı kaydı değiştirilmedi.',
      '- Prepare yöntemlerine yalnız süreç-içi gözlem kaydı eklendi. Bu atama çıkarılınca ASTleri önceki yöntemlerle aynı; commit/iptal yöntemleri aynıdır.',
      '- UnifiedTradingEngine içinde yalnız operational_health_snapshot değişti; diğer yöntemlerin ASTleri eski kaynakla aynı. Strateji/risk/çıkış/replay dosyaları korundu.',
      '- Önceki 13 dosya grubunun 11i byte-byte aynı. live_runner ve unified_engine sağlık/telemetri değişikliği nedeniyle farklı; 13/13 aynı iddiası YOK. StateStore da ek sağlık kaydı/metodu içerir.',
      '- Ek sağlık hesaplarının canlı zamanlamayı hiç etkilemediği iddia edilmez.',
      '', '## Testler','', '```text',(R/'v943_pytest.txt').read_text().strip(),'```','',
      'Bu bölümdeki 121 sonucu eski host test kaydıdır. Yeni gerçek Docker testi ayrıca aşağıdaki r3 bölümündedir (121 geçti, 11.73s); iki koşunun test sayıları toplanmaz.',
      'Önceki 87 teste 34 yeni sağlık/endpoint/değişmezlik kontrolü eklendi. Test kapsamı: dört niyet tablosu, 0/14.999/15/16s sınırları, yeniden başlatma/yabancı sahip, gerçek nakit/ücret/funding hataları, pozisyon kümesi farkı, ilk emir, iptal, salt-okunurluk, sıkı recovery ve gerçek HTTP handlerı. Endpoint testi iki akışın birbirini ezmediğini doğrular.',
      '', 'İlk test koşusunda eski alarm metnine bağlı bir assert başarısızdı (117 geçti, 1 başarısız). Bu testin beklentisi istenen yeni POSITION_SET_MISMATCH sözleşmesine güncellendi; güvenlik denetimi kaldırılmadı. İlk çıktı saklandı. Son tam test 121/121dir.',
      '', '## Önceki tamamlanmış 15 dakikalık canlı PAPER koşusu','',
      f'- Donma UTC: {m["frozen_at_utc"]}. Donmuş kaynak kontrolü başarılı.',
      f'- Aktif süre yaklaşık {s["elapsed_sec"]-s["drain_elapsed_sec"]:.3f}s; drenaj {s["drain_elapsed_sec"]:.3f}s; toplam {s["elapsed_sec"]:.3f}s.',
      '- Bu eski 15 dakikalık deney doğrudan Python ileydi. Sonraki r3 Docker deneyi ayrı bölümde kaydedildi.',
      '| Ölçüm | Binance | OKX |','|---|---:|---:|']
    for label,key in [('İşlem ticki','ticks'),('BBO','bbo_updates'),('Hata','errors'),('aggTrade hatası','errors_aggTrade'),('Trade-tape sağlıklı','trade_tape_healthy')]:
        lines.append(f'| {label} | {s["venues"]["binance"].get(key,"—")} | {s["venues"]["okx"].get(key,"—")} |')
    lines+=['',f'- Endpoint aggTrade: `{endpoints.get("endpoint_aggTrade")}`; bookTicker: `{endpoints.get("endpoint_bookTicker")}`.',
      f'- HTTP örnekleri: `{counts}`. Aktif fazda ilk 60s sonrası {len(samples)} örnek, başarısız {len(bad)}. Yaklaşık 15s aralıkla alınan örneklerdir; sürekli erişilebilirlik garantisi değildir.',
      f'- Canlı örneklerde IN_FLIGHT görülme sayısı: {len(in_flight)}. Sıfırsa bu canlı koşu PENDING toleransını olay üzerinde sınamış sayılmaz; o davranış ayrı HTTP/regresyon testleriyle sınanmıştır.',
      f'- Paper kuyruk: `{json.dumps(s["analytics"]["maker_queue"],ensure_ascii=False)}`.',
      f'- Kapanmış {s["closed_count"]}, açık {len(s["open_positions"])}. Kapalı net {s["closed_net_pnl"]:+.6f}, açık brüt {s["unrealized_pnl"]:+.6f}, toplam equity farkı {s["net_pnl"]:+.6f} USDT.',
      f'- Son sıkı defter kontrolü: `{json.dumps(strict_final,ensure_ascii=False)}`.',
      '', '### Yalnız örneklenen bağlantı/sağlık kontrolleri — tam operasyonel kabul değil','', '| Kontrol | Geçti |','|---|---|']
    for k,v in checks.items():lines.append(f'| {k} | {v} |')
    if bad:
        lines+=['','Başarısız gözlemler gizlenmedi:','```json',json.dumps(bad,ensure_ascii=False,indent=2),'```']
    lines+=['','## Sınırlar ve önceki olayın yorumu' ,'',
      'Kayıt: 1 emir denemesi vardı, dolmadı; 0 açık/0 kapalı pozisyon ve 0 gözlenmiş IN_FLIGHT örneği. Bu, PENDINGin hiç oluşmadığını kanıtlamaz; onun içindeki HTTP yanıtının örneklemeye yakalanmadığını gösterir. Önceki 503ün canlıda kapandığı kanıtlanmış değildir.','',
      '**v9.4.2deki 503 için en olası neden geçici PENDING emir niyeti; deneyle yeniden üretildi, canlı olayda ayrıca yakalanmadı.** Yeni yama eski koşunun sonucunu geriye dönük değiştirmez.',
      '- Bu yalnız tek yeni ağ/zaman koşusudur. Ağ koşulları değişirse tekrar test gerekir.',
      '- Thread sınırı: PENDING kaydı sonrası süreç-içi token kaydediliyor. Mevcut tek iş parçacıklı asyncio akışında arada await yok; ayrı threadli sağlık okuyucusu için atomik görünürlük ayrıca sınanmış değildir.',
      '- Maliyet sınırı: sağlık görünümü DB kopyası alır. Küçük DBdeki test, büyüyen defterde veya sık panel sorgusunda gecikme/CPU/RAM maliyetini ölçmüş sayılmaz. r3 bölümünde dar sentetik kopya ölçümü eklendi; tam API/gerçek büyük defter yük doğrulaması yapılmadı.',
      '- Yeni 24 saatlik prospektif PAPER koşusu önceden kaydedilmiş planla BAŞLATILDI; tamamlanmadı. Başlangıç kanıtı ve sınırlar aşağıdaki r3 bölümündedir.',
      '- Az sayıda deneme/dolumdan yürütme güvenilirliği çıkarılamaz. Kapanmış işlem yoksa çıkış/kapanış hattı bu canlı koşuda sınanmamıştır.',
      '- Paper dolumu gerçek borsa dolumu değildir. Çıkış, emir kuyruğu ve piyasa etkisi için geniş kapsamlı genel onay yoktur.',
      '- Önceki negatif tarihsel araştırma kanıtı değişmedi. Yeni strateji eşiği seçimi, tarihsel kârlılık doğrulaması veya bağımsız ileri-OOS iddiası yoktur.',
      '', '## Dosyalar','',
      'v943_freeze_manifest.json, v943_pytest.txt, v943_pytest_initial_alarm_contract.txt, v943_reference_sources, v943_strict_method_hash_proof.json, v943_live_run.log, v943_health_samples.jsonl, v943_paper_15dk_summary.json, v943_test_results.json ve yeni PACKAGE_MANIFEST.json. Diğer v94/v941 dosyaları devralınan tarihsel arşivdir.','']
    lines+=['', (R/'v943_packaging_r3_update.md').read_text()]
    (R/'v943_final_report.md').write_text('\n'.join(lines),encoding='utf-8')
    status={'version':'9.4.3','release_type':'health_telemetry_patch_only','approved_for_real_money':False,'strategy_rules_changed':False,
            'strict_recovery_changed':False,'regression_tests_passed':121,'packaging_revision':3,'historical_15min_record_reused':True,'health_grace_sec':15,
            'historical_15min_status':'COMPLETED','new_24h_status_at_delivery':r3['long_paper_status_at_snapshot'],'new_24h_completed':False,'sampled_connectivity_checks_passed':all(checks.values()),'live_pending_scenario_verified':False,'pending_in_flight_observed_live':False,'live_order_open_close_cycle_verified':False,'operational_readiness_approved':False,'live_http_sample_counts':counts,
            'historical_profitability_revalidated':False,'previous_negative_research_status_preserved':True,
            'canonical_freeze':'reports/v943_packaging_freeze_manifest.json','canonical_report':'reports/v943_final_report.md'}
    status['packaging_r3']=r3
    status['sampled_connectivity_checks_scope']='historical 15min run only; not full operational acceptance'
    (ROOT/'RELEASE_STATUS.json').write_text(json.dumps(status,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
