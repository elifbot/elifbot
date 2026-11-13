# Futures Bot v37 — Kağıt Testi Durum ve İyileştirme Raporu

> **GÜNCELLEME:** Bu dosya ikinci/üçüncü denemelerin ara durumunu ve eski bulgularını korur. Son tamamlanmış beş dakikalık koşunun sonuçları ve güncel telemetrisi için [`v37_paper_test_final_report_2026-10-29.md`](v37_paper_test_final_report_2026-10-29.md) esas alınmalıdır. Yeni denemede eksik gösterge dakikaları için kapanmış Binance klines backfill eklendi; 413 test geçti.

**Rapor tarihi:** 29 Ekim 2026  
**Saat dilimi:** Europe/Istanbul (TRT, UTC+3)  
**Kapsam:** Hazırlık kapısı ve ikinci kağıt-test denemesi  
**Sonuç durumu:** **Gösterge hazır olma eşiği aşılmadı; beş dakikalık ölçüm başlamadı.**

## Yönetici özeti

İkinci kağıt-test süreci yaklaşık 30 dakika boyunca gösterge hazırlık aşamasında kaldı. Binance ve OKX’in her birinde beklenen sembol evreninin **%90’ından fazlasının** gösterge ve taze fiyat koşullarını sağlaması gerekiyordu. Son durum kaydında iki borsa da 0 kapsam gösterdi; beş dakikalık test sayacı sıfır kaldı.

Botta sinyal, pozisyon açılışı/kapanışı veya PnL oluşmadı. Bu nedenle **tamamlanmış bir beş dakikalık test sonucu yoktur**; PnL’nin 0 olması performans sonucu olarak yorumlanmamalıdır.

Önemli tanı bulgusu, Binance aggTrade girişinde çok yüksek bayat olay ve reset sayısıdır. Kod incelemesi, bayat/sırasız olayların gösterge mum geçmişini temizleyebildiğini doğruluyor. Bu, hazır kapsamın neden sürdürülemediğine dair güçlü bir açıklamadır; ancak olayların neden bayat geldiği mevcut toplu telemetriyle kesin olarak saptanamamıştır.

## Son durum

| Ölçüm | Son kayıt / sonuç |
|---|---:|
| Süreç başlangıcı | 29 Ekim 2026, 16:44:56 UTC (19:44:56 TRT) |
| Son durum kaydı | 17:15:08 UTC (20:15:08 TRT) |
| Son aşama | `indikator_hazirlik` |
| Hazırlıkta geçen süre | 1.812 sn (30 dk 12 sn) |
| Beş dakikalık test sayacı | **0 sn — başlamadı** |
| Binance hazır kapsamı | **0 / 522** |
| OKX hazır kapsamı | **0 / 289** |
| Sinyal / açılan / kapanan işlem | 0 / 0 / 0 |
| Toplam PnL | 0.0 (işlem yok) |
| Kayıtlı hata sayacı | 0 |

Son durum JSON’unda hem `mum_hazir` hem `mum_ve_fiyat_hazir` sayıları iki borsa için de sıfırdı. Önceki bir OKX anlık görüntüsünde 139/289 sembol gösterge açısından hazır (**%48,10**), 70/289 ise taze fiyatla hazır (**%24,22**) görünmüştü; bu da %90 eşiğinin altında kalıyordu.

## Binance aggTrade telemetrisi

| Sayaç | Son değer |
|---|---:|
| Toplam aggTrade mesajı | 1.456.499 |
| Kabul edilen | 1.256.848 |
| Bayat/sırasız olarak reddedilen | 199.651 (**yaklaşık %13,71**) |
| Geçersiz | 0 |
| Reset | 202.229 |
| Şüpheli aggregate-ID boşluğu | 506 |
| WebSocket bağlantı sayacı | 6 |
| Akış hatası / callback hatası | 0 / 0 |

Bayat oranı, reddedilen 199.651 olayın toplam 1.456.499 aggTrade mesajına oranıdır. Reset sayısı bayat olay sayısından yüksek olduğundan, tüm resetleri yalnızca bayat olaylara bağlamak doğru olmaz; bağlantı ve ID-boşluğu yolları da reset üretebilir.

## Tanı ve güvenlik değerlendirmesi

Kaynak incelemesinde `scanner/aggtrade_input.py` içinde Binance olay zamanı şu koşullarla kontrol ediliyor: olayın 5 saniyeden eski olması, 2 saniyeden fazla gelecekte görünmesi veya sembol bazında zaman sırasının bozulması. Bu koşullardan biri sağlanınca olay bayat olarak sayılıyor ve geçmişi temizleyen reset çağrılıyor. Temizlenen alanlar arasında gösterge dakika mumları (`ind_mum`, `ind_acik_mum`) ve hacim/geçmiş bağlamı da bulunuyor. Dolayısıyla tekrarlayan resetler 60 dakikalık gösterge geçmişinin yeniden oluşmasını engelleyip hazır kapsamı düşürebilir.

Ayrıca `scanner/binance_flow.py`, şüpheli aggregate-ID boşluğunda ilgili sembol için bağlantı durumu geri-kurulumu tetikliyor; bu da giriş katmanında reset yoluna giriyor. Mevcut çalışma telemetrisi bayat olayların **hangi sembollerde**, **kaç milisaniye gecikmeyle** ve **hangi reset sebebiyle** oluştuğunu göstermediğinden, upstream neden (akış gecikmesi/kuyruk, saat farkı, yeniden bağlantı veya ID boşluğu) kesinleşmiş değildir.

**Güvenlik kararı:** Bayat veri eşiği gevşetilmedi, hazır olma eşiği atlanmadı ve ön-hazırlık sinyalleri test örneklemine alınmadı. Bu koşuda gerçek emir gönderilmedi; çalışma kağıt-test modundaydı.

## Sürecin durdurulması ve kayıt notu

`stop_process` çağrısı sürecin durduğunu bildirse de, işletim sistemi kontrolünde Python çocuk süreci PID **6715** çalışmaya devam ediyordu. SIGTERM sonrasında da kapanmadığı görüldüğünden SIGKILL ile sonlandırıldı; son `ps` kontrolünde `ws_bot.py` süreci görünmüyordu.

Süreç zorla sonlandırıldığı için kapanış kodu temiz biçimde yazılamadı. Bu nedenle `ws_durum.json` içindeki `calisiyor: true` ve `ws_kapanis.json` içindeki `kapanis_nedeni: bilinmiyor` alanları **son/gerçek süreç durumunu yansıtan bir kapanış kaydı değildir**. Log aktarım süreci daha erken kapandığından metin logu da son durum JSON’undan önce bitiyor; son telemetri zamanı yukarıdaki 17:15:08 UTC kaydıdır.

## İstenen iyileştirmeler — uygulama durumu

1. **OKX varlık filtresi ve çapraz-borsa tekrarları:** OKX'in `instCategory=1` kripto evreni korunuyor; hisse/emtia kategorileri dışarıda. Çalışan tarayıcıya ek olarak v37'nin `STOCK_LIKE_DENYLIST`'i uygulanıyor ve Binance'te aynı normalize base varlığı bulunan OKX sembolleri eleniyor; ortak semboller Binance'te kalıyor. Üçüncü koşu başlangıcındaki evren: OKX 289 ham sembol, 4 stock-like denylist eşleşmesi, 263 Binance ortak sembolü elendi, OKX'te 22 benzersiz sembol kaldı; Binance 522. Denylist tam/otoritatif şirket-kökeni listesi değildir; raporlanan eşleşmeler görünür tutuluyor.
2. **Bayat olay ve timeout davranışı:** Stale/sırasız paket reddediliyor ama `reset()` çağrılmıyor; tamamlanmış 60 dakikalık gösterge geçmişi korunuyor. Gerçek bağlantı/ID boşluğunda yalnız canlı hacim penceresi ve açık dakika yeniden ısıtılıyor; tam geçmiş silinmiyor. Bayat nedenleri/yaş dağılımı/sembol sayaçları, tam resetler ve kısmi resetler ayrı telemetriye eklendi. 5 sn stale ve +2 sn gelecek toleransları gevşetilmedi.
3. **Saat kontrolü:** OKX public time ile üç örneğin medyanında yerel saat farkı yaklaşık **+39 ms** ölçüldü; RTT yaklaşık 163–175 ms idi. Binance saat uç noktası bu ortamdan HTTP 451 döndürdü. `timedatectl` NTP'yi eşzamanlı göstermiyor ve container ayrıcalıksız; ölçülen fark 5 sn stale eşiğini açıklamadığından chrony/ntpdate kurulmadı.
4. **Güvenli kapanış:** Sinyal istisnası kaldırılıp SIGTERM/SIGINT/SIGHUP asyncio event loop'una kooperatif kapanış olarak bağlandı. Böylece sinyal ağ coroutine'lerindeki genel `except Exception` bloklarında yutulmamalı; kapanış durumu JSON'a yazılmalı.

## Doğrulama

- `py_compile`: başarılı.
- Hedefli testler: **50 geçti**.
- Tam regresyon paketi: **412 geçti**.
- Bu testler kod/regresyon doğrulamasıdır; canlı kağıt-test performansını veya veri bütünlüğünü kanıtlamaz. H-01/P0 kapsam uyarısı geçerlidir.

## Üçüncü kağıt koşusu — devam ediyor

**Son kontrol:** 29 Ekim 2026 17:47:49 UTC (20:47:49 TRT). Süreç `futures-bot-paper-test-64c183fa`, Python PID **32219** ile çalışıyor. Yalnız kağıt portföyü kullanılıyor.

| Ölçüm | Son durum |
|---|---:|
| Aşama / hazırlık süresi | `indikator_hazirlik` / 413 sn |
| Binance kapsamı | 0/522 hazır; 0/522 taze fiyatla hazır |
| OKX kapsamı | 22/22 hazır; 22/22 taze fiyatla hazır (%100) |
| Beş dakikalık test sayacı | **0 sn — henüz başlamadı** |
| AggTrade kabul / bayat / tam reset | 273.652 / 0 / 0 |
| Kısmi reset | 522, tümü `initial_connect` (başlangıç başlatması) |
| Akış hatası / callback hatası / ID boşluğu | 0 / 0 / 0 |
| Sinyal / açılan / kapanan / PnL | 0 / 0 / 0 / 0.0 |

Binance REST ön-dolgu 522/522 sembol için tamamlandı; hazır kapsam bir süre 109/522 olmuş, sonra 0/522'ye düşmüştür. Bayat olay veya tam reset sayaçları artmadığından bu düşüş eski reset döngüsüyle açıklanmıyor. Olası neden, canlı aggTrade'in ilk kısmi dakikasının atılmasıyla 60 tam mum penceresinde bir dakikanın eksik kalmasıdır; bu henüz kesin kök neden olarak doğrulanmadı. Kapı **her iki borsada da >%90** şartını koruyor; bu nedenle beş dakikalık saat başlatılmadı ve canlı test sonuçları henüz yok.

## İlgili dosyalar

- **Üçüncü koşunun canlı logu:** [`v37_paper_test.log`](v37_paper_test.log)
- **Üçüncü koşunun canlı durum JSON'u:** [`ws_durum.json`](../logs/ws_durum.json)
- **İkinci koşunun arşivlenmiş logu:** [`attempt2/v37_paper_test.log`](attempt2/v37_paper_test.log)
- **İkinci koşunun arşivlenmiş durum/kapanış kayıtları:** [`attempt2/logs/ws_durum.json`](attempt2/logs/ws_durum.json), [`attempt2/logs/ws_kapanis.json`](attempt2/logs/ws_kapanis.json)
- **İlk tamamlanmamış deneme:** [`attempt1/`](attempt1/)
- **Değiştirilmiş v37 kaynak ağacı:** `futures_bot_v37/`
