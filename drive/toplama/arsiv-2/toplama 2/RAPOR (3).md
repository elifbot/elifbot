# Yeni 10 dakikalık PAPER denemesi — v9.4.5

**Sonuç: 4 dolan giriş; 0 kapanış kaydı; 4 açık pozisyon.**

**Mevcut kurallar test edildi. Kilit gevşetme / yeniden-deneme değişikliği uygulanmadı. Gerçek borsa emri yok.**

**Operasyonel koşu durumu: DISCONTINUOUS. Süre hedefinin dolması süreklilik kabulü değildir.**

## 1. Protokol ve tamamlanma

- Plan UTC: 2026-11-03T12:11:24.340199+00:00; yeni boş DB başlangıçtan önce doğrulandı. Console ilk mutabakat clean_empty_db kaydını içerir.
- Konteyner Türkiye saati: 03.11.2026 15:11:29 → 03.11.2026 15:23:38.
- Runner: **DISCONTINUOUS**, exit code 0; active_window_completed=True; neden=drain_limit_with_open_positions.
- Hedef aktif süre 600s; son monotonic−drenaj tahmini 600.559903s (final raporlama overheadini de içerir; tam aktif çıkış zamanı değildir). Drenaj 120.000169s; monotonic toplam 720.5600720370057. Drenaj hedefi en fazla 120s; scheduler hassasiyeti nedeniyle matematiksel katı üst sınır iddiası yok.
- Önceki açık pozisyonlar devralınmadı. Zorla işlem / zorla kapanış / hedef sayıya ulaşmak için süre uzatma yapılmadı.
- Aynı Docker imajı: `sha256:e20310f7201f973f750d51fc05e5ade87476750e414ea1198a6eb1910e59813d`. 100 kaynak hash ve config değişmezliği tekrar doğrulandı. Bu koşuda pytest veya Docker build yeniden yapılmadı; önceki regresyon sonuçları yeni sonuç diye sayılmadı.

## 2. Kaç işleme girdi?

| Ölçüm | Sayı |
|---|---:|
| Maker kuyruk emir denemesi (submitted) | 5 |
| Maker filled | 4 |
| Maker partial_filled | 0 |
| Dolmadan süresi biten | 1 |
| Post-only reddi | 0 |
| Son açık bekleyen emir | 0 |
| OPEN giriş journal kaydı | 4 |
| Engine entries_routed | 4 |
| Kapanış kaydı | 0 |
| Açık pozisyon | 4 |
| Dolan giriş LONG / SHORT | 4 / 0 |

Emir denemesi, dolum, giriş journal kaydı ve kapanış farklı sayaçlardır. Kapanış kaydı kısmi kapanış da içerebilir; tek başına tam döngü kanıtı değildir. Dolum sayısı düşükse gerçekleşme güvenilirliği çıkarılamaz.

### Dolan girişler

| Sembol | Yön | Venue | Giriş operation_id |
|---|---|---|---|
| BTC/USDT | LONG | binance | d7ac2639b276488099fcd8300373bdca |
| UNI/USDT | LONG | okx | fbeaa8a5cda2471d8b95a50ef41bf2c1 |
| LINK/USDT | LONG | binance | 18910948a46e41699d7a428d0b87864a |
| APT/USDT | LONG | binance | 74eb751c5759467786e56ecc705273dc |

## 3. Finansal fotoğraf

| Ölçüm | USDT |
|---|---:|
| Bakiye | 999.60001952 |
| Equity | 1008.92146407 |
| Equity farkı | 8.92146407 |
| Kapanmış net PnL | 0.00000000 |
| Açık brüt unrealized | 9.32144455 |
| Ödenmiş toplam ücret | 0.39998048 |
| Funding | 0.00000000 |

Açık unrealized kapanmış sonuç değildir; ilerideki çıkış maliyetlerini içermez. Açık pozisyonların giriş ücretleri bakiyeden düşmüş olabilir. Küçük bir PAPER fotoğrafı kârlılık veya gerçek emir kalitesi kanıtı değildir.

## 4. Açık yoğunluk ve çıkışlar

- Brüt mark nominali 2009.223826 USDT; toplam marj 200.000000 USDT. Stop bütçesi maksimum zarar garantisi değildir; gap/slippage/gelecek ücretler ve korelasyon hariçtir.

| Sembol | Yön | Mark nominal USDT | Stop | Mark→stop % | Mark→stop USDT |
|---|---|---:|---:|---:|---:|
| BTC/USDT | LONG | 501.652162 | 76871.30545000 | 0.678256 | 3.402485 |
| UNI/USDT | LONG | 502.628121 | 7.17693788 | 1.246125 | 6.263374 |
| LINK/USDT | LONG | 502.684203 | 11.20088883 | 0.316924 | 1.593127 |
| APT/USDT | LONG | 502.259340 | 0.61660371 | 0.939238 | 4.717412 |
- Kapanış yok; çıkış mekanizması, tutulma süresi ve kapanmış işlem MAE bu koşuda test edilmedi.

Süreç durduğundan açık PAPER pozisyonlar artık izlenmiyor. Bu DB yeni koşuya taşınmamalı.

## 5. Sağlık ve süreklilik

- HTTP cevapları: {'200': 658, '503': 32}; toplam sorgu hatası 8 (summary sonrası cleanup hataları 0 ayrı). Tüm ham hatalar SONUC.json ve varsa errors.jsonl içinde tutulur.
- Hata türleri: {'http': 6, 'state': 2}. HTTP sağlık timeoutları ile /api/state timeoutları ayrı sayılır.
- Örneklenen sağlık kontrollerinin hatasızlık/5s boşluk ölçütü: **False**. Sürenin COMPLETED olması bu ölçütü geçirmez. Çalışma sırasında hata sayısı 8; dış sağlık boşluğu >5s: True.
- Maksimum HTTP örnekleri arası boşluk: 13.885294854000676; observer final: FINISHED_SUMMARY_FOUND.
- Bu koşudaki yakalanan 503 yanıtlarının alarmları timeout_investigation.json içinde. RUN_DISCONTINUITY_DETECTED, supervisor süreksizlik bileşeninin alarmıdır; alttaki gecikmenin CPU/VM/ağ/başka iş kök nedenini veya tarihsel v942 503ünü kanıtlamaz.
- Dahili gap_count=1; task_failures={}; continuity_ok=False; alarmlar=['RUN_DISCONTINUITY_DETECTED']. Final cancelled task durumları planlı cleanup sonucu olabilir; hata tarihçesi ayrı tutulur.
- Sıkı ledger: `{"ok": true, "empty": false, "balance": 999.6000195236674, "expected_balance": 999.6000195236674, "total_fees_usdt": 0.3999804763326167, "total_funding_usdt": 0.0, "open_positions": 4, "closed_trades": 0}`.
- Canlı doğal PENDING/IN_FLIGHT örneği: True; HTTP eşleşme örnek sayısı 41. Son journal durumları SONUC.json içinde; ABSENT_NOT_PROOF_OF_CANCEL tek başına iptal kanıtı değildir.

| Akış | Tick | BBO | Hata | Trade tape sağlıklı |
|---|---:|---:|---:|---|
| binance | 142283 | 2651640 | 0 | True |
| okx | 149177 | 483891 | 0 | True |

## 6. Ret sayaçları

| İlk dönen neden | Ham çağrı | Görüldüğü farklı sembol–mum anahtarı |
|---|---:|---:|
| ONE_ATTEMPT_PER_CLOSED_BAR | 10630 | 200 |
| DRAIN_NO_NEW_ENTRY | 2232 | 72 |
| POSITION_WAIT_NEXT_CLOSED_BAR | 294 | 5 |
| STALE_SIGNAL_BAR | 206 | 11 |
| SPREAD_TOO_WIDE | 44 | 44 |
| NO_LOCAL_TREND | 36 | 36 |
| LOW_TREND_EFFICIENCY | 31 | 31 |
| INSUFFICIENT_REAL_FLOW | 31 | 31 |
| RSI_EXHAUSTION | 19 | 19 |
| DO_NOT_CHASE | 12 | 12 |
| CLOSED_HTF_DISAGREEMENT | 9 | 9 |
| REAL_TAKER_UNAVAILABLE | 8 | 8 |
| FLOW_CONFIRMED_RECLAIM | 4 | 4 |
| ATR_EXCEEDS_RISK_CAP | 3 | 3 |
| WAIT_FOR_RECLAIM_OR_BREAKOUT | 3 | 3 |
| LIVE_ENTRY_DRIFT | 2 | 2 |
| LEADERS_UNAVAILABLE_OR_STALE | 1 | 1 |
| EXECUTION_GUARD_OR_UNFILLED | 1 | 1 |
| HOLD_CONFIRMED_THESIS | 1 | 1 |

Ham tekrarlar kaçırılmış bağımsız sinyal değildir. Sembol–mum anahtarları da olgun/bağımsız ekonomik fırsat değildir; unique_signal_count hâlâ null. İlk dönen ret sonraki filtreleri gizleyebilir. Sonradan spreadin düzeldiği veya kârlı fırsat kaçtığı mevcut karar loglarından çıkarılamaz.

## 7. Sınırlar

- Bu, gevşetilmiş filtrelerin veya retry yamasının testi değildir. Mevcut sürümün yeni piyasa penceresindeki işlem sayısı ölçüldü.
- Önceki 2s timeout nedeni bilinmiyor. Bu koşuda da çalışma sırasında timeout varsa düzelmiş sayılmaz; timeout_investigation.json zaman korelasyonunu içerir. Görevlerin canlı olması sağlık isteğinin gecikmediğini kanıtlamaz.
- Thread-token yarışı, büyük gerçek ledger/API yükü, bridge/Compose dağıtımı ve olgun tekil sinyal altyapısı açık kalır.
- Host ağ modu kullanıldı; genel operasyonel hazırlık, sürekli erişilebilirlik veya gerçek para onayı YOK.
