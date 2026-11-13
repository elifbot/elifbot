# v9.4.3 — Kullanıcı isteğiyle durdurulan PAPER koşusu

**Sonuç: KESİLDİ / YETERSİZ GÖZLEM. 24 saatlik kabul tamamlanmadı.**

Bot konteyneri durduruldu (`Running=false`, `ExitCode=0`); salt-okunur gözlemci de durduruldu. Ayrı 10 dakikalık koşu başlatılmadı. Kaynak veya strateji eşiği değiştirilmedi.

## Süre ve doğru etiket

- Konteyner başlangıcı: 03.11.2026 12:51:31 Türkiye saati.
- Konteyner bitişi: 03.11.2026 13:12:18 Türkiye saati.
- Önceden belirlenmiş hedef: 86.400 saniye aktif + en fazla 600 saniye drenaj.
- Runner toplam geçen süre: **1238.006 saniye — yaklaşık 20 dakika 38 saniye**. Drenaj 0.000211s.
- Ham summary `phase=COMPLETED` ve konsol “86400s tamamlandı / CANLI_TEST_TAMAMLANDI” yazıyor. **Bunlar erken durdurmayı yanlış etiketleyen runner çıktılarıdır**; ham kayıtlar değiştirilmedi. Gerçek süre 24 saatin altında olduğundan kanonik sonuç `INTERRUPTED_BY_USER` olarak yazıldı. ExitCode=0 yalnız temiz süreç kapanışıdır; deney başarısı değildir.

## Önemli süreklilik sınırı

- `/health` kayıtları arasındaki en büyük boşluk **897.078s — yaklaşık 14 dakika 57 saniye**: 2026-11-03T09:56:27.363695+00:00 → 2026-11-03T10:11:24.441538+00:00. İkinci boşluk 41.867s.
- State örneklerinde de yaklaşık 901s, Docker durum örneklerinde yaklaşık 906s boşluk var. Duvar saati sayacı bu aralıkları içerir; **20 dakika 38 saniye kesintisiz çalışan/izlenen bot kanıtı değildir**.
- Ortak boşluk altyapı/sandbox askıya alınması veya yürütme duraklaması ihtimaliyle uyumludur; hangisinin neden olduğu bu kayıtlarla kesinleştirilmedi. Veri akışı/örnekleme sürekliliği doğrulanamadı. Önceki “ACTIVE/çalışıyor” yanıtı o andaki canlı durumu gösteriyordu; geriye dönük kesintisizlik garantisi değildi.

## HTTP sağlık sonuçları

- Gözlemci kayıtları: **62 yanıt; 60 HTTP200, 2 HTTP503**. Ayrı manuel sorgular veya Docker HEALTHCHECK yanıtları bu sayıya katılmadı.
- 503ler bu koşuda PENDING kaynaklı görünmüyor: her iki yanıtta da defter RECONCILED/clean_empty_db ve pending_operations boş. Kaydedilen alarmlar aşağıdadır; eski v9.4.2 503 olayı için yeni kesin tanı sayılmaz.

| UTC zaman | HTTP | Feed gecikmesi | Alarmlar |
|---|---:|---:|---|
| 2026-11-03T10:11:24.441538+00:00 | 503 | 895.91s | FEED_LATENCY_ALARM(895.9s>20.0s), OKX_TRADE_TAPE_STALE |
| 2026-11-03T10:12:16.605202+00:00 | 503 | 39.03s | FEED_LATENCY_ALARM(39.0s>20.0s) |

- Durdurmadan sonra gözlemci 2 adet Connection refused kaydetti. Bunlar konteyner kapandıktan sonraki sorgulardır; çalışan botun HTTP503 sayısına eklenmedi.
- Son summary sağlık anlık görüntüsünde FEED_LATENCY_ALARM(40.2s>20.0s) var. Son iki tape sayacı sağlıklı olsa bile genel operasyonel sağlık false; “her şey sağlıklı” sonucu çıkarılmadı.
- Son Docker inspect durmuş konteyner için Health.Status=unhealthy gösteriyor; bu, HTTP503 sayısına eklenmedi. Kayıtlı son beş Docker HEALTHCHECK komutunun ExitCode değeri 0; aradaki büyük boşluk nedeniyle sürekli Docker sağlık doğrulaması sayılamaz.

## Piyasa verileri

| Ölçüm | Binance | OKX |
|---|---:|---:|
| İşlem ticki | 21536 | 17725 |
| BBO güncellemesi | 487004 | 103305 |
| Hata | 1 | 0 |
| aggTrade hatası | 1 | — |
| Son trade-tape sağlığı | True | True |

Binance aggTrade akışında 1 hata/geçiş ve yeniden bağlantı kaydı var; sıfır hata denmedi. Endpointler market/public olarak ayrı kaldı.

## Emir, pozisyon ve defter

| Ölçüm | Sonuç |
|---|---:|
| Emir gönderimi / dolum / dolmadan süresi dolan | 0 / 0 / 0 |
| Açık / kapanmış pozisyon | 0 / 0 |
| Başlangıç / bitiş equity | 1000 / 1000 USDT |
| Net PnL / ücret / funding | 0 / 0 / 0 USDT |
| Sinyal değerlendirmesi | 4972 |
- Son salt-okunur sıkı defter kontrolü: `{"ok": true, "empty": true, "reason": "clean_empty_db"}`. Dört niyet tablosunda kayıt yok; açık pozisyon/trade_history de boş.
- Bu koşuda eski 15 dakikalık deneyden farklı olarak **emir denemesi dahi yok**. Doğal PENDING HTTP200/IN_FLIGHT ve giriş–kapanış döngüsü gözlenmedi. 0 USDT net, kârlılık veya güvenlik kanıtı değildir.

### Giriş engelleme sayaçları

| Neden | Sayaç |
|---|---:|
| ONE_ATTEMPT_PER_CLOSED_BAR | 4596 |
| STALE_SIGNAL_BAR | 189 |
| LEADERS_UNAVAILABLE_OR_STALE | 79 |
| CLOSED_HTF_DISAGREEMENT | 29 |
| SPREAD_TOO_WIDE | 21 |
| NO_LOCAL_TREND | 18 |
| INSUFFICIENT_REAL_FLOW | 11 |
| REAL_TAKER_UNAVAILABLE | 10 |
| DO_NOT_CHASE | 7 |
| LOW_TREND_EFFICIENCY | 7 |
| RSI_EXHAUSTION | 5 |

Bu sayaçlar benzersiz sinyal veya bağımsız işlem sayısı değildir. Bir aday tekrar değerlendirilmiş olabilir; gate sırası koşulludur. Bu verilere göre parametre/gate ayarı yapılmadı, “kârlı işlem engellendi” yorumu çıkarılmadı.

## Değişmezlik ve önceki testler

- Önceden kaydedilmiş 90 kaynak hashinin tamamı tekrar doğrulandı; uyuşmazlık 0. Observer SHA-256 planla aynı: True.
- Önceki Docker testinde ilk PyYAML eksikliğiyle 4 collection hatası ve paketleme düzeltmesi sonrası 121 passed / 11.73s çıktısı korunur; bu durdurma işlemi için yeni pytest çalıştırılmadı.
- Önceki r3 ZIP değişmedi: içindeki RUNNING bilgisi tarihli başlangıç anı kopyasıdır. **Güncel nihai durum bu rapor ve SONUC.json dosyasıdır.** Eski 15 dakikalık testin 59/59 sayısı bu koşuya eklenmedi.

## Nihai karar

- 24 saat süre ölçütü: **SAĞLANMADI — kullanıcı isteğiyle erken durduruldu**.
- Kesintisiz veri/gözlem: **DOĞRULANAMADI — yaklaşık 15 dakika kayıt boşluğu, 2 HTTP503**.
- Canlı genç PENDING + sağlıklı HTTP yanıtı: **GÖZLENMEDİ**.
- Doğal giriş dolumu ve tam kapanış: **GÖZLENMEDİ**.
- Son sıkı defter: **TEMİZ, fakat boş defter**.
- Operasyonel hazırlık, kârlılık ve gerçek para onayı: **YOK**.

Bu koşu, tamamlanmış 10 dakika veya tamamlanmış 24 saat kabul testi olarak yeniden adlandırılmadı. Yeniden başlatma yapılmadı. Ham kayıtlar kanitlar/ klasöründedir; manifest her teslim dosyasının SHA-256 değerini içerir.
