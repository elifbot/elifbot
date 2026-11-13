"""Reporting-only renderer added after freeze; cannot alter trading/validation results."""
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
import csv,json,hashlib
import numpy as np

ROOT=Path(__file__).resolve().parents[1];R=ROOT/'reports'
fmt=lambda v:'Yetersiz / yok' if v is None else f'{v:+.2f}'
def fmtci(x):return 'Hesaplanamadı / yetersiz kanıt' if x is None else f'[{x[0]:+.2f}, {x[1]:+.2f}]'
def stamp(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def main():
    v=json.loads((R/'v94_historical_validation.json').read_text());live=json.loads((R/'v94_canli_15dk_summary.json').read_text())
    if not v['complete'] or live['phase']!='COMPLETED':raise RuntimeError('Incomplete run is not a completed test')
    m=v['freeze'];dev=json.loads((R/'v94_development_results.json').read_text());g=json.loads((R/'v941_gate_cohort_audit.json').read_text())
    from scripts.validate_v94 import integrity
    integrity(m)
    a=v['arms']['v94'];old=v['arms']['v93_on_corrected_clock']
    from src.gate_statistics import confidence
    for group in ('BASE_ACCEPTED_REFERENCE','SINGLE_BLOCKER_TREND','SINGLE_BLOCKER_FLOW','SINGLE_BLOCKER_MARKET'):
        sides=g['summary_by_side'].setdefault(group,{})
        for side in ('LONG','SHORT'):
            sides.setdefault(side,{'unique_symbol_bar_n':0,'matured_15m_n':0,'censored_15m_n':0,
                'mean_gross_mark_return_bps':None,'mean_stress_8bps_per_side_mark_return_bps':None,
                'worst_bar_mae_bps':None,'initial_tactical_stop_barrier_touches':0,'emergency_8pct_barrier_touches':0,
                'confidence':confidence([])})
    p=np.array([t['realized_pnl'] for t in a['trades']]);meanwin=float(p[p>0].mean()) if (p>0).any() else None
    meanloss=float(p[p<0].mean()) if (p<0).any() else None
    tests=(R/'v94_pytest.txt').read_text().strip().splitlines()[-1]
    lines=['# Kripto Bot v9.4.1 — Nihai inceleme ve deney raporu','',
       '**GERÇEK PARA ONAYI YOK. Bu dosya bir araştırma adayının olumlu ve olumsuz kanıtlarını birlikte raporlar.**','',
       f'**Önceden tanımlı araştırma kabul sonucu:** `{v["decision"]}`. Kontrollerin tümü geçti mi: **{v["research_criteria_passed"]}**.','',
       '## 1. Yönetici özeti','',
       f'- Yeni aday: **{a["trade_count"]} işlem, {a["net_pnl"]:+.2f} USDT net**, özsermaye maksimum düşüşü **{a["max_equity_drawdown_usdt"]:.2f} USDT**; başlangıç tek kasa $1000.',
       f'- Aynı yeni saat/cüzdanda eski v9.3 kuralları: **{old["trade_count"]} işlem, {old["net_pnl"]:+.2f} USDT net**. Yeni-eski fark **{a["net_pnl"]-old["net_pnl"]:+.2f} USDT**.',
       f'- Paper aktif hedefi 900s; toplam {live["elapsed_sec"]:.2f}s, drenaj {live["drain_elapsed_sec"]:.2f}s. Kapanmış net {live["closed_net_pnl"]:+.4f}, açık brüt {live["unrealized_pnl"]:+.4f}, özsermaye farkı {live["net_pnl"]:+.4f} USDT.',
       f'- Regresyon testleri: **{tests}**. Kaynak/veri bütünlüğü doğrulandı; 13 işlem/risk/çıkış/yönlendirme/replay dosyası önceki v9.4 donmasıyla byte-byte aynı.',
       '- **Canlı doğrulama eksik/degrade:** sıfır emir/dolum; Binance aggTrade sayacı 0 ve 133 hata, BBO verisi var. Genel healthy=true yalnız kotasyon güncelliğini gösterdiğinden tam işlem akışı sağlığı onayı değildir. Emir-yürütme hattı bu koşuda canlı dolumla sınanmadı.',
       '- Daha temiz mimari ve daha güvenilir ölçüm otomatik olarak pozitif beklenti sağlamaz. Negatif veya kabul dışı bir aday başarılı strateji olarak pazarlanmadı; test sonucu görüldükten sonra işlem parametresi değiştirilmedi.','',
       '## 2. Kullanıcının dört tablo incelemesi','',
       'Görsellerdeki altı kapının adetleri ve getirileri v9.3 kaydedilmiş JSON özetiyle birebir eşleşti. XLSX eki gelmedi; görseller ve kayıtlar karşılaştırıldı. Ayrıntı: `v941_user_tables_verified.json`.','',
       '- v9.3 kazanan %56.90; ortalama kazanan +1.12, kaybeden -3.26 USDT. Yaklaşık başa baş isabet %74.4; açık -17.5 **yüzde puan**. Yuvarlanan ortalamalardan tekrar hesaplanan beklenti hassas rapor değeriyle tam eşleşmeyebilir.',
       '- Net -88.82 USDT, brüt -48.25 ve ücret 40.57. Brüt yürütme fiyatlarından gelir ve kaymayı içerir; yalnız komisyonun tek neden olmadığı nettir, fakat sıfır sürtünmeli sinyal alfası bu sütundan tek başına ölçülemez.',
       '- Eski lider/genişlik ablasyonunda kapı kapatılınca CHOP/ATR filtresi geliyordu. Bu yüzden +25.71 USDT fark saf “kapıyı çıkar” etkisi değildi. Yeni MARKET ablasyonu başka kapı eklemez. Ortak upstream özellikleri nedeniyle yeni kollar da tam ortogonal nedensel deney değildir.',
       '- “Benzersiz örnek” olgunlaşmış 15m n değildir. Eski rapor bu paydayı ve yön başına ileri getiriyi tutmadığından bunlar geriye dönük güvenilir biçimde doldurulamaz; CI uydurulmadı.',
       '- “Kârlı sinyali engellemiş / doğru engellemiş” yerine **pozitif/negatif işaretli getiri ipucu** kullanılır. Bu bir dolum, stop-yolu net kârı veya nedensel kapı etkisi değildir.','',
       '### Maliyet aritmetiği (eski altı kapı; ileri getiri, işlem neti değil)','',
       'Round trip komisyon 7bps; 8bps/yön kayma toplam 16bps. Böylece **23bps, spread ve funding hariç**. Referans spread 1.5bps eklenirse 24.5bps.','',
       '| Eski kapı | Rapordaki benzersiz alan | Olgunlaşmış 15m n | İşaretli brüt bps | 23bps sonrası senaryo |','|---|---:|---|---:|---:|']
    verified=json.loads((R/'v941_user_tables_verified.json').read_text())
    csvrows=[]
    for x in verified['rows']:
        ret=x['blocked_signal_15m_signed_bps']
        lines.append(f'| {x["gate"]} | {x["sampled_unique"]} | Bilinmiyor / kaydedilmedi | {ret:+.2f} | {ret-23:+.2f} |')
        csvrows.append({'kapi':x['gate'],'engellenen_LONG_ham_tekrar':x['blocked_long'],'engellenen_SHORT_ham_tekrar':x['blocked_short'],
          'rapordaki_ornek_alani_olgunlasmis_dogrulanmadi':x['sampled_unique'],'olgunlasmis_15m_n':'BILINMIYOR',
          'isaretli_brut_15m_bps':ret,'23bps_sonrasi_senaryo_spread_funding_haric':ret-23,'yorum':'Firsat maliyeti ipucu; gerceklesen islem kari veya nedensel etki degil'})
    with (R/'v941_v93_kapi_tablosu_dogrulanmis.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(csvrows[0]));w.writeheader();w.writerows(csvrows)
    lines+=['','+44/+45bps olan iki ortalama maliyeti aşabilir; bilinmeyen olgunlaşmış payda, seçim yanlılığı, stop yolu ve dolum yokluğu nedeniyle bunlardan da kapı kaldırma kararı çıkmaz.','',
       '## 3. On uzmanlık açısından tartışma ve uygulanan değişiklikler','',
       'On bağımsız yapay zekâ/LLM çalıştırıldığı iddia edilmez. Tek asistan veri, istatistik, sinyal, emir akışı, rejim, çıkış, risk, yürütme, muhasebe ve operasyon açısından karşı görüşlü denetim yaptı. Ayrıntılı itiraz/karar tablosu: `v94_on_uzman_inceleme_ve_kararlar.md`.','',
       'v9.4 geliştirmesinde: kapanmış mum değişmezliği; ortak kapalı-mum çekirdeği; eksiksiz HTF; gerçek taker verisi; sentetik spot BBOyu futures gibi kullanmama; ATR taktik stop ve R/ATR takip; toplam ve yönlü stop-risk bütçesi; tek $1000 kasa; sonraki açılış dolumu; giriş-bar stop; aynı barın sonraki çıkış gelirini önceki açılışta harcamama; funding/işlem neti uzlaştırması.','',
       'Bunlar doğruluk ve risk hipotezleridir, kanıtlanmış pozitif edge değildir. $50/10x sabit kalır. Stop-bazlı açık risk bütçesi toplam drawdown limiti değildir; tekrar eden küçük kayıplar birikebilir. Çok yakın stoplar maliyet/whipsaw sorununu büyütebilir.','',
       '### Önceden sınırlanan geliştirme adayları','', '| Aday | İşlem | Net USDT | Özsermaye DD |','|---|---:|---:|---:|']
    for k,x in dev['candidates'].items():
        z=x['result'];lines.append(f'| {k} | {z["trade_count"]} | {z["net_pnl"]:+.2f} | {z["max_equity_drawdown_usdt"]:.2f} |')
    lines+=['',f'Seçilen {dev["selected"]}: yalnız geliştirme netine göre daha az kaybeden aday. Her iki aday negatif; eski v9.3 holdout artık geliştirme verisi ve yeniden OOS diye sunulmadı.','',
       '## 4. Test başlamadan dondurulan plan','',
       f'- Donma (UTC): **{m["frozen_at_utc"]}**.',
       f'- Tarihsel test: **{stamp(v["test_start_ms"])} — {stamp(v["test_end_ms"])}**, 8 × 4200 test barı, öncesinde 600 ısınma barı.',
       '- Eski görüntüyle en az bir günlük boşlukla ayrık tarihsel blok; geliştirme tarihinden ÖNCE yer alır. Bu nedenle tam bağımsız prospektif/kronolojik ileri-OOS veya rolling walk-forward değildir.',
       '- Önceki v9.4.0 süreçleri kayboldu ve tamamlanmış sonuç kaydedilmedi; kesintili oturum başarılı test sayılmadı. Arşivde kod zipi, donma kaydı ve kısmi kayıtlar var.',
       '- v9.4.1 kabul ölçütleri v9.3/kullanıcı incelemesinden etkilenmiştir. Önceki kesilmiş süreç bazı kaydedilmemiş hesaplar yapmış olabilir; tamamlanmış sonuç incelenip parametre ayarlaması yapılmadı. Doğrulayıcı bağımsız deney iddiası yoktur.',
       f'- Mühürlü veri SHA-256: `{m["sealed_data"]["sha256"]}`.','',
       '### Sabit başarı ölçütleri','', '```json',json.dumps(m['success_criteria_before_restart'],indent=2),'```','',
       'Araştırma adayı: en az 100 kapalı işlem; baz ve önceden seçilen bütün stres kollarında pozitif net; maksimum özsermaye DD ≤ $50; en az 10 UTC günlük bloktan ortalama günlük net için nominal %95 alt sınır > 0; funding verisi tam. Her durumda gerçek para için otomatik onay yok.','',
       'Kapı-yön için: en az 50 olgunlaşmış örnek, 3 sembol, 10 UTC günü. Olmazsa CI hesaplanmaz. Pozitif fırsat maliyeti bayrağı, stres sonrası çoklu-düzeltilmiş alt sınır > +1bps gerektirir; bu da otomatik kapı kaldırma kararı değildir.','',
       '## 5. Tarihsel doğrulama sonuçları','', '| Kol | İşlem | Brüt | Ücret | Funding maliyeti | Net USDT | Özsermaye DD |','|---|---:|---:|---:|---:|---:|---:|']
    for name,x in v['arms'].items():
        lines.append(f'| {name} | {x["trade_count"]} | {x["gross_pnl"]:+.2f} | {x["fees"]:.2f} | {x["funding_cost"]:+.2f} | **{x["net_pnl"]:+.2f}** | {x["max_equity_drawdown_usdt"]:.2f} |')
    pci=v['portfolio_daily_change_ci_usdt']['ci_95']
    lines+=['',f'- v9.4.1 isabet %{a["win_rate_pct"]:.2f}; ortalama kazanan/kaybeden {fmt(meanwin)} / {fmt(meanloss)} USDT; işlem başına {fmt(float(p.mean()) if len(p) else None)} USDT.',
       f'- Daha az toplam kayıp, daha güçlü edge demek değildir: yeni/eski işlem başına net {a["net_pnl"]/a["trade_count"]:+.3f} / {old["net_pnl"]/old["trade_count"]:+.3f} USDT; profit factor {a["profit_factor"]:.3f} / {old["profit_factor"]:.3f}. İşlem adedi de çok farklıdır.',
       f'- Toplam net farkın muhasebe ayrışımı: brüt fark {a["gross_pnl"]-old["gross_pnl"]:+.2f}, ücret tasarrufu {old["fees"]-a["fees"]:+.2f}, funding farkı {old["funding_cost"]-a["funding_cost"]:+.2f} USDT. Bu bir nedensel alfa ayrıştırması değildir.',
       f'- Ortalama kazanan/kaybedenle yaklaşık başa baş isabet %{100*abs(meanloss)/(meanwin+abs(meanloss)):.2f}; gözlenen isabet bunun altındadır.',
       f'- Günlük ortalama netin iki günlük blok CI %95 (USDT/gün): {fmtci(pci["net_base_bps"] if pci else None)}.',
       f'- Cüzdan neti − işlem neti: {a["net_pnl"]-a["trade_net_sum"]:.10f} USDT.',
       f'- Funding durumu: `{json.dumps(v["funding_status"])}`. Settlement mark yerine 5m açılışı kullanılır; yaklaşıktır.',
       '- v9.3 karşılaştırması eski kuralları aynı yeni ortak saat ve cüzdanda çalıştırır; önceki teslimin birebir tekrarı değildir. Risk bütçesi/strateji birlikte değişmiştir; fark saf alfa katkısı değildir.',
       '- no_fee_no_slippage_funding_on teşhisinde fee/kayma sıfır, funding ve karar içindeki maliyet başlığı kapısı aynı kalır. Feeye bağlı çıkış tabanı/dolum yolu da etkilenebilir; aynı sabit işlem listesinden ücret çıkarma işlemi değildir.',
       '- Bu kolda bile net negatif: sorun yalnızca komisyon değildir. Yeni adayın daha az kaybetmesi kârlılık kanıtı değildir.',
       '- MARKET ablasyonunun aynı çıkması yalnız bu örneklemde ek portföy farkı gözlenmediğini gösterir; evrensel gereksizlik kanıtı değildir. TREND/FLOW ve çıkış ablasyonları yol-bağımlı portföy karşılaştırmalarıdır; geleceğe taşınan kesin nedensel katsayılar değildir.','',
       '### Önceden yazılan kabul kontrolleri','', '```json',json.dumps(v['success_checks'],indent=2),'```','',
       '### Yeni adayın çıkış ve sembol dökümleri','', '| Tür | Grup | İşlem | Net USDT |','|---|---|---:|---:|']
    for field in ('reason','symbol'):
        groups=defaultdict(list)
        for t in a['trades']:groups[t[field]].append(t['realized_pnl'])
        for group,values in sorted(groups.items()):lines.append(f'| {field} | {group} | {len(values)} | {sum(values):+.2f} |')
    lines+=['','## 6. Ayrı yönlü kapı-cohort denetimi','',
       '**Kapsam:** önceden tanımlanan üç aile TREND (HTF/etkinlik/RSI/uzama), FLOW ve MARKETtir. Veri kalitesi/tazelik, gerçek taker, spread, yerel yön tanımı, tetik, ATR-risk ve maliyet başlığı hard kontrolleri kaldırılmadı; bunların her biri için ayrı ileri-getiri CI deneyi yapılmış değildir. Eski altı kapının olgunlaşmış paydası da bilinmiyor. Bu rapor “bütün eski/yeni ret nedenlerine CI hesaplandı” iddiası taşımaz.',
       'SINGLE_BLOCKER: yalnız ilgili TEK aile kaldırıldığında diğer bütün giriş koşullarını geçen aday. Yerine başka filtre konmaz. Gelecek fiyatlar yalnız etiket/rapor için okunur; işlem kararına/parametre seçimine verilmez. BASE_ACCEPTED_REFERENCE randomize veya eşleştirilmiş nedensel kontrol değildir.','',
       '| Cohort | Yön | Benzersiz | 15m olgun | Sansürlü | Brüt bps | 24.5bps sonrası | En kötü MAE bps | Taktik / %8 temas |','|---|---|---:|---:|---:|---:|---:|---:|---|']
    for group,sides in g['summary_by_side'].items():
        for side,x in sides.items():lines.append(f'| {group} | {side} | {x["unique_symbol_bar_n"]} | {x["matured_15m_n"]} | {x["censored_15m_n"]} | {fmt(x["mean_gross_mark_return_bps"])} | {fmt(x["mean_stress_8bps_per_side_mark_return_bps"])} | {fmt(x["worst_bar_mae_bps"])} | {x["initial_tactical_stop_barrier_touches"]} / {x["emergency_8pct_barrier_touches"]} |')
    lines+=['','### Güven aralıkları: 8bps/yön maliyet senaryosu sonrasında','',
       '| Cohort | Yön | n / sembol / gün | Nominal %95 CI | Altı karşılaştırma düzeltilmiş CI | Durum |','|---|---|---|---|---|']
    for group,sides in g['summary_by_side'].items():
        for side,x in sides.items():
            c=x['confidence'];reg=c['ci_95'];adj=c['simultaneous_familywise_95_ci']
            lines.append(f'| {group} | {side} | {c["matured_n"]} / {c["distinct_symbols"]} / {c["distinct_utc_days"]} | {fmtci(reg["net_stress_bps"] if reg else None)} | {fmtci(adj["net_stress_bps"] if adj else None)} | {c["status"]} |')
    lines+=['','SINGLE_BLOCKER_MARKET satırları ham audit JSONunda bulunmuyorsa bu renderer onları sıfır n / yetersiz kanıt olarak açıkça gösterir; yeni gözlem icat etmez. Tarihsel audit her sembol-kapalı mum için bir kez bakar: burada benzersiz cohort sayısı ilgili cohort ham kayıt sayısına eşittir, canlıdaki tekrar eden kapı sayacıyla karıştırılmaz.','',
       'İki günlük hareketli blok bootstrap bütün sembolleri aynı UTC gününde birlikte kümeler. Üç kapı × iki yön için nominal Bonferroni aile düzeltmesi vardır. Kısa seri, rejim değişimi ve durağanlık varsayımı nedeniyle aralıklar betimleyicidir; kesin anlamlılık/kausalite iddiası yoktur. Ufuklar örtüşür. Başlangıç bariyerine temas, gerçek maker dolumu veya dinamik takip stopuyla gerçekleşecek işlemin tam sonucu değildir.','',
       '## 7. 15 dakika canlı veri / PAPER sonucu','',
       f'- Faz {live["phase"]}; aktif hedef 900s, toplam {live["elapsed_sec"]:.2f}s, drenaj {live["drain_elapsed_sec"]:.2f}s.',
       f'- Kapalı işlem **{live["closed_count"]}**; kapalı brüt **{live["gross_pnl"]:+.4f}**, kapalı net **{live["closed_net_pnl"]:+.4f} USDT**.',
       f'- Açık pozisyon **{len(live["open_positions"])}**; gerçekleşmemiş brüt **{live["unrealized_pnl"]:+.4f} USDT**.',
       f'- Ödenmiş ücret {live["total_fees"]:.4f}; equity **{live["equity"]:.4f}**, başlangıca fark **{live["net_pnl"]:+.4f} USDT**.',
       '- **Akış kusuru:** Binance BBO 1,773,328 güncelleme, aggTrade 0, hata 133. OKX BBO 427,665, işlem ticki 70,112, hata 0. Her iki venue kotasyon almış olsa da tam çift-venue trade-tape/yürütme doğrulaması geçmedi.',
       '- **Sağlık alanı kör noktası:** JSONdaki genel healthy=true BBO güncelliğiyle birlikte oluşuyor; sıfır işlem akışını sağlıklı kanıtlamaz. Donmuş runner değiştirilmedi. Kök neden bu deneyde giderilmiş/doğrulanmış sayılmaz. Ayrı yeni sürüm ve yeni donmayla onarım gerekir.',
       '- Gerçek emir gönderilmedi. Sıfır/az işlem veya pozitif birkaç paper işlem kârlılık kanıtı değildir. Bu tek gün testi 10 UTC günü gate-CI koşulunu karşılayamaz.','',
       '```json',json.dumps({'venues':live['venues'],'venue_trade_counts':live['venue_trade_counts'],'maker_queue':live['analytics']['maker_queue'],
          'operational_health':live['analytics']['operational_health'],'observer_errors':live.get('measurement_v941',{}).get('observer_errors',[])},ensure_ascii=False,indent=2),'```','',
       '## 8. Kural değişmezliğinin SHA-256 kanıtı','', '| Dosya | v9.4.0 = v9.4.1 SHA-256 | Aynı |','|---|---|---|']
    live_table=['### Canlı kapı adetleri — ham, benzersiz ve olgunlaşmış ayrı','',
        '| Kapı | Yön | Ham | Benzersiz | Olgun 5m | Olgun 15m | Bekleyen 15m | Pencere kaçırılmış 15m | En kötü 15m MAE bps | %8 temas |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    lg=live.get('measurement_v941',{}).get('gate_cohorts',{}).get('gate_asymmetry_and_forward_returns',{})
    for group in ('SINGLE_BLOCKER_TREND','SINGLE_BLOCKER_FLOW','SINGLE_BLOCKER_MARKET'):
        z=lg.get(group,{})
        for side in ('LONG','SHORT'):
            x=z.get('by_side',{}).get(side,{});h=x.get('15m',{});h5=x.get('5m',{})
            live_table.append(f'| {group} | {side} | {z.get("blocked_"+side.lower(),0)} | {x.get("retained_unique",0)} | {h5.get("matured_observed_n",0)} | {h.get("matured_observed_n",0)} | {h.get("pending_n",0)} | {h.get("missed_or_unobserved_n",0)} | {fmt(h.get("observed_worst_mae_bps"))} | {h.get("observed_emergency_8pct_barrier_touches",0)} |')
    live_table+=['','Gözlemci hataları JSON bölümünde gösterilir. 15m ufku dolmamış cohortlara son fiyatla 15m etiketi verilmedi. Pencere içindeki gözlem bekleyenleri ayrıntılı JSONda ayrıca bulunur. Tek günlük canlı örnek için tüm CI sonuçları yetersiz kanıttır.','']
    ix=lines.index('## 8. Kural değişmezliğinin SHA-256 kanıtı');lines[ix:ix]=live_table
    with (R/'v941_kural_hash_karsilastirmasi.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['dosya','v94_0_sha256','v94_1_sha256','ayni'])
        for name,proof in m['source_equality_proof'].items():
            lines.append(f'| {name} | `{proof["v94_1_sha256"]}` | {proof["identical"]} |')
            w.writerow([name,proof['v94_0_sha256'],proof['v94_1_sha256'],proof['identical']])
    lines+=['','İşlem kodu temeli 9.4.0, paket sürümü 9.4.1. Değişen katmanlar: ayrı ölçüm gözlemcisi, istatistik, test/rapor araçları ve metadata. Orijinal karar nesnesi değiştirilmez. Ek CPU süresi nedeniyle canlı zamanlamanın birebir aynı olduğu iddia edilmez.','',
       '## 9. Son karar ve sonraki adım','',
       f'**{v["decision"]}. Gerçek para onayı: FALSE.**','',
       '- Yeni aday negatif veya kabul dışıysa performans yükseltmesi olarak terfi ettirilmez. Ölçüm altyapısının doğrulanması strateji edge kanıtı değildir.',
       '- Aynı test üzerinde yeni eşik/stop ayarı yapıp tekrar “OOS” denmedi; kazanan sembol veya yön sonradan seçilmedi.',
       '- Sonraki strateji deneyi ancak yeni, ayrıca dondurulmuş hipotez ve yeni veriyle yapılabilir. Önce entry edge ile çıkış etkisini ayrıştıran kontrollü deney ve daha uzun prospektif paper gerekir.',
       '- Stop-bazlı risk, gap, likidite çöküşü, ortak piyasa faktörü ve tekrarlayan zararlardan oluşan toplam düşüşü garantiyle sınırlamaz.',
       '- Miras paper muhasebesi marjı aşan gap kaybını likidasyonla sınırlar; gerçek cross kaybı daha yüksek olabilir. Sabit sembol seçimi survivorship yanlılığı taşır.',
       '', '## Kanıt dosyaları','',
       '`v94_historical_validation.json`, `v941_gate_cohort_audit.json`, `v94_freeze_manifest.json`, `v94_development_results.json`, `v94_canli_15dk_summary.json`, `v94_pytest.txt`, doğrulanmış CSV tabloları ve kesintili oturum arşivi.','']
    out=R/'v941_nihai_detayli_rapor.md';out.write_text('\n'.join(lines),encoding='utf-8')
    print(out)
    print(json.dumps({'decision':v['decision'],'base_net':a['net_pnl'],'old_rules_new_clock_net':old['net_pnl'],'live_closed_net':live['closed_net_pnl'],'live_equity_delta':live['net_pnl']},indent=2))

if __name__=='__main__':main()
