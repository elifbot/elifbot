# v37 — Beş dakikalık paper testi: nihai rapor

**Durum:** TAMAMLANDI — yalnız paper portföyü; gerçek emir yok  
**Tarih:** 29 Ekim 2026  
**Kod tabanı:** `/home/user/Futures_Bot_v37_Deneysel_Paper_SON/futures_bot_v37/`  
**Test koşusu:** `run_artifacts/attempt4/`  
**Çıkış kodu:** 0 (`ws_kapanis.json`: `tamamlandi`, `normal`)

## Sonuç özeti

| Ölçüm | Sonuç |
|---|---:|
| Hazırlık kapısından geçiş | 18:43:53.833 UTC |
| Kapı anındaki Binance hazır kapsam | **516/522 = 98,85%** |
| Kapı anındaki OKX hazır kapsam | **22/22 = 100%** |
| Sayaç başlangıcı | 18:43:53.858 UTC |
| Sayaç bitişi | 18:48:54.210 UTC |
| Örnekleme süresi | **300,35 sn (5 dakika)** — warm-up hariç |
| Sinyal | **0** |
| Açılan paper pozisyonu | **0** |
| Kapanan paper pozisyonu | **0** |
| Gerçekleşen PnL | **0,0000 USDT** |
| Sanal bakiye | **1.000,00 → 1.000,00 USDT** |
| Açık pozisyon / kayıt mutabakatı | **0 / başarılı** |

Beş dakikalık süre hazırlık kapısının onayından sonra başladı. Sonlandırma doğal süre bitiminde oldu; açık paper pozisyonu bulunmadığı için kapanışta ayrıca işlem oluşmadı. `live_trades.csv` ve `ws_olay.csv` başlık satırları dışında kayıt içermiyor. Sinyal/trade olmaması bu beş dakikada strateji eşiklerini geçen örnek görülmediği anlamına gelir; kârlılık veya strateji başarısı hakkında sonuç çıkarılamaz.

## Veri kapsamı ve akış sağlığı

- Binance evreni: **522** aktif USDT perpetual.
- OKX: 289 ham adaydan 4 stock-like denylist eşleşmesi ve Binance’le ortak 263 varlık elendi; **22** benzersiz OKX sözleşmesi kaldı. Ortak varlıklar Binance’te tutuldu.
- Final `ws_durum.json` kapsamı: Binance **508/522 = 97,32%**, OKX **22/22 = 100%**.
- Ara gözlem: 18:47:10 UTC’de, sayaç devam ederken Binance gösterge+fiyat kapsamı **424/522 = 81,23%** seviyesine düşmüştü; OKX 22/22’ydi. Son durum kaydında Binance kapsamı 97,32%’ye toparlandı. Başlangıç eşiği geçildiği için sayaç çalışmaya devam etti. Bu geçici düşüş, gelecekteki testlerde kapsamın yalnız başlangıçta değil, tüm örnekleme boyunca da izlenmesi/raporlanması gerektiğini gösteriyor.
- Binance aggTrade: **303.644 kabul**, **0 stale**, **0 geçersiz**, **0 tam reset**, **0 şüpheli ID boşluğu**, **0 callback/sinyal hatası**.
- Kısmi reset sayacı **1.044**: 522 `initial_connect` + 522 düzenli bağlantı kapanışı (`connection_down`). Bunlar stale paketi nedeniyle 60 dakikalık gösterge geçmişinin silinmesi değildir. İstenen “stale/timeout nedeniyle reset yapmama” kuralı korunmuştur.
- Hazırlık öncesi engellenen sinyal: **0**; sayaç ve paper portföyü kapıdan geçmeden açılmadı.
- Aday değerlendirme kapılarındaki sayımlar (bunlar benzersiz sinyal sayısı değildir): hacim penceresi yetersiz 25.740, hacim oranı hazır değil 168.317, `bayat_hacim` kapısında ret 51.280, getiri eşiği 228.752 ve RVOL eşiği 27.967. `bayat_hacim` sinyal filtresi sayacıdır; yukarıdaki **aggTrade stale paket sayısı 0** ile karıştırılmamalıdır.

## Saat ve kapanış

Önceki saat kontrolünde OKX public time üç ölçümde yerel saate göre medyan yaklaşık **+39 ms** fark gösterdi (RTT yaklaşık 163–175 ms); Binance saat endpoint’i bu ortamdan HTTP 451 verdi. `timedatectl` NTP eşzamanlı olmadığını, container’da chronyd/ntpdate çalıştırma yetkisi olmadığını gösterdi. +39 ms fark 5 sn stale eşiğini açıklamadığı için saat değiştirilmedi. Bu paper koşusu doğal süre bitiminde `normal`, çıkış kodu 0 ile kapandı; test sırasında SIGTERM gönderilmedi.

## Uygulanan düzeltme ve doğrulama

Üçüncü koşunun önceki logunda Binance REST ön-dolgu 522/522 görünmesine rağmen hazır kapsam 0/522’de kalmıştı. Kod incelemesi, dakika ortasında bağlanan aggTrade akışının ilk kısmi dakikayı doğru biçimde atmasının ardından, son 60 tam dakika penceresinde oluşan boşlukların yeniden REST’ten tamamlanmamasını ortaya çıkardı.

v37 kaynak ağacına `binance_indikator_mum_eksiklerini_doldur()` eklendi. Hazırlık kapısı, eksik son 60 dakika mumlarını Binance’in **kapanmış klines** verisinden, yalnız `ind_mum` haritasına ve rate-limit aralığıyla dolduruyor. Hacim/bağlam geçmişini ikinci kez eklemiyor ve stale olayında `reset()` çağırmıyor. Yeni hedefli test bu onarımın eksik mumu doldurduğunu ve diğer kuyrukları değiştirmediğini doğruluyor.

- `py_compile`: başarılı.
- Hedefli gösterge testleri: **16 geçti**.
- Tam pytest regresyonu: **413 geçti**.
- Gerçek paper koşusu: her borsada ayrı ayrı **>%90** kapıdan geçti; beş dakika tamamlandı.

## Sınırlamalar

OKX `instCategory=1` kategorisi ve v37 `is_stock_like` denylist’i kullanıldı. Kullanıcı tarafından yetkili ABD-kökenli varlık listesi sağlanmadı; denylist otoritatif/tam bir köken kaynağı değildir ve ticker çakışmalarında yanlış pozitif olabilir. Bu nedenle “ABD kaynaklı” sınıflandırmasının kapsamı garanti edilmez. Binance’le çakışan sembollerin Binance’te bırakılması talimata uygun uygulandı.

## Kanıt dosyaları

- Koşu logu: `run_artifacts/attempt4/v37_paper_test.log`
- Nihai durum: `logs/ws_durum.json`
- Nihai kapanış: `logs/ws_kapanis.json`
- İşlem CSV’si: `live_trades.csv` (başlık dışında satır yok)
- Sinyal CSV’si: `logs/ws_olay.csv` (başlık dışında satır yok)
- Önceki tamamlanmamış koşunun arşivi: `run_artifacts/attempt3/`
