# v9.4.4 — 10 dakikalık gerçek piyasa verili PAPER testi

Rapor UTC: 2026-11-03T11:18:43.696600+00:00

**Gerçek borsa emri gönderilmedi. Strateji/risk ayarı değiştirilmedi. Kârlılık veya gerçek para onayı yok.**

## 1. Süre, kaynak ve ortam

- Plan UTC: 2026-11-03T11:04:37.031589+00:00; başlangıçtan önce süre, kaynak, config ve örnekleme kaydedildi.
- Konteyner: 03.11.2026 14:05:16 → 03.11.2026 14:17:26 Türkiye saati.
- Aktif hedef 600s; gerçekleşen **600.142s**, drenaj **120.956s**, toplam **721.097s**.
- Drenaj üst sınırı 120s idi; gerçek süre 120.956s, **0.956s taşma** var. Bu, mevcut 1s poll döngüsünün sınır sonrasında uyanmasıyla uyumludur; katı 120s sınırı tam sağlandı denmedi.
- Durum: **COMPLETED**; runner phase=COMPLETED, ExitCode=0. Bot durmuş durumda.
- İmaj `sha256:2a6ab2c2e700db6cdc225fb32e54c3468e3a2c8afb76415aadd0434b17c633a3`; host ağ modu. Kaynak97 hashleri tekrar doğrulandı; config aynı. Bu test için yeni pytest çalıştırılmadı; önceki 140/140 sonuçları yeni test sayısına eklenmedi.

## 2. Sağlık ve süreklilik

- Gözlemci yanıtları: **{'200': 723}**, toplam 723. İlk 60s sonrası 644 yanıt, HTTP200 dışı 0.
- Toplam örnekleme hatası **1**, aktif başlangıçtan 60s sonrası/stop öncesi hata 1. Hatalar aşağıda ve ham dosyada saklıdır.
- En büyük sağlık örnekleri arası boşluk **4.730s**; gözlemci poll boşluğu **2.255s**. 5s üzeri gözlenen sağlık boşluğu: **False**.
- Kapsamı dar örneklenen bağlantı/sağlık kontrolleri: **False**. Bu sürekli erişilebilirlik veya genel operasyonel hazırlık onayı değildir.
- v9.4.4 içinde monotonic süre denetimi/supervisor henüz yok; burada dış gözlemci monotonic zamanlarıyla boşluklar ayrıca değerlendirildi. Bu, gelecekteki sandbox kesintilerini önleyen bir kod yaması değildir.

### Örnekleme hataları

```json
[
  {
    "observed_at_epoch": 1793704053.5867622,
    "observer_monotonic": 36615.882665559,
    "type": "http",
    "error": "TimeoutError('timed out')"
  }
]
```

## 3. Piyasa akışları

| Ölçüm | Binance | OKX |
|---|---:|---:|
| Tick | 71979 | 66135 |
| BBO | 1500636 | 366870 |
| Hata | 0 | 0 |
| aggTrade hatası | 0 | — |
| Son trade-tape sağlığı | True | True |

## 4. Doğal PAPER emir yaşam döngüsü

- Maker kuyruk: `{"submitted": 8, "filled": 8, "partial_filled": 0, "expired_unfilled": 0, "post_only_rejected": 0, "open_resting": 0, "fill_rate_pct": 100.0, "avg_wait_ms": 1015.5, "avg_unfilled_runaway_bps": 0.0}`.
- Açık pozisyon **7**; kapanış kaydı **1**; defter pozisyon kimlikleriyle doğrulanan ayrı tam kapanmış döngü **1**.
- Canlı genç/sahipli PENDING + HTTP200/IN_FLIGHT/reconciled=false: **True**. 33 örnekte 5 ayrı niyet kimliği; son journal durumları `pending_terminal_proof.json` içinde.
- PENDING kanıtı önceki sentetik probe değildir: gerçek piyasa veri akışı, değiştirilmemiş Executor, PAPER maker kuyruğu ve StateStore yolundan doğal oluştu. Hiçbir niyet/pozisyon/fiyat/yaş enjeksiyonu yapılmadı.
- Bu olaylar mevcut canlı PENDING davranışına ilişkin sınırlı doğrudan kanıttır; eski v9.4.2 503ünün kesin nedeni hâlâ geriye dönük kanıtlanmış değildir.
- Doğal tam giriş–kapanış döngüsü gözlendi: **True**. Drenaj sonunda kalan pozisyonlar zorla kapatılmadı; yeniden açılmadı. Son DB korunmuştur.
- Niyet operation_id ile position_id farklı kimliklerdir. Tam döngü kanıtı; tekil sembol/giriş miktarı, sonraki niyetlerin beklenen-durum metadata içindeki position_id, CLOSED kapanış niyeti, trade_history miktarı ve kalan pozisyonun yokluğunu birlikte eşleştirir. Ayrıntı full_cycle_proof.json içindedir.
- Kapanan döngünün kendi giriş PENDING HTTP anı yakalandı: **False**. Yakalanan PENDINGler diğer girişlere aittir; bütün aşamalar aynı kapanmış işlemde HTTP örneklemesine yakalandı denmedi.

## 5. Finansal sonuç — küçük örneklem

| Ölçüm | USDT |
|---|---:|
| Bakiye | 1000.64385040 |
| Equity | 1009.56192443 |
| Toplam equity farkı | +9.56192443 |
| Kapanmış net PnL | +1.34381556 |
| Açık unrealized PnL | +8.91807403 |
| Toplam ücret | 0.90026333 |
| Funding | 0.00000000 |
- Son salt-okunur sıkı ledger: `{"ok": true, "empty": false, "balance": 1000.6438504009365, "expected_balance": 1000.6438504009363, "total_fees_usdt": 0.9002633310268007, "total_funding_usdt": 0.0, "open_positions": 7, "closed_trades": 1}`. Snapshot test DBsi rapor paketindedir.
- Equity köprüsü: 1000 + kapanmış net 1.34381556 − hâlen açık pozisyonların ödenmiş giriş ücretleri 0.69996516 + açık brüt unrealized 8.91807403 = 1009.56192443 USDT (bu koşuda funding=0). Açık PnL gelecekteki çıkış maliyetini içermez.
- Bot durduğundan kalan PAPER pozisyonlar artık bu süreç tarafından izlenmiyor; equity/unrealized yalnız son anın fotoğrafıdır.
- Bu küçük örneklemden kârlılık, kazanma oranı güvenilirliği veya gerçek borsa dolum güvenilirliği çıkarılamaz. Açık PnL kapanmış sonuç değildir; önceki negatif tarihsel araştırma hükmü değişmez.

## 6. Değerlendirme sayaçları

```json
{
  "evaluation_calls_total": 13886,
  "entry_retry_suppressed": 9759,
  "position_retry_suppressed": 1318,
  "retry_suppressed_total": 11077,
  "non_retry_evaluation_calls": 2809,
  "retry_suppression_pct": 79.77099236641222,
  "counter_consistent": true,
  "non_retry_reason_counts": {
    "INSUFFICIENT_REAL_FLOW": 29,
    "DO_NOT_CHASE": 9,
    "SPREAD_TOO_WIDE": 37,
    "NO_LOCAL_TREND": 27,
    "RSI_EXHAUSTION": 33,
    "WAIT_FOR_RECLAIM_OR_BREAKOUT": 3,
    "REAL_TAKER_UNAVAILABLE": 10,
    "LOW_TREND_EFFICIENCY": 21,
    "CLOSED_HTF_DISAGREEMENT": 11,
    "STALE_SIGNAL_BAR": 227,
    "HOLD_CONFIRMED_THESIS": 13,
    "ATR_EXCEEDS_RISK_CAP": 1,
    "DRAIN_NO_NEW_ENTRY": 2380
  },
  "unique_signal_count": null,
  "scope": "Call counters, NOT unique opportunities, mature cohorts, or independent signals",
  "strategy_policy_changed": false
}
```

- State örneklerinde değerlendirme sayacının aynı kaldığı en uzun gözlenen span 0.000s. Bu yeni bir görev supervisor/heartbeat ölçümü değildir.
- Tekrar korumaları ekonomik gate reddi ve bağımsız fırsat sayısı sayılmadı. unique_signal_count hâlâ null; olgun örneklem/karar kimliği altyapısı bu testte eklenmedi.

## 7. Nihai karar

- Süre protokolü: **COMPLETED**.
- Örneklenen bağlantı/sağlık kriterleri: **False**.
- Doğal canlı PENDING yanıtı: **True**.
- Doğal tam açılış–kapanış döngüsü: **True**.
- Görev denetimi, değerlendirme durması alarmı, dahili süreklilik durumu, thread-token yarışı, büyük gerçek defter yükü ve Docker bridge/Compose dağıtımı bu testle çözülmüş sayılmaz.
- Operasyonel hazırlık / gerçek para onayı **YOK**. Sinyal/stop/çıkış/filtre ayarı ve otomatik tekrar koşusu yapılmadı.
