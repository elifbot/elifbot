# Düzeltilmiş gecikme probu — 10 dakikalık PAPER testi

**Koşu: COMPLETED. Dolan giriş: 0; kapanış kaydı: 0; açık pozisyon: 0.**

**Bu bir ölçüm koşusudur; gecikme düzeltmesi veya filtre gevşetmesi uygulanmadı. Gerçek emir yok.**

## 1. Protokol ve ortam

- Plan UTC: 2026-11-03T13:38:54.780166+00:00. Yeni boş defter; eski pozisyonlar devralınmadı. İlk console clean_empty_db kaydını içerir.
- Host launcher Türkiye saati: 03.11.2026 16:39:02 → 03.11.2026 16:49:11. Bu süre warmup ve kapanışı da içerir.
- Aktif hedef 600s; active_window_completed=True; toplam monotonic 600.547249s; drenaj 0.000144s. Son monotonic−drenaj 600.547105s, final overheadini içerir; tam aktif çıkış zamanı değildir.
- Process exit code 0; koşu nedeni duration_target_reached. Drenaj hedefi en fazla 120s; scheduler hassasiyeti vardır. Zorla giriş/kapanış veya hedef işlem sayısı için süre uzatma yok.
- **Host çalıştırması:** mevcut ortamda Docker komutu yok. Sabitlenmiş doğrudan bağımlılıklar kuruldu, pip check temiz. Bu, önceki Docker koşusuyla eşleştirilmiş karşılaştırma değildir; farklı piyasa ve ortam vardır.
- Bot kaynakları aynı: önceki başlangıçtan önce kayıtlı planın 100 SHA değeri ile doğrulandı. Config aynı. Sadece haricî launcher sınıfı warmup sonrasında probu bağlar; kaynak dosyaları değiştirilmez.
- Ön kontrol: 11 prob testi geçti (son çalışma 0.37s); ilk regresyon 154 geçti/4 eksik referans hatası. Eksik tarihsel test referansları doğrulanmış v944 arşivinden geri getirildi; v944 AST referansı aynı eski kaynaktan üretildi. Son regresyon 158 geçti/21.69s. İlk başarısız çıktılar silinmedi. Yeni Docker testi yapılmadı.

## 2. Prob çalıştı mı?

- Pencere sayısı 573; final flush=True; prob hata durumu=None.
- Çift start aynı probu döndürür; çift wrapper engellenir. Kapanışta son pencere yazılır ve fonksiyonlar eski hâline döndürülür. Hata olursa yeni girişler kesilip stop istenir; probe task supervisor kaydındadır.
- Lag probu 50ms aralık hedefler, yaklaşık saniyede bir JSONL yazar. Her pencerede gerçek elapsed, faz, en uzun çağrının zamanları ve uygun bağlam tutulur.
- Probun ölçtüğü maksimum 50ms uyku aşımı: **1160.602 ms**. Bu, supervisorın 1s uyku ölçüsüyle aynı metrik değildir.

## 3. Fonksiyon ölçümleri

**Süreler kapsayıcı duvar süresidir. Async beklemeler dahil; iç içe süreleri toplayıp CPU yüzdesi çıkarmayın.**

| Fonksiyon | Çağrı | Toplam kapsayıcı ms | Ortalama ms | En uzun ms |
|---|---:|---:|---:|---:|
| on_trade | 180242 | 214663.625 | 1.190974 | 138.628 |
| on_price_tick | 2643794 | 15734.733 | 0.005952 | 7.223 |
| warmup_symbol | 35 | 6948.645 | 198.532701 | 620.994 |
| evaluate_and_route | 11499 | 5270.418 | 0.458337 | 61.974 |
| market_context | 150 | 3335.323 | 22.235489 | 48.079 |
| build_state_payload | 665 | 2456.543 | 3.694050 | 11.737 |
| _rows_to_df | 1337 | 1798.022 | 1.344818 | 5.068 |
| features | 200 | 1460.521 | 7.302607 | 13.660 |
| acquire_writer_lease | 166 | 550.971 | 3.319104 | 10.580 |

**Çağrılmayan ölçüm hedefleri:** update_paper_risk_if_unchanged, find_pair_rescue. Bunlar için performans sonucu çıkarılamaz. Özellikle pozisyon açılmadıysa risk güncellemesi ve pozisyonlu stop yolu doğrulanmış değildir.

### En yüksek üç lag penceresi

- UTC 2026-11-03T13:47:14.277277+00:00; faz ACTIVE; gerçek pencere 1210.860ms; uyku aşımı 1160.602ms; açık pozisyon 0.
  - Aynı penceredeki çağrı/total/max: `{"on_price_tick": {"n": 4973, "total_ms": 29.474, "max_ms": 0.178}, "on_trade": {"n": 681, "total_ms": 1042.172, "max_ms": 89.384}, "build_state_payload": {"n": 1, "total_ms": 3.132, "max_ms": 3.132}}`.
- UTC 2026-11-03T13:40:23.339397+00:00; faz ACTIVE; gerçek pencere 1664.927ms; uyku aşımı 1150.860ms; açık pozisyon 0.
  - Aynı penceredeki çağrı/total/max: `{"on_price_tick": {"n": 10232, "total_ms": 52.624, "max_ms": 0.24}, "on_trade": {"n": 753, "total_ms": 440.84, "max_ms": 20.54}, "_rows_to_df": {"n": 2, "total_ms": 2.201, "max_ms": 1.111}, "acquire_writer_lease": {"n": 1, "total_ms": 3.488, "max_ms": 3.488}, "evaluate_and_route": {"n": 55, "total_ms": 778.77, "max_ms": 46.547}, "features": {"n": 23, "total_ms": 213.056, "max_ms": 13.594}, "market_context": {"n": 23, "total_ms": 559.419, "max_ms": 34.719}}`.
- UTC 2026-11-03T13:48:47.035905+00:00; faz ACTIVE; gerçek pencere 1165.228ms; uyku aşımı 1115.069ms; açık pozisyon 0.
  - Aynı penceredeki çağrı/total/max: `{"_rows_to_df": {"n": 1, "total_ms": 1.302, "max_ms": 1.302}, "on_price_tick": {"n": 5406, "total_ms": 27.875, "max_ms": 0.095}, "on_trade": {"n": 1027, "total_ms": 1008.471, "max_ms": 68.887}}`.

### Atıf sınırı

- Aynı pencerede features/market_context yığılması varsa bu, kısa çevrim gecikmesine katkı adayıdır; tek başına önceki 5.22s olayının nedenini kanıtlamaz. Cache-miss ile bar zamanı bağlamı ham kayıttadır.
- on_trade yüksek toplam gösterirse flow/detector/counterfactual alt yollarını ayırmak gerekir. Bu koşuda bunlar ayrı ölçülmedi. Büyük kapsayıcı toplam, tek başına tekil uzun blokaj demek değildir.
- SQLite risk yazımı çağrılmadıysa önceki kilit/disk şüphesi ne doğrulanır ne de elenir. BEGIN/COMMIT ayrı ölçülmedi.
- JSON parse, karar JSONL yazımı ve WS mesaj grupları ayrı ölçülmedi; bunlar kalan kör noktalardır. 50ms lag ölçümü CPU/VM/disk ayrımı yapmaz.
- Exchange olay zamanı, yerel alınma ve stop kararı/kapanış çağrısı zamanları eklenmedi; gerçek stop gecikmesi ölçülmüş değildir.

### Bu koşuda öne çıkan somut bulgular

- on_trade: 180242 çağrı, toplam kapsayıcı 214.664s, en uzun tek çağrı 138.628ms. Bu CPU yüzdesi değildir; alt çağrıları içerir. Bir sonraki ayrıştırma adayı flow/detector/counterfactual alt yollarıdır.
- En yüksek lag penceresi UTC 13:47:14.277: gerçek pencere 1210.860ms, 681 on_trade çağrısının toplam kapsayıcı süresi 1042.172ms; bu pencerede features/market_context çağrısı yok. Bu, tüm gecikmelerin mum hesabıyla açıklanamayacağını gösteren bir ölçümdür; tam CPU/stack nedensellik kanıtı değildir.
- Ayrı mum-hesap penceresi UTC 13:40:23.339: 23 features çağrısı 213.056ms, 23 market_context çağrısı 559.419ms; uyku aşımı 1150.860ms. Yeni mum hesaplarının yığılması ölçüldü; önceki 5.22s olayını açıklamış sayılmaz.
- Risk yazımı ve pair-rescue yolu hiç çağrılmadı; bunların performansı sınanmadı. Önceki 5.22s boşluk ve timeoutun bu koşuda tekrarlanmaması, sebebin düzeldiğini göstermez.

## 4. Probun ek yükü

- Launcher kapanış özeti: `{"failed": null, "calls": 2838090, "windows": 573, "recorder_ns_total": 4563977551, "log_write_ns_total": 80023991, "log_write_ns_max": 543807, "scope": "Measured recorder aggregation+JSONL writes only; excludes all clock/wrapper overhead. Not total probe overhead."}`.
- Recorder/JSONL maliyetleri yalnız ölçülebilen alt bölümlerdir; wrapper saat okumalarını ve tüm scheduler etkisini kapsamaz. Mikrobenchmark no-op fonksiyon içindir; gerçek canlı ek yük ölçümü değildir ve recorder maliyetiyle toplanmamalıdır.
- Kontrol koşusu olmadan daha hızlı/daha yavaş hükmü veya önceki timeoutun düzeldiği iddiası yoktur.

## 5. İşlemler ve finansal fotoğraf

| Ölçüm | Sonuç |
|---|---:|
| Emir denemesi | 0 |
| Maker filled | 0 |
| Maker partial filled | 0 |
| Dolmadan süresi biten | 0 |
| OPEN giriş journal kaydı | 0 |
| Engine entries_routed | 0 |
| Kapanış kaydı | 0 |
| Açık pozisyon | 0 |
| Bakiye USDT | 1000.0 |
| Equity USDT | 1000.0 |
| Equity farkı USDT | 0.0 |
| Kapanmış net PnL USDT | 0.0 |
| Açık unrealized USDT | 0.0 |
| Ücret USDT | 0.0 |
| Funding USDT | 0.0 |

Açık PnL kapanmış kâr değildir; gelecekteki çıkış ücretlerini içermez. Az sayıda dolum, yürütme güvenilirliği veya kârlılık kanıtı değildir. Emir denemesi, giriş ve kapanış ayrı sayılır.
- Açık pozisyon olmadığı için yön dağılımı ve stop/nominal yoğunluk sıfırdır.

Kalan PAPER pozisyonlar süreç durduktan sonra izlenmez. Bu DB sonraki koşuya taşınmamalı. Kapanış yoksa kapanış mekanizması/tutulma süresi/MAE sınanmamıştır.

## 6. Sağlık ve süreklilik

- HTTP cevapları {'200': 549}; hata türleri {}; summary sonrası cleanup hatası 0. Tüm hatalar SONUC.json ve ham dosyalarda tutulur.
- Maks sağlık örnekleri arası boşluk 2.7541423459999805; örneklenen hata/boşluk ölçütü True.
- Supervisor gap_count=0; task_failures={}; alarms=[]. Koşu fazı ve continuity, yalnız zaman hedefinden ayrıdır.
- Salt-okunur sıkı ledger: `{"ok": true, "empty": true, "reason": "clean_empty_db"}`.

## 7. Retler ve örneklem sınırı

| İlk dönen neden | Ham çağrı | Farklı sembol–mum anahtarı |
|---|---:|---:|
| ONE_ATTEMPT_PER_CLOSED_BAR | 10415 | 150 |
| STALE_SIGNAL_BAR | 934 | 50 |
| SPREAD_TOO_WIDE | 42 | 42 |
| INSUFFICIENT_REAL_FLOW | 35 | 35 |
| LOW_TREND_EFFICIENCY | 27 | 27 |
| NO_LOCAL_TREND | 16 | 16 |
| DO_NOT_CHASE | 9 | 9 |
| REAL_TAKER_UNAVAILABLE | 8 | 8 |
| CLOSED_HTF_DISAGREEMENT | 5 | 5 |
| RSI_EXHAUSTION | 5 | 5 |
| LEADERS_UNAVAILABLE_OR_STALE | 2 | 2 |
| WAIT_FOR_RECLAIM_OR_BREAKOUT | 1 | 1 |

Tekrar sayıları bağımsız kaçırılmış işlem değildir; sembol–mum anahtarları da bağımsız/olgun sinyal sayılmaz. unique_signal_count hâlâ null. Sonradan koşulların düzeldiği veya kârlı fırsat engellendiği çıkarılamaz.

## 8. Hüküm

**Prob ölçüm için çalıştırıldı; optimizasyon henüz yapılmadı.** Yeni sonuç eski 5.22s gecikmenin kesin kök nedenini tek başına belirlemez. Çağrılmayan yollar için güvenilirlik veya performans iddiası yoktur. Gerçek para / genel operasyonel hazırlık onayı YOK. Thread-token, büyük ledger/API, Compose/bridge ve tekil olgun sinyal altyapısı açık kalır.
