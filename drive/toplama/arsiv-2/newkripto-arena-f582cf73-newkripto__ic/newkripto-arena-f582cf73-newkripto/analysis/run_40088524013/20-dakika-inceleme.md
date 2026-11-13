# 20 dakikalık paper kesiti — erken durdurma incelemesi

**Run:** [40088524013](https://github.com/omeracar56/kripto-bot/actions/runs/40088524013)

**Durum:** paper job `cancelled`; kanıt-kayıt job’ı başarılı.

**Kapsam:** logdaki 1–20. dakika heartbeat kesiti. Bu, planlı 60 dakikalık oturum raporu değildir.

> **Önemli:** Bu kesitteki bütün kapanışlar flash-crash sigortasıdır. Normal trailing/order-flow çıkışı ve altı Shadow varyantının nihai sonucu ölçülmemiştir.

## 1. Doğrulanan çalışma koşulları

- Başlangıç paper kasası **100.000 USDT**; her işlem **50 USDT marj, sabit 10x**; gerçek emir yok.
- Preflight iki borsayı birlikte doğruladı: **Binance 741**, **OKX 507** Futures paritesi; REST örnekleri, funding ve open interest mevcut.
- 20. dakika heartbeat’inde açık pozisyon **0**. Oturum daha sonra kullanıcı isteğiyle erken durduruldu.

## 2. Sonuç özeti (yalnız 6 zorunlu/sigorta kapanışı)

| Ölçüm | Değer |
|---|---:|
| Giriş / kapanış | 6 / 6 |
| Normal strateji çıkışı | 0 |
| Flash-crash / erken toplu kapanış | 6 |
| Brüt fiyat K/Z | +0.47 USDT |
| Toplam ücret | 2.0999 USDT |
| Funding | +0.0000 USDT |
| **Gerçekleşen net K/Z** | **-1.62 USDT** |
| Net kazanan / kaybeden | 1 / 5 |
| Medyan net | -0.58 USDT |
| Net PF (yalnız bu zorunlu kohort) | 0.50 |
| Brüt ≥ 0 iken net zarar | 2 işlem |

**Yorum:** Brüt +0,47 USDT olmasına rağmen 2,10 USDT ücret sonrası net −1,62 USDT. CC ve IWM brüt +0,05 USDT kârdayken ücretler nedeniyle net −0,30 USDT oldu. Bu, maliyet sonrası çıkış ve giriş kalitesi ölçümünün neden gerekli olduğunu gösterir; tek başına yeni bir canlı kural kanıtı değildir.

## 3. İşlem bazında giriş ve kapanış

| Sembol | Borsa / yön | Rejim | Skor / tetik | Giriş veri notu | Net K/Z | Kapanış |
|---|---|---|---|---|---:|---|
| ALCH/USDT | binance / LONG | BREAKOUT | +32.6; BEKLE→PARA_GIRISI | kapsama 14.3sn<60.0sn, emir defteri yok, defter yaşı yok>10.0sn | -0.88 | FLASH CRASH SİGORTASI |
| BEAT/USDT | okx / SHORT | TREND | -34.0; BEKLE→PARA_CIKISI | kapsama 44.5sn<60.0sn | -0.86 | FLASH CRASH SİGORTASI |
| CC/USDT | okx / SHORT | TREND | -35.3; BEKLE→PARA_CIKISI | hazır | -0.30 | FLASH CRASH SİGORTASI |
| CNPY/USDT | okx / SHORT | TREND | -25.9; BEKLE→PARA_CIKISI | işlem sayısı 2<5 | +1.61 | FLASH CRASH SİGORTASI |
| FLNC/USDT | okx / SHORT | TREND | -35.7; BEKLE→PARA_CIKISI | işlem sayısı 3<5, defter yaşı 62.0sn>10.0sn | -0.89 | FLASH CRASH SİGORTASI |
| IWM/USDT | binance / LONG | TREND | +24.2; BEKLE→PARA_GIRISI | işlem sayısı 4<5, emir defteri yok, defter yaşı yok>10.0sn | -0.30 | FLASH CRASH SİGORTASI |

Altı girişin tamamında `raw_signal=BEKLE` ve para-akışı tetiki (`PARA_GIRISI`/`PARA_CIKISI`) vardı. Bu nedenle girişler yalnız toplam skorla değil, akış verisinin kapsamı/güvenilirliği ve teknik çelişkilerle birlikte incelenmeli.

## 4. Giriş kalitesi ve veri hazır-olma bulguları

| Sembol | Teknik skor | Akış skoru | Trade / kapsama | Defter | Teknik çelişki | Volatilite kapısı |
|---|---:|---:|---|---|---:|---|
| ALCH/USDT | +59.4 | +54.1 | 13 / 14.3 sn | 0 kademe / yaş yok | 0 | kabul |
| BEAT/USDT | -37.4 | -56.5 | 13 / 44.5 sn | 20 kademe / yaş 0.518 | 2 | kabul |
| CC/USDT | -37.4 | -57.2 | 22 / 70.1 sn | 20 kademe / yaş 1.873 | 2 | kabul |
| CNPY/USDT | -25.8 | -55.8 | 2 / 66.7 sn | 20 kademe / yaş 6.329 | 2 | kabul |
| FLNC/USDT | -31.8 | -59.6 | 3 / 104.0 sn | 20 kademe / yaş 62.036 | 2 | kabul |
| IWM/USDT | +27.8 | +56.0 | 4 / 75.7 sn | 0 kademe / yaş yok | 2 | ret |

- **ALCH ve IWM:** emir defteri yok; **BEAT:** kapsama 44,5 sn (<60); **CNPY:** yalnız 2 trade; **FLNC:** 3 trade ve 62 sn bayat defter. CC veri-hazır-olma kontrolünden geçen tek giriş.
- Mevcut kodla yalnız giriş bağlamı yeniden değerlendirildiğinde teknik-harmony 1/6, volatilite kapısı 5/6 adayı kabul ediyor. Bu **gerçek Shadow sonucu değildir**; yeni run’da observer kayıtlarıyla doğrulanacak.
- Kazanan/kaybeden ayrımı için örneklem yalnız 6 ve tamamı erken sigorta kapanışı; teknik skor veya akış skoru için yeni eşik önerilmez.

## 5. Borsa ve rejim dağılımı

| Grup | İşlem | Net K/Z | Ücret |
|---|---:|---:|---:|
| Borsa: binance | 2 | -1.18 | 0.6998 |
| Borsa: okx | 4 | -0.44 | 1.4001 |
| Rejim: BREAKOUT | 1 | -0.88 | 0.3498 |
| Rejim: TREND | 5 | -0.74 | 1.7501 |

Bu dağılım yalnız betimleyicidir; OKX/Binance veya TREND/BREAKOUT için kapatma/optimize etme kararı verilmez.

## 6. Bu kesitten doğrulanamayanlar

- Altı Shadow varyantının resmi kabul/ret, Net Exit, MFE/MAE, kaçırılan kazanan ve trailing maliyet sonuçları.
- Normal bot kapanışlarının PF’si, medyan neti, borsa/rejim bazlı doğal çıkış performansı ve ilk iki işlemin netteki payı.
- 20 dakikalık tek kesitten zararsızlık veya gelecek kâr garantisi.

## 7. Yeni denemeden önce ele alınan eksikler

1. Erken iptalde kaybolan raporlar için periyodik, atomik **partial checkpoint** dosyaları ve workflow artifact/kayıt desteği eklendi; bunlar nihai closeout yerine geçmeyecek.
2. Flash-crash sigortası ilk tetiklemeden sonra aynı alarmı her tick’te tekrar üretmeyecek; reset sonrası eski fiyat çiftleri temizlenecek. Sigortanın koruma eşiği veya 50 USDT/10x kuralları değiştirilmedi.
3. Yeni deneme ayrı profille **1.000 USDT paper başlangıç kasası + her Shadow varyantında 1.000 USDT izole kasa**, 60 dakika, 50 USDT marj ve sabit 10x olarak hazırlanıyor.

## 8. Sonraki denemenin okuma kuralı

- Botun doğal kapattığı işlemler ile sigorta/manuel/erken kapanışlar ayrı kohortlarda raporlanacak.
- Shadow final dosyası oluşmazsa yalnız partial checkpoint olarak sunulacak; tam rapor gibi yorumlanmayacak.
- Yeni sonuçlar otomatik canlı kurala veya parametre optimizasyonuna dönüştürülmeyecek.

**Ham kanıt:** `paper-session.txt`, `preflight.json`, `run.json`; ayrıntılı giriş bağlamları ve işlem eşleştirmeleri `20-dakika-inceleme.json` içindedir.
