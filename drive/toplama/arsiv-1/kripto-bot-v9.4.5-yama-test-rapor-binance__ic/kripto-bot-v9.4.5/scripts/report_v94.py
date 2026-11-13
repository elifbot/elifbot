"""Produce a candid Turkish evidence report; no parameter tuning here."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter,defaultdict
import json,hashlib
import numpy as np
from scripts.validate_v94 import integrity

ROOT=Path(__file__).resolve().parent.parent;R=ROOT/'reports'


def main():
    validation=json.loads((R/'v94_historical_validation.json').read_text())
    development=json.loads((R/'v94_development_results.json').read_text())
    live=json.loads((R/'v94_canli_15dk_summary.json').read_text())
    integrity(validation['freeze'])
    a=validation['arms']['v94'];old=validation['arms']['v93_on_corrected_clock']
    trades=a['trades'];pnl=np.array([t['realized_pnl'] for t in trades])
    avgwin=float(pnl[pnl>0].mean()) if (pnl>0).any() else 0
    avgloss=float(pnl[pnl<0].mean()) if (pnl<0).any() else 0
    reasons=defaultdict(lambda:{'count':0,'net':0})
    symbols=defaultdict(lambda:{'count':0,'net':0})
    for t in trades:
        for group,key in ((reasons,t['reason']),(symbols,t['symbol'])):
            group[key]['count']+=1;group[key]['net']+=t['realized_pnl']
    times=lambda ms:datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
    daily={}
    for point in a['equity_curve']:
        day=datetime.fromtimestamp(point['ts']/1000,timezone.utc).strftime('%Y-%m-%d')
        daily[day]=point['equity']
    daily_values=np.diff(np.r_[1000.,list(daily.values())])
    rng=np.random.default_rng(940)
    interval=np.quantile(rng.choice(daily_values,size=(10000,len(daily_values)),replace=True).mean(axis=1),[.025,.975]).tolist()
    diagnosis={'average_winner':avgwin,'average_loser':avgloss,'expectancy':float(pnl.mean()) if len(pnl) else None,
        'daily_block_bootstrap_mean_95ci':interval,'daily_count':len(daily_values),'exit_reasons':dict(reasons),
        'by_symbol':dict(symbols),'test_improvement_vs_corrected_legacy':a['net_pnl']-old['net_pnl'],
        'wallet_trade_reconciliation_error':a['net_pnl']-a['trade_net_sum'],
        'source_integrity':'UNCHANGED','approved_for_real_money':False}
    (R/'v94_diagnostics.json').write_text(json.dumps(diagnosis,indent=2))
    lines=['# Kripto Bot v9.4.1 — Detaylı inceleme, geliştirme ve doğrulama','',
        '**Gerçek para kullanımına onay yok. Bu sürüm PAPER araştırma adayıdır; kazanç garantisi verilmez.**','',
        '## 1. Ne yapıldı ve ne yapılmadı?','',
        'On bağımsız yapay zekâ çalıştırıldığı iddia edilmedi. Veri, istatistik, sinyal, akış, rejim, çıkış, risk, yürütme, muhasebe ve operasyon açısından karşı görüşlü inceleme yapıldı. Ayrıntılı görüşler: `v94_on_uzman_inceleme_ve_kararlar.md`. Eski 10 kural oylaması bu sürümün etkin karar hattında kullanılmıyor.','',
        'v9.3 kaybının ana nedeni: küçük kazananlar (+1.12 ortalama) karşısında daha büyük kaybedenler (-3.26). 39 ters-sinyal çıkışı -151.81 net; 66 kâr-kilidi çıkışı yalnız +64.78 net. Canlı sonundaki APR ve RUNE açık zararları kapanmış kazançları aşmıştı. Sadece daha çok gösterge/ajan veya kazanan sembolü seçmek çözüm sayılmadı.','',
        '### Uygulanan teknik değişiklikler','',
        '- Aynı kapalı-mum özellik ve karar çekirdeği canlı ve tarihsel replay tarafından kullanılıyor.',
        '- Ticker geçmiş kapanmış mumlara yazılmıyor; mark ayrı parametre. HTF yalnız tam ve eksiksiz 15m/1h kovalarından oluşuyor.',
        '- Gerçek Binance quote taker hacmi korunuyor. OKX nötr proxy gerçek akış sayılmıyor; eksik veride açık ret nedeni var.',
        '- Spot+perpAnchor sentetik BBO v9.4 futures yürütmesinden çıkarıldı; gerçek futures WS ve REST fiyatları kullanılıyor.',
        '- Açıklanabilir trend + akış teyitli reclaim/breakout; ters yönde yalnız ortak güçlü piyasa kanıtıyla veto.',
        '- ATR taktik stop ve ATR/R birimli kâr takibi; sabit küçük dolar kilidi yerine oynaklık ölçeği.',
        '- $50 sabit marj, 10x ve %8 acil risk tavanı korunuyor. Taktik stop daha yakın; dinamik kaldıraç/ekleme yok.',
        '- Açık taktik risk toplamı özsermayenin %2, tek yönde %1.5 sınırı; bu, gap kaybını veya korelasyonu tam modelleyen garanti değildir.',
        '- Tek $1000 cüzdan, ortak zaman çizgisi, sonraki açılış dolumu, giriş-bar stopu ve tüm kapanışlarda cooldown.',
        '- Aynı barın sonradan oluşan stop çıkışı, o barın daha önceki açılışına para sağlayamaz. Yeni MFE stopu geriye dönük uygulanmaz.',
        '- Tarihsel funding API verisi bulunduğu yerde settlement açılış-mark yaklaşımıyla ekleniyor; işlem neti ile cüzdan neti uzlaştırılıyor.','',
        '## 2. Önceden sınırlanan geliştirme deneyi','',
        'Önceki v9.3 1500 bar görüntüsü artık geliştirme verisi. [600:1500] aralığında yalnız A/B adayları denendi. Her ikisinin sonucu da aşağıda; en iyiyi saklayıp kötü denemeleri gizleme yok.','',
        '| Aday | İşlem | Net USDT | Maks. özsermaye düşüşü |','|---|---:|---:|---:|']
    for k,x in development['candidates'].items():
        r=x['result'];lines.append(f'| {k} | {r["trade_count"]} | {r["net_pnl"]:+.2f} | {r["max_equity_drawdown_usdt"]:.2f} |')
    lines+=['',f'Seçim: **{development["selected"]}**, yalnız geliştirme netine göre; eşitlikte düşük düşüş. İki aday da negatif olduğundan bu seçim üretime onay değildir. Seçilen parametreler:','',
        '```json',json.dumps(validation['freeze']['selected_policy'],indent=2),'```','',
        '## 3. Ayrık tarihsel doğrulama tasarımı','',
        f'- Kaynak/parametre dondurma (UTC): **{validation["freeze"]["frozen_at_utc"]}**.',
        f'- Test aralığı (UTC): **{times(validation["test_start_ms"])} — {times(validation["test_end_ms"])}**.',
        '- Sekiz sembol × 4,200 test barı; önceki 600 bar sadece ısınma. Ortak bitiş zamanlı 4,800 bar/sembol görüntüsü, geliştirme verisinden en az 1 gün boşlukla ayrık.',
        '- Bu tarihsel blok daha önce açılmamış olsa da geliştirme tarihinden ÖNCE yer alır. Bağımsız prospektif/kronolojik ileri-OOS veya rolling walk-forward diye sunulamaz.',
        f'- Mühürlü veri SHA-256: `{validation["freeze"]["sealed_data"]["sha256"]}`.',
        '- Mühür açılmadan önce kaynaklar, konfigürasyon ve A/B seçimi donduruldu. Sonuçlar görüldükten sonra izlenen kaynaklar değiştirilmedi.',
        '- v9.3 karşılaştırması aynı yeni saat/cüzdan üzerinde eski giriş/çıkış kurallarıdır. Eski teslimin birebir tekrar sonucu değildir. Risk bütçesi ve strateji değişiklikleri birlikte etkilenir; saf alfa katkısı diye okunamaz.','',
        '## 4. Doğrulama sonucu','',
        '| Kol | İşlem | Brüt USDT | Ücret | Funding maliyeti | Net USDT | Özsermaye DD |','|---|---:|---:|---:|---:|---:|---:|']
    for name in ('v94','v93_on_corrected_clock'):
        x=validation['arms'][name];lines.append(f'| {name} | {x["trade_count"]} | {x["gross_pnl"]:+.2f} | {x["fees"]:.2f} | {x["funding_cost"]:+.2f} | **{x["net_pnl"]:+.2f}** | {x["max_equity_drawdown_usdt"]:.2f} |')
    lines+=['',f'- Yeni-eski net fark: **{a["net_pnl"]-old["net_pnl"]:+.2f} USDT**; sermaye her kolda $1000.',
        f'- v9.4 isabet: %{a["win_rate_pct"]:.2f}; ortalama kazanan/kaybeden: {avgwin:+.2f}/{avgloss:+.2f} USDT; işlem başına net: {diagnosis["expectancy"]:+.4f} USDT.' if len(pnl) else '- v9.4 işlem üretmedi; olumlu edge kanıtı yok.',
        f'- Günlük portföy değişimleriyle betimleyici bootstrap %95 ortalama günlük net aralığı: [{interval[0]:+.2f}, {interval[1]:+.2f}] USDT. Gün sayısı {len(daily_values)}; küçük örnek ve seri bağımlılık nedeniyle kesin anlamlılık testi değildir.',
        f'- Cüzdan-net / işlem-net farkı: {diagnosis["wallet_trade_reconciliation_error"]:.10f} USDT.',
        f'- Funding veri durumu: `{json.dumps(validation["funding_status"])}`. Funding settlement fiyatı yerine 5m açılışı kullanılır; rate tam olsa bile fiyatlama yaklaşıktır.',
        '', '| Sembol | İşlem | Net USDT |','|---|---:|---:|']
    for s,x in sorted(symbols.items()):lines.append(f'| {s} | {x["count"]} | {x["net"]:+.2f} |')
    lines+=['','### Çıkış nedenleri','', '| Neden | İşlem | Net USDT |','|---|---:|---:|']
    for reason,x in reasons.items():lines.append(f'| {reason} | {x["count"]} | {x["net"]:+.2f} |')
    lines+=['','## 5. Dört ablasyon ve maliyet/gecikme stresi','', '| Kol | İşlem | Net USDT | v9.4 fark | DD |','|---|---:|---:|---:|---:|']
    for name,x in validation['arms'].items():
        if name in ('v94','v93_on_corrected_clock'):continue
        lines.append(f'| {name} | {x["trade_count"]} | {x["net_pnl"]:+.2f} | {x["net_pnl"]-a["net_pnl"]:+.2f} | {x["max_equity_drawdown_usdt"]:.2f} |')
    lines+=['','Ablasyonlar operasyonel kapı/çıkış kaldırmalarıdır; ortak özellikler nedeniyle tam bağımsız nedensel deneyler değildir. 3/8/15bps her yönde kayma kullanılır. Ek gecikme bir tam 5m bar daha bekletir; milisaniyelik mikro-yapı ölçümü değildir.','',
        '## 6. Dondurma sonrası 15 dakika canlı veri / PAPER testi','',
        f'- Faz: {live["phase"]}; toplam {live["elapsed_sec"]:.2f}s, drenaj {live["drain_elapsed_sec"]:.2f}s; aktif hedef 900s.',
        f'- Evren {live["universe_counts"]["union_pure"]}; son venue sağlıkları: Binance {live["venues"]["binance"]["healthy"]}, OKX {live["venues"]["okx"]["healthy"]}.',
        f'- Kapalı {live["closed_count"]} işlem: brüt {live["gross_pnl"]:+.4f}, net **{live["closed_net_pnl"]:+.4f} USDT**.',
        f'- Açık {len(live["open_positions"])} pozisyon: gerçekleşmemiş brüt **{live["unrealized_pnl"]:+.4f} USDT**.',
        f'- Toplam ödenmiş ücret {live["total_fees"]:.4f}; özsermaye {live["equity"]:.4f}; başlangıca fark (açık dahil) **{live["net_pnl"]:+.4f} USDT**.',
        '- Sıfır/az dolum başarının kanıtı değildir. İşlem sayısı artması veya isabet artışı tek başına kabul ölçütü değildir. Gerçek borsa emri gönderilmedi.',
        '', '### Canlı operasyon kaydı','', '```json',json.dumps({'venues':live['venues'],'venue_trade_counts':live['venue_trade_counts'],'maker':live['analytics']['maker_queue'],'health':live['analytics']['operational_health']},ensure_ascii=False,indent=2),'```','',
        '## 7. Son karar ve açık sınırlamalar','',
        f'**Makine karar kaydı: {validation["decision"]}. Gerçek paraya otomatik terfi yok.**','',
        '- Testlerde net pozitif sonuç çıksa bile, iki geliştirme adayının negatif olması ve testin retrospektif olması nedeniyle daha uzun prospektif paper doğrulaması gerekir.',
        '- Sekiz sembol seçimi hayatta-kalma/seçim yanlılığı taşır; canlı evrenle birebir aynı değildir.',
        '- Ortak çekirdek aynı mum kararını sağlar; canlı maker dolumu, spread ve tick stop yolunun OHLC ile birebir eşit olduğu iddia edilmez.',
        '- Risk bütçesi stop bazlıdır; boşluklar, likidite çöküşü ve ortak BTC faktörünün kuyruk riskini garantiyle sınırlamaz.',
        '- Miras paper muhasebesi marjı aşan gap kaybını likidasyonla sınırlar; gerçek cross-margin aşırı boşluk kayıpları daha yüksek olabilir.',
        '- En iyi sembolü/yönü testten sonra seçmek, yeni parametre üretip aynı bloğa tekrar “OOS” demek yapılmadı.',
        '- Sonraki adım: dondurulmuş modelle çok daha uzun ileriye dönük paper, farklı rejimlerde veri ve bağımsız risk incelemesi; kazanç garantisi veya yatırım tavsiyesi yok.','',
        '## 8. Kanıt dosyaları','',
        '- `v94_on_uzman_inceleme_ve_kararlar.md`: detaylı bulgu, itiraz ve kararlar.',
        '- `v94_development_results.json`: iki adayın tüm geliştirme sonuçları.',
        '- `v94_freeze_manifest.json`, `v94_sealed_data_metadata.json`, `v94_sealed_historical_holdout.json.gz`.',
        '- `v94_historical_validation.json`: bütün işlemler, equity eğrileri, ablasyon ve stres.',
        '- `v94_canli_15dk_summary.json`, `v94_canli_15dk_decisions.jsonl`, `v94_live_health.jsonl`.',
        '- `v94_pytest.txt`: birim/regresyon test çıktısı.','']
    (R/'v94_nihai_detayli_rapor.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(diagnosis,indent=2))
if __name__=='__main__':main()
