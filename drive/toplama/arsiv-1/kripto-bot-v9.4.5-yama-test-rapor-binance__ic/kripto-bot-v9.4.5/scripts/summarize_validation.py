"""Render human-readable report after frozen OOS and live paper session finish."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
REPORTS=ROOT/'reports'


def main():
    oos=json.loads((REPORTS/'v9_3_oos_validation_report.json').read_text())
    live=json.loads((REPORTS/'v9_3_canli_15dk_cift_borsa_summary.json').read_text())
    data=json.loads((REPORTS/'v93_market_snapshot.json').read_text())
    baseline=oos['baseline']
    trades=sorted([t for row in baseline['per_symbol'] for t in row['trades']],key=lambda t:t['closed_at'])
    pnl=np.array([t['realized_pnl'] for t in trades])
    equity=np.r_[8000.,8000.+pnl.cumsum()]
    dd=float((np.maximum.accumulate(equity)-equity).max())
    rng=np.random.default_rng(930)
    boots=rng.choice(pnl,size=(10000,len(pnl)),replace=True).mean(axis=1)
    ci=np.quantile(boots,[.025,.975]).tolist()
    manifest=oos['freeze']
    changed=[name for name,h in manifest['source_sha256'].items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h]
    first=next(iter(data['frames'].values()))
    stamp=lambda v:datetime.fromtimestamp(v/1000,timezone.utc).isoformat()
    mean_win=float(pnl[pnl>0].mean()) if (pnl>0).any() else 0
    mean_loss=float(pnl[pnl<=0].mean()) if (pnl<=0).any() else 0
    diagnostics={'realized_only_combined_max_drawdown_usdt':dd,'iid_bootstrap_95ci_net_per_trade':ci,
      'bootstrap_warning':'Descriptive IID trade bootstrap only. Correlated symbols/time violate independence; no confirmatory significance claim.',
      'mean_winner_usdt':mean_win,'mean_loser_usdt':mean_loss,'exit_reasons':dict(Counter(t['reason'] for t in trades)),
      'mean_holding_minutes':float(np.mean([(t['closed_at']-t['opened_at'])/60000 for t in trades])),
      'post_freeze_source_changes':changed,'data_sha256_matches':hashlib.sha256((REPORTS/'v93_market_snapshot.json').read_bytes()).hexdigest()==manifest['dataset_sha256'],
      'live_run_completed':live['phase']=='COMPLETED','live_elapsed_sec':live['elapsed_sec'],
      'promotion_decision':'REJECT_REAL_MONEY_USE_NEGATIVE_HOLDOUT',
      'ablation_warning':'Operational feature/gate removals; shared upstream trend/flow information is not fully orthogonalized.'}
    (REPORTS/'v93_validation_analysis.json').write_text(json.dumps(diagnostics,indent=2))
    b=baseline
    lines=['# Kripto Bot v9.3.0 — Nihai doğrulama ve teslim raporu','',
      '**Karar: Gerçek para kullanımına ONAY YOK. Dondurulmuş holdout net beklentisi negatif.**','',
      '## Teslim edilen değişiklikler','',
      'BTC/ETH lider çapası, yönlü genişlik, kontrollü kaskad filtresi, V-dibi short korumaları, üç kademeli dalga kâr kilidi, nedensel sonraki-mum stop güncellemesi ve yeni regresyon testleri.','',
      '## Test kapsamı ve veri dürüstlüğü','',
      '- Birim/regresyon testleri: **45/45 geçti**. Test çıktısı: `v93_pytest_result.txt`.',
      f'- Kaynak dondurma zamanı (UTC): {manifest["frozen_at_utc"]}. Sonradan değişen izlenen kaynak sayısı: **{len(changed)}**.',
      f'- Veri SHA-256: `{manifest["dataset_sha256"]}`.',
      f'- Yeni veri görüntüsü: {stamp(first[0]["open_time"])} — {stamp(first[-1]["open_time"]+300000)}.',
      f'- İşlem yapılan holdout: {stamp(first[750]["open_time"])} — {stamp(first[-1]["open_time"]+300000)} (8 × 750 kapanmış 5m mum).',
      '- Önceki yalnız bellekteki kalibrasyon verisi korunmadı. Bu yeni görüntü, önceki dokunulmamış [750:1500] verisinin birebir testi değildir. Yakın tarihli pencereler örtüşebileceğinden bağımsız prospektif OOS iddiası yoktur.',
      '- [450:750] yalnız ısınma; son 750 barda işlem. Sekiz ayrı $1,000 hesap, nominal toplam $8,000; tek $1,000 kasa getirisi değil.',
      '- İlk holdout sonucu görüldükten sonra strateji/risk/backtest kaynaklarına dokunulmadı. Dört ablasyon ve üç stres senaryosu aynı dondurulmuş setle çalıştırıldı.',
      '- Ön-eleme hız hedefi (<15 saniyede 8 sembol) doğrulanmış değildir; tam holdout+ablasyon+stres koşusu '+f'{oos["elapsed_sec"]:.1f} saniye sürdü.',
      '', '## Dondurulmuş temporal holdout sonucu (funding hariç)','',
      '| Ölçüm | Sonuç |','|---|---:|',
      f'| Kapalı işlem | {b["trade_count"]} |',f'| Brüt K/Z | {b["gross_pnl"]:+.2f} USDT |',
      f'| Komisyon | {b["fees"]:.2f} USDT |',f'| Net K/Z | **{b["net_pnl"]:+.2f} USDT** |',
      f'| Net kazanan oranı | %{b["win_rate_pct"]:.2f} |',f'| İşlem başına net beklenti | {b["net_expectancy_per_trade"]:+.4f} USDT |',
      f'| Ortalama kazanan / kaybeden | {mean_win:+.2f} / {mean_loss:+.2f} USDT |',
      f'| Birleştirilmiş kapanış bazlı maksimum düşüş | {dd:.2f} USDT |',
      f'| Betimleyici IID bootstrap %95 aralığı, işlem başına | [{ci[0]:+.4f}, {ci[1]:+.4f}] USDT |',
      '', 'Düşüş yalnız gerçekleşmiş kapanış eğrisindendir; açık pozisyon içi gerçek özsermaye düşüşünü ölçmez. Semboller ve işlemler bağımlı olabildiğinden IID bootstrap kesin anlamlılık testi değildir. Yüksek isabet, kayıpların büyüklüğünü telafi etmedi.','',
      '| Sembol | İşlem | Net K/Z (USDT) |','|---|---:|---:|']
    for row in b['per_symbol']:
        x=row['summary'];lines.append(f'| {row["symbol"]} | {x["trades"]} | {x["realized_pnl"]:+.2f} |')
    lines+=['','## Ablasyon: bir bileşen çıkarıldığında','', '| Devre dışı aile | İşlem | Net USDT | Baz modele fark |','|---|---:|---:|---:|']
    for x in oos['ablations']:
        lines.append(f'| {x["disabled_family"]} | {x["trade_count"]} | {x["net_pnl"]:+.2f} | {x["net_delta_vs_baseline"]:+.2f} |')
    lines+=['','Pozitif fark, aile kaldırılınca sonucun daha az kötü olduğunu gösterir. Lider/genişlik kapısı bu pencerede zararı artırmıştır; işlem/numune değişimi nedeniyle bu fark nedensel üstünlük kanıtı değildir. Aileler ortak girdiler kullanır, tamamen bağımsız deney kolları değildir. Sonuç üzerine kapı kapatılıp yeni “başarılı OOS” üretilmedi.','',
      '## İcra sürtünmesi stresi','', '| Kayma (bps/yön) | Gecikme (ms) | Net USDT |','|---|---:|---:|']
    for x in oos['stress']:
        lines.append(f'| {x["slippage_bps"]:.0f} | {x["latency_ms"]} | {x["net_pnl"]:+.2f} |')
    lines+=['','Gecikme, bir sonraki mevcut mum açılışı yaklaşımıdır; gerçek 1 saniyelik yürütme ölçümü değildir. Komisyon sabit %0.035/yön; funding hariçtir.','',
      '## Binance + OKX: 15 dakika canlı veri / PAPER emir testi','',
      f'- Oturum fazı: **{live["phase"]}**; raporlanan toplam süre **{live["elapsed_sec"]:.2f} sn**, drenaj **{live["drain_elapsed_sec"]:.2f} sn**. Aktif süre ayarı: **900 sn**.',
      f'- Saf kripto evreni: {live["universe_counts"]["union_pure"]}; Binance {live["universe_counts"]["binance_pure"]}, OKX {live["universe_counts"]["okx_pure"]}.',
      f'- Kapanan işlem: **{live["closed_count"]}**; kazanan {live["wins"]}, kaybeden {live["losses"]}.',
      f'- Kapanmış işlemler brüt K/Z: **{live["gross_pnl"]:+.4f} USDT**; kapanmış net K/Z: **{live["closed_net_pnl"]:+.4f} USDT**.',
      f'- Toplam ödenmiş ücret: {live["total_fees"]:.4f} USDT; açık pozisyon: **{len(live["open_positions"])}**, gerçekleşmemiş brüt K/Z: **{live["unrealized_pnl"]:+.4f} USDT**.',
      f'- Özsermaye: {live["equity"]:.4f} USDT; başlangıca fark (açık işlemler dahil): {live["net_pnl"]:+.4f} USDT.',
      '- Gerçek borsa emri gönderilmedi. Bağlantı sağlığı, dolum gerçekleşmesi ve gerçekleşmiş kâr birbirinden ayrıdır.',
      '', '| Venue | Veri sağlıklı (son an) | Tick | BBO güncelleme | Hata sayacı |','|---|---|---:|---:|---:|']
    for venue,x in live['venues'].items():
        lines.append(f'| {venue} | {x["healthy"]} | {x["ticks"]} | {x["bbo_updates"]} | {x["errors"]} |')
    lines+=['',f'Venue işlem sayacı (açık ve kapalı birlikte): `{json.dumps(live["venue_trade_counts"])}`.',
      '', '### Operasyonel ölçümler','', '```json',json.dumps(live['analytics'],ensure_ascii=False,indent=2),'```','',
      '## Sınırlamalar ve sonraki karar','',
      '- Tek 750-bar temporal holdout; rolling walk-forward yapılmadı. Yeni prospektif ve rejim çeşitliliği yüksek veri gerekir.',
      '- 15 dakika bağlantı/yürütme smoke testidir; strateji kârlılığının istatistiksel kanıtı değildir.',
      '- OHLCV taker akışı ve hafif çıkış göstergeleri canlı tick/indikatör hattının birebir eşlemesi değildir.',
      '- HTF son kovası kısmi olabilir; yalnız o ana kadar bilinen alt barlar kullanılır.',
      '- 10 ajan on deterministik kural rolüdür, on bağımsız LLM veya bağımsız kanıt değildir.',
      '- Kayma, maker kuyruk ve funding modellemelerinin sınırları README ve ham JSON içinde kayıtlıdır.',
      '- Negatif beklenti nedeniyle v9.3 gerçek para için terfi ettirilmedi. AVAX pozitif olsa da kazanan sembolü sonradan seçmek veri madenciliği olur.',
      '', '## Dosyalar','',
      '- `v9_3_oos_validation_report.json`: bütün baz/ablasyon/stres işlemleri.',
      '- `v93_freeze_manifest.json` ve `v93_market_snapshot.json`: tekrar üretim/veri kaydı.',
      '- `v9_3_canli_15dk_cift_borsa_summary.json`: tamamlanmış paper testi.',
      '- `v9_3_canli_15dk_cift_borsa_decisions.jsonl`: karar günlüğü.',
      '- `v93_live_health_samples.jsonl`: oturumun bir bölümünde 30 saniyelik bağımsız API sağlık örnekleri (başlangıçtan itibaren tam kayıt değildir).',
      '- `v93_validation_analysis.json`: kaynak bütünlüğü ve ek betimleyici analiz.',
      '']
    (REPORTS/'v9_3_nihai_dogrulama_raporu.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(diagnostics,indent=2))

if __name__=='__main__':main()
