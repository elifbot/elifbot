> **Önceki adayın tarihsel raporu.** Bu kopyadaki son değişiklikler ve testler için `KULLANICI_KOD_ANALIZI_VE_DUZELTME.md` esas alınmalıdır.

# Ayrı aday: UTC risk, Binance mum onarımı ve saat kontrolü

## Sonuç

Bu, önceki Supertrend paper adayının ayrı bir kopyasında yapılan değişikliktir. **Canlı bağlantılı paper koşusu yapılmadı.** Düzeltmeler ağsız/sentetik testlerden geçti; bu sonuç gerçek piyasa boşluklarını, canlı sürekliliği veya kârlılığı kanıtlamaz. Eski kanıtlar ve veritabanları değiştirilmedi.

Son tam paket: **568 passed in 50.39s**. Komut: `cd aday && PYTHONPATH=../no_net:. pytest -q`. Çıktı: `TAM_AGSSIZ_TEST.txt`. Başlangıçta iki regresyonun başarısızlığı ve ara tam test sonucu da dosyalarda korunmuştur. Ara tam testte, artık otomatik state kurtarma nedeniyle bir eski testin iki bağımsız botu yanlışlıkla aynı dizini paylaşıyordu; fixture bağımsız çalışma dizinleri kullanacak biçimde düzeltildi. Eski test beklentisi gevşetilmedi.

## UTC günlük risk

- Risk etkin ve durum dosyası varsa `--durum-devam` unutulsa da durum yüklenir. Aynı günün başlangıç bakiyesi ve zararı korunur; yeni paper pozisyon, state yazılmadan başarılı sayılmaz.
- Hesap gün geçişinde pozisyonsuz ve geçerli equity'ye sahipse yeni UTC gününün başlangıç equity'si kaydedilir. Ayrı `blocked_new_positions` bayrağı sıfırlanmaz. Saatin UTC günü geriye giderse giriş bloke edilir.
- Tarihsiz/eski risk state'i veya UTC geçişinde açık pozisyon olması durumunda gece yarısı equity'si uydurulmaz; yeni girişler belirsiz olarak engellenir. Risk kontrolü kendi başına mevcut paper pozisyonun kapanmasını engellemez; çıkış ve kapanış sırasında da sınır kontrolü yapılır.
- State yazımının replace öncesi hatası giriş veya gün değişimi bakımından başarısız olur. Replace sonrası dizin fsync belirsizliğinde bellekte fail-closed uygulanır; pozisyonun geri alındığı iddia edilmez.
- **Önemli sınırlama:** Belirsiz eski state veya gece yarısı açık pozisyon sonrasında, bu adayda güvenilir sınır equity'sini doğrulayıp blokeyi güvenli biçimde çözecek otomatik ya da operatör mutabakat aracı yoktur. Pozisyon sonradan kapansa bile giriş blokesi devam eder. Dolayısıyla bu, kesintisiz 7/24 çözümü değildir.
- **Çıkış/yazım sınırlaması:** Önceden mevcut `_kapat_ve_kaydet` yolu, kapanış state yazımı istisna verirse tutarlılık için paper kapanışı bellekte geri alır ve hata yükseltir. Günlük risk guard'ı kapanışı engellemese de depolama hatası mevcut kapanış işlemini engelleyebilir. Bu davranış mevcut regresyonla korunmuştur; kullanıcının her durumda çıkışın engellenmemesi beklentisi burada tam karşılanmış değildir. Depolama kalıcılığı belirsizken yeniden başlatma sonrası mutabakat da garanti edilemez.
- Yeniden başlatma öncesi kaydedilmemiş son piyasa markları veya geç gelen funding'in gece yarısı değerlemesi bu testlerle kanıtlanmış değildir.

## Binance kapanmış mumlar

- REST yanıtı beklenirken canlı akışın eklediği mumun üzerine artık yazılmaz. Bağlantı nesli değiştiyse veya sembol durumu değiştirildiyse eski yanıt işlenmez. Tam dakika açılış/kapanış zaman damgası ve kapanmış olma koşulları doğrulanır; fiyat veya mum uydurulmaz.
- Hazırlık onarımında ve hazırlıktan sonra, ilgili Binance REST + aggTrade/aktif gösterge yolunda periyodik izleyici 60 saniyede bir son 60 kapalı dakikanın boşluk anlık görüntüsünü `aday/logs/binance_mum_bosluklari.jsonl` içine UTC olarak yazar. REST denemesi 15 saniye ile sınırlıdır; tur sonucunu veya zaman aşımını da kaydeder. İzleyici görev grubu tarafından iptal edilir. Ağsız testler birden çok turu, zaman aşımını, iptali, anlık UTC dakikayı ve yarış durumunu sınar.
- Bu kayıtlar henüz gerçek borsa verisi değildir; gerçek eksik dakikalar ölçülmemiştir. Dosya yazma/gözlem yükü ve canlı rate limit etkisi ölçülmedi. Son 60 dakikalık pencere dışındaki boşlukları keşfetme garantisi yoktur.

## Saat ve güvenli ön kontrol

Sadece `paper_5dk_supertrend_supervisor.py --preflight-only` bot başlatmadan kontrol yapar; iki sonucun da subprocess başlatmadığı sentetik testlerle sınandı. Bayraksız supervisor ön kontrolü geçerse paper botu başlatır. Diğer eski supervisor dosyalarında `--preflight-only` seçeneği eklenmedi; doğrudan çağrılmamalıdır.

Yerel saat kontrolü artık `timedatectl` ve Chrony yanında Linux `adjtimex` durumunu da okur ve `STA_UNSYNC` / `TIME_ERROR` durumunda fail-closed çalışır. 2026-10-31 18:28:09 UTC salt kontrolde `timedatectl=yes`, Chrony stratum 2, tahmini bound 0.000732 s olsa da çekirdek `state=5`, `status=64` (`STA_UNSYNC`) verdi; sonuç `ok=false`, çıkış kodu 1. Ayrı C ile okuma aynı sonucu verdi. Bu durum tek başına büyük ölçülmüş saat hatası demek değildir; ancak koruma geçmediği için bot başlatılmadı. Zaman koşulları anlık değişebilir. Kontrol yalnız desteklenen 64-bit Linux ABI'sinde doğrudan ölçüm yapar, desteklenmeyen durumda başarısız kapanır.

## Funding ve diğer kapılar

`scanner/signal_intel.py` aynı yönlü crowded funding'i `funding_crowding_opposes_fade` gerekçesiyle reddediyor; supervisor momentum seçse de bu filtre stratejiye göre değiştirilmemiştir. Önceki koşudaki retlerin açıklaması bu mevcut davranışla uyumludur. Funding, MTF, teyit, risk ve indikatör eşikleri gevşetilmedi. Kullanıcının diğer Codespace'inde bildirdiği kod ve 522 test burada bağımsız doğrulanmadı.

## Dosyalar ve fark

Önceki Supertrend adayına göre uygulama düzeyinde `aday/ws_bot.py` ve `aday/scanner/ws_scanner.py` değişti. Yeni UTC-risk, watcher ve supervisor testleri eklendi; Binance yarış testleri ve bir eski bağımsız-run fixture'ı güncellendi. Saat kontrolü `gozlem/saat_kontrolu.py` ve yalnız 5 dakikalık Supertrend supervisor'ı değişti. Doğrudan çalışma için güvenilir senkronize ana makine, belirsiz state mutabakat çözümü ve yukarıdaki kapanış/yazım sorununun tasarımı hâlâ gereklidir. Gerçek 5 dakikalık paper koşusunun sonuçları görülmeden daha uzun koşuya veya 7/24'e geçilmemelidir.
