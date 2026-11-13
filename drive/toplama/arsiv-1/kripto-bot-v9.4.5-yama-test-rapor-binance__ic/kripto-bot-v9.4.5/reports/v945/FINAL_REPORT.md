# v9.4.5 Faz 1.5 — yama ve ikinci 10 dakikalık test

**Gerçek para onayı yok. Strateji/risk/ATR/çıkış/maker kuralları değiştirilmedi. Önceki 7 pozisyon devralınmadı; yeni boş defter kullanıldı.**

## A. Önceki PENDING kanıtının tamamlanması

| Sembol | OPEN gözlemi üst sınırı (s) | Sonraki RECONCILED gözlemi üst sınırı (s) |
|---|---:|---:|
| BTC/USDT | 0.570 | 6.147 |
| NEAR/USDT | 2.534 | 5.508 |
| WLD/USDT | 2.071 | 2.838 |
| SOL/USDT | 2.313 | 3.074 |
| ACU/USDT | 1.822 | 2.600 |

Beş niyetin hepsi 15s içinde terminal OPEN ve sonrasında mutabakat dönüşüyle gözlendi. Bunlar örnekleme üst sınırlarıdır, tam commit zamanı değildir. Art arda başka PENDINGler olduğundan RECONCILED gözlemi ilk niyetin commitinden daha geç olabilir. Ham eski health/pending ve son DB reports/v945/previous_live_proof/ içindedir.
**15 saniyelik PENDING toleransı önceki doğal canlı veride 5 niyette gözlendi. Eski v9.4.2 503ünün nedeni kesinleşmedi.**

## B. Eski zaman aşımı incelemesi

# Önceki v9.4.4 zaman aşımı incelemesi

Timeout kaydı UTC 11:07:33.586762. İstek 2s sınırında kaldığından yaklaşık
11:07:31.58 civarında başlatılmıştır. Çevresindeki başarılı sağlık cevapları
11:07:30.576 ve 11:07:35.306; kayıtlar arasında 4.730s boşluk var.
Çevredeki yanıtların defteri RECONCILED; ±10s içinde gözlenen PENDING olayı yok.
Beş dakikalık mum kapanışı 11:05/11:10 olduğundan tam kapanış anına denk gelmiyor;
bu durum sonraki değerlendirme/ısınma işini dışlamaz. 11:07:35.529da HOT paritesinin
terfi kaydı var. Yakınlık CPU blokajının sebebini kanıtlamaz.
Sunucu 11:07:34.193te gecikmiş /health 200 loglamış olabilir; request-id ile
istemci korelasyonu olmadığından bunun zaman aşımına uğrayan istek olduğu kesin değil.
Önceki sürümde health-render/analytics ve döngü gecikme profili olmadığından DB
kopyası, başka senkron hesap, VM scheduling ve istemci gecikmesi ayrıştırılamadı.
Kesin kök neden BELİRLENEMEDİ; PENDING kaynaklı dendiği de YOK. Yeni yamada
poll/duvar-saat sapması, değerlendirme hazırlık süresi ve health-render/analytics
süreleri kaydedilerek sonraki olayın ayrıştırılması kolaylaştırılır.

## C. Yama davranışı ve testler

- Altı ana task (universe, fast_quotes, Binance, OKX, candles, strategy_eval) denetlenir. Beklenmedik return/cancel/exception HTTP503 alarmı ve FAILED kapanış üretir; yeni girişler kesilir, açık pozisyonlar zorla kapatılmaz. Supervisor otomatik restart yapmaz; haricî Docker restart politikası ayrıdır.
- Değerlendirme çağrısı ilerlemezse 30s, tamamlanan strateji çevrimi heartbeat’i bayatlarsa 15s alarm. HOLD/tekrar değerlendirmesi de işleyen değerlendirmedir; düşük sinyal/işlem sayısı görev ölümü sayılmaz.
- Writer lease yenileme hatası yutulmaz; fatal task hatasına yükseltilir. Warmup/setup ve her alt coroutine için genel supervisor iddiası yok: bu denetim aktif/drenajdaki altı ana görev içindir.
- Aktif/drenaj süreleri monotonic. Uyku/poll >5s veya wall/mono sapması >2s süreklilik olayı; süre hedefi gelse bile DISCONTINUOUS, düz COMPLETED değil. Gözlem bütün VM durmuşken çalışamaz; dönüşte boşluğu tespit eder. Güç kaybında final dosyası garantisi yok.
- 1s pollda >1s ek gecikme EVENT_LOOP_DELAY olarak kaydedilir. Strateji hazırlığı (senkron), tüm çevrim (await dahil), analytics/ledger ve sağlık render süreleri ayrıdır. Bunlar CPU/stack profili değildir.
- Önce yeni gerçek run testleri eski v9.4.4 davranışında 4 başarısız / 10 geçti. Yama sonrası host **158 geçti / 15.84s**, temiz --no-cache Docker **158 geçti / 17.31s**. pip check başarılı. 100 kaynak dosyası donduruldu. Strateji/Executor/StateStore/portfolio/backtest kaynakları byte-byte korunur; config yalnız sürüm etiketiyle farklıdır.
- Hata enjekte edilen dört gerçek HTTP testi feedler ve ledger sağlıklıyken task ölümü, sayaç durması, heartbeat bayatlığı ve boşluk için 503 doğrular. Bu enjeksiyonlar yalnız test defterlerindedir; aşağıdaki doğal koşuya enjekte edilmedi.

## D. Yeni doğal koşu — görev ve süreklilik sonucu

- Runner durumu **COMPLETED**, active_window_completed=True. Monotonic toplam **720.706s**; kaydedilen drenaj **120.000s**.
- Aktif süre tahmini (son monotonic−drenaj) **600.706s**. Son raporlama/cleanup overheadini de içerdiğinden tam aktif çıkış timestamp’i olarak sunulmaz.
- Dahili gap_count=0, görev hataları={}, max poll ek gecikmesi=0.262680s, max wall/mono sapması=0.000021s.
- Çalışma sırasında HTTP zaman aşımı/hata: 0; final summary sonrası planlı HTTP cleanup sırasında ConnectionRefused: 1. Ham kayıt silinmedi. Tüm gözlemci denemeleri (cleanup dahil) başarılı bayrağı false olarak ayrı tutulur.
- Son snapshotta görevlerin cancelled görünmesi normal cleanup sonrasıdır; task_failures tarihçesi ayrı alandır. Ara snapshotlardaki running durumları ve ilerleme ham state kayıtlarında tutulur.
- Yeni koşu HTTP sayaçları {'200': 719}; sorgu hata sayısı 1. Kapsamı dar bağlantı kabulü: **True**.
### Ölçülen süreler (süreçteki maksimumlar)

| İşlem | Maks ms | Not |
|---|---:|---|
| analytics_snapshot_including_ledger | 4.773 | Duvar/monotonic süre; nedensel profiler değildir |
| health_render | 8.055 | Duvar/monotonic süre; nedensel profiler değildir |
| strategy_prepare_sync | 33.603 | Duvar/monotonic süre; nedensel profiler değildir |
| strategy_cycle_including_awaits | 5762.041 | Await/maker beklemesini içerir; CPU blokajı değildir |

Önceki timeout tekrar etmemiş olsa bile sebebi düzeldi/kanıtlandı denmez; farklı piyasa ve yük örneğidir. Yeni render ölçüsü handler başladıktan sonrasını ölçer; handler kuyruğunda bekleme ayrıca poll gecikmesinde görülebilir.

## E. Yeni koşu pozisyon yoğunluğu ve stop mesafeleri

- LONG **1**, SHORT **0**; toplam marj 50.000000 USDT.
- Brüt mark nominali **499.473268 USDT**, net yönlü nominal **499.473268 USDT**, brüt/equity **0.4998×**.
- Mark→stop USDT mesafe toplamı **2.459625**; mevcut stopların girişe göre kayıp kısmı **2.971725 USDT**.
- Farklı sembollerin ham fiyat farkları toplanmaz; qty ile USDTye çevrilir. Stop tam fiyatından gerçekleşme, korelasyon, gap, slippage ve ücretler garanti edilmez. Bu tutarlar maksimum portföy düşüş sınırı değildir.
| Sembol | Yön | Marj USDT | Mark nominal USDT | Mark | Stop | Mark→stop % | USDT mesafe |
|---|---|---:|---:|---:|---:|---:|---:|
| ENA/USDT | LONG | 50.0000 | 499.4733 | 0.170685 | 0.16984447 | 0.4924 | 2.4596 |

Drenaj sonunda kalan PAPER pozisyonlar zorla kapatılmadı. Süreç durduğundan bu pozisyonları artık izlemiyor; snapshotı yeni koşuya taşımayın. Son değerler anlık fotoğraftır.

## F. Kapanış mekanizması, süre ve MAE

| Koşu | Sembol | Neden | Tutulma s | MAE USDT | MFE USDT | Net USDT |
|---|---|---|---:|---:|---:|---:|
| Önceki v944 | DOT/USDT | KÂR KİLİDİ STOPU | 333.620 | -0.319472 | 3.088227 | +1.343816 |
| Yeni v945 | — | Kapanış yok | — | — | — | — |

MAE/MFE sadece gözlenen quote yolundaki Executor ölçüleridir; gözlenmeyen borsa fiyat uçlarını kapsadığı iddia edilmez. Bilinmeyen tutulma süresi uydurulmadı; mevcut süreler persisted position_meta.opened_ts ile trade_history.ts farkıdır.

## G. Kalan açıklar ve Binance kaynakları

- Thread-token atomik görünürlük yarışı, büyük gerçek defter tam API yükü, bridge/Compose dağıtımı, tam transitif lock ve unique_signal_count/olgun karar kimliği altyapısı tamamlanmadı. Phase2 strateji araştırması başlamadı.
- Binance mevcut bağlantısı: src/live_runner.py içindeki _binance_single_ws/binance_ws_loop; REST mumları _fetch_binance_perp_candles. URL kategorileri src/feed_health.py. aggTrade → fstream.binance.com/market; bookTicker → fstream.binance.com/public.
- Tam kaynak alıntısı BINANCE_BAGLANTI_KODU.txt içindedir. Ayrı bağımsız başlatıcı veya Binance-only mod değildir; bu test Binance ve OKX birlikte çalıştı.
- 10 dakikalık tek örnek, küçük dolum/kapanış sayısı veya olumlu equity; genel yürütme güvenilirliği, kârlılık veya gerçek para onayı değildir. Önceki negatif tarihsel araştırma hükmü değişmedi.


---

# v9.4.5 — 10 dakikalık gerçek piyasa verili PAPER testi

Rapor UTC: 2026-11-03T11:46:03.861333+00:00

**Gerçek borsa emri gönderilmedi. Strateji/risk ayarı değiştirilmedi. Kârlılık veya gerçek para onayı yok.**

## 1. Süre, kaynak ve ortam

- Plan UTC: 2026-11-03T11:31:17.972989+00:00; başlangıçtan önce süre, kaynak, config ve örnekleme kaydedildi.
- Konteyner: 03.11.2026 14:31:23 → 03.11.2026 14:43:32 Türkiye saati.
- Aktif hedef 600s; son monotonic−drenaj tahmini **600.705593s** (raporlama overheadini içerir); drenaj **120.000327s**, wallclock toplam **720.703710s**.
- Drenaj üst sınırı 120s idi; gerçek süre 120.000327s, **0.000327s taşma** var. Kalan süreye göre kısaltılan beklemeye rağmen scheduler hassasiyeti vardır; katı matematiksel 120s sınırı iddia edilmez.
- Durum: **COMPLETED**; runner phase=COMPLETED, ExitCode=0. Bot durmuş durumda.
- İmaj `sha256:e20310f7201f973f750d51fc05e5ade87476750e414ea1198a6eb1910e59813d`; host ağ modu. Kaynak100 hashleri tekrar doğrulandı; config aynı. Bu yeni sürüm için koşudan önce host 158/158 ve temiz Docker 158/158 regresyon geçti. Önceki sürümün 140 testi ayrıca eklenerek sayı şişirilmedi.

## 2. Sağlık ve süreklilik

- Gözlemci yanıtları: **{'200': 719}**, toplam 719. İlk 60s sonrası 653 yanıt, HTTP200 dışı 0.
- Toplam örnekleme hatası **1**, aktif başlangıçtan 60s sonrası/stop öncesi hata 0. Hatalar aşağıda ve ham dosyada saklıdır.
- En büyük sağlık örnekleri arası boşluk **1.524s**; gözlemci poll boşluğu **0.767s**. 5s üzeri gözlenen sağlık boşluğu: **False**.
- Kapsamı dar örneklenen bağlantı/sağlık kontrolleri: **True**. Bu sürekli erişilebilirlik veya genel operasyonel hazırlık onayı değildir.
- Final summary yazıldıktan sonra planlı web kapanışında alınan hata sayısı: 1. Bu koşuda ConnectionRefused kaydı summary yazımından yaklaşık 0.235s sonradır; çalışan testin zaman aşımı değildir. Tüm gözlemci denemeleri (cleanup dahil) başarılı: False. Çalışma-penceresi ölçütü final summary yazımına kadar değerlendirilir, Docker FinishedAt daha geçtir.
- v9.4.5 dahili monotonic süre/görev denetimi ve dış gözlemci birlikte kullanıldı. Eşik üstü iç boşluk ayrı run süreklilik sonucudur; sistemin askıya alınmasını önleme veya uptime garantisi değildir.

### Örnekleme hataları

```json
[
  {
    "observed_at_epoch": 1793706212.0978324,
    "observer_monotonic": 38642.525299048,
    "type": "http",
    "error": "URLError(ConnectionRefusedError(111, 'Connection refused'))"
  }
]
```

## 3. Piyasa akışları

| Ölçüm | Binance | OKX |
|---|---:|---:|
| Tick | 55706 | 52767 |
| BBO | 1259311 | 312574 |
| Hata | 0 | 0 |
| aggTrade hatası | 0 | — |
| Son trade-tape sağlığı | True | True |

## 4. Doğal PAPER emir yaşam döngüsü

- Maker kuyruk: `{"submitted": 2, "filled": 1, "partial_filled": 0, "expired_unfilled": 1, "post_only_rejected": 0, "open_resting": 0, "fill_rate_pct": 50.0, "avg_wait_ms": 2754.8, "avg_unfilled_runaway_bps": 0.0}`.
- Açık pozisyon **1**; kapanış kaydı **0**; defter pozisyon kimlikleriyle doğrulanan ayrı tam kapanmış döngü **0**.
- Canlı genç/sahipli PENDING + HTTP200/IN_FLIGHT/reconciled=false: **True**. 21 örnekte 1 ayrı niyet kimliği; son journal durumları `pending_terminal_proof.json` içinde.
- Bu koşudaki yakalanan niyetlerin terminal journal kanıtı tamamlandı: **False**. ABSENT_NOT_PROOF_OF_CANCEL tek başına iptal kanıtı değildir; bu yeni koşunun kaydında kuyrukta 1 expiry ile uyumlu fakat aynı kimlikli iptal olayı ayrıca kaydedilmedi.
- PENDING kanıtı önceki sentetik probe değildir: gerçek piyasa veri akışı, değiştirilmemiş Executor, PAPER maker kuyruğu ve StateStore yolundan doğal oluştu. Hiçbir niyet/pozisyon/fiyat/yaş enjeksiyonu yapılmadı.
- Bu olaylar mevcut canlı PENDING davranışına ilişkin sınırlı doğrudan kanıttır; eski v9.4.2 503ünün kesin nedeni hâlâ geriye dönük kanıtlanmış değildir.
- Doğal tam giriş–kapanış döngüsü gözlendi: **False**. Drenaj sonunda kalan pozisyonlar zorla kapatılmadı; yeniden açılmadı. Son DB korunmuştur.
- Niyet operation_id ile position_id farklı kimliklerdir. Tam döngü kanıtı; tekil sembol/giriş miktarı, sonraki niyetlerin beklenen-durum metadata içindeki position_id, CLOSED kapanış niyeti, trade_history miktarı ve kalan pozisyonun yokluğunu birlikte eşleştirir. Ayrıntı full_cycle_proof.json içindedir.
- Kapanan döngünün kendi giriş PENDING HTTP anı yakalandı: **False**. Bu koşuda kapanış olmadığından aynı kapanmış döngüde tüm aşamaların HTTP gözlemi ölçütü uygulanamaz; false alanı yeni kapanış kanıtı yok demektir.

## 5. Finansal sonuç — küçük örneklem

| Ölçüm | USDT |
|---|---:|
| Bakiye | 999.90000293 |
| Equity | 999.38790273 |
| Toplam equity farkı | -0.61209727 |
| Kapanmış net PnL | +0.00000000 |
| Açık unrealized PnL | -0.51210020 |
| Toplam ücret | 0.09999707 |
| Funding | 0.00000000 |
- Son salt-okunur sıkı ledger: `{"ok": true, "empty": false, "balance": 999.9000029262868, "expected_balance": 999.9000029262868, "total_fees_usdt": 0.09999707371316538, "total_funding_usdt": 0.0, "open_positions": 1, "closed_trades": 0}`. Snapshot test DBsi rapor paketindedir.
- Equity köprüsü: 1000 + kapanmış net 0.00000000 − hâlen açık pozisyonların ödenmiş giriş ücretleri 0.09999707 + açık brüt unrealized -0.51210020 = 999.38790273 USDT (bu koşuda funding=0). Açık PnL gelecekteki çıkış maliyetini içermez.
- Bot durduğundan kalan PAPER pozisyonlar artık bu süreç tarafından izlenmiyor; equity/unrealized yalnız son anın fotoğrafıdır.
- Bu küçük örneklemden kârlılık, kazanma oranı güvenilirliği veya gerçek borsa dolum güvenilirliği çıkarılamaz. Açık PnL kapanmış sonuç değildir; önceki negatif tarihsel araştırma hükmü değişmez.

## 6. Değerlendirme sayaçları

```json
{
  "evaluation_calls_total": 14478,
  "entry_retry_suppressed": 11096,
  "position_retry_suppressed": 199,
  "retry_suppressed_total": 11295,
  "non_retry_evaluation_calls": 3183,
  "retry_suppression_pct": 78.01491918773311,
  "counter_consistent": true,
  "non_retry_reason_counts": {
    "INSUFFICIENT_REAL_FLOW": 31,
    "LOW_TREND_EFFICIENCY": 27,
    "RSI_EXHAUSTION": 27,
    "SPREAD_TOO_WIDE": 46,
    "DO_NOT_CHASE": 7,
    "REAL_TAKER_UNAVAILABLE": 8,
    "LIVE_ENTRY_DRIFT": 1,
    "CLOSED_HTF_DISAGREEMENT": 19,
    "NO_LOCAL_TREND": 42,
    "STALE_SIGNAL_BAR": 421,
    "HOLD_CONFIRMED_THESIS": 2,
    "DRAIN_NO_NEW_ENTRY": 2550
  },
  "unique_signal_count": null,
  "scope": "Call counters, NOT unique opportunities, mature cohorts, or independent signals",
  "strategy_policy_changed": false
}
```

- State örneklerinde değerlendirme sayacının aynı kaldığı en uzun gözlenen span 0.000s. Bu dış sayaç ölçümüdür; dahili strategy_cycle heartbeat alanı ayrıca sonuçlarda yer alır.
- Tekrar korumaları ekonomik gate reddi ve bağımsız fırsat sayısı sayılmadı. unique_signal_count hâlâ null; olgun örneklem/karar kimliği altyapısı bu testte eklenmedi.

## 7. Nihai karar

- Süre protokolü: **COMPLETED**.
- Örneklenen bağlantı/sağlık kriterleri: **True**.
- Doğal canlı PENDING yanıtı: **True**.
- Doğal tam açılış–kapanış döngüsü: **False**.
- Görev denetimi ve iç süreklilik durumları ayrı kontrat testleriyle doğrulandı; bu doğal koşuda hata enjeksiyonu yoktur. Thread-token yarışı, büyük gerçek defter yükü ve bridge/Compose dağıtımı çözülmüş sayılmaz.
- Operasyonel hazırlık / gerçek para onayı **YOK**. Sinyal/stop/çıkış/filtre ayarı ve otomatik tekrar koşusu yapılmadı.
