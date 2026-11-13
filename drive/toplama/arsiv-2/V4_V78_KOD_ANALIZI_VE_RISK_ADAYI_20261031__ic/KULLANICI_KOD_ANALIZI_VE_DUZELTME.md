# V4 + v7.8: paylaşılan testlerin analizi ve ayrı aday düzeltmesi

## Kapsam ve sonuç

Paylaşılan Markdown ile test kodu incelendi; bunlar Codespace'teki uygulamanın kendisi değildir. Bu nedenle oradaki 523 test, Compose build, watcher, state güvenliği ve kod hashleri burada doğrulanmış sayılmaz. Arena'da, önceki ayrı adayın **yeni bir kopyası** üzerinde çalışıldı. Canlı borsa bağlantılı koşu veya Compose servisi başlatılmadı; API anahtarı ve gerçek emir kullanılmadı.

- Kendi adayımızın tam ağsız paketi: **575 passed in 50.93s** (`TAM_AGSSIZ_TEST_YENI.txt`).
- Bunun yanı sıra, kullanıcının portföy düzeyindeki dört UTC testinin eşdeğerleri **ayrıca** çalıştırıldı: **4 failed** (`karsilastirma/TEST_KULLANICI_SONUCU.txt`). Bunlar 575'lik pakete dahil değildir ve uyumsuzluğu gizlememek için bağımsız tutulmuştur.
- Önceki 17 PnL/risk muhasebesi testi adayda zaten vardı ve geçti; eklenen geleceğe tarihli fiyat testiyle bu dosya **18 passed**.

## En önemli ayrım: portföy ile bot katmanı

Bu adayda UTC gün yönetimi `ws_bot.Bot._gunluk_risk_guncelle` düzeyindedir; `PaperPortfolio`'da `roll_daily_period` veya `daily_period_unknown` yoktur. Dört karşılaştırma testinden biri ertesi gün hâlâ günlük zarar nedeniyle reddedilir; üçü bu API eksikliğiyle hata verir. Bot yolunda geçişe ilişkin ayrı ağsız testler vardır, ancak bunlar **doğrudan portföy API'sinin veya diğer çağıranların güvende olduğunu kanıtlamaz**. `main.py` ve `backtests/engine.py` portföyü doğrudan çağırır; günlük UTC davranışını bot sarmalayıcısı üzerinden otomatik almazlar. Bu açık sorun çözülene dek tüm yollar için günlük limit düzeldi denemez.

## Gece yarısı açık pozisyon testi

Paylaşılan `test_open_position_rolls_daily_risk_with_live_position` pozisyonun gece yarısından 10 saniye önce ve 10 saniye sonra 90 fiyatında olmasından, sıfırlamanın güvenli olduğunu varsayıyor. Bu, gerçek 00:00 equity'sini kanıtlamaz. Örneğin LONG 10 birimlik pozisyonda fiyat 23:59:50'de 90, tam 00:00'da 100, 00:00:10'da yeniden 90 olabilir. İki gözlem aynıyken gece yarısından sonraki 100 USDT zararı 00:00:10 fiyatıyla başlangıç almak gizleyebilir. İlk equity yaklaşık 999,5 USDT ise bu yaklaşık %10'luk gündüz zararıdır. İki uç nokta veya 120 saniyelik tazelik, ara değeri kesin olarak belirlemez.

Bu yüzden, kullanıcının talep ettiği fail-closed güvenliği korumak amacıyla bu aday açık pozisyonla gece yarısı geçişinde yeni girişleri belirsiz kilitler. Burada söz konusu testin beklediği otomatik açılma uygulanmadı. Kesin sınır fiyatı doğrulanacak bir kaynak/protokol bulunmadan veya kullanıcı bilinçli bir tahmin politikasını açıkça onaylamadan daha gevşek davranış benimsenmemeli.

## Bu ayrı kopyada yapılanlar

1. **Uzun gözlem boşluğu:** Önceki Arena adayında hesap flat iken 30 Ekim 12:00 → 31 Ekim 12:00 aralığında günlük başlangıcın güvenliymiş gibi resetlendiği sentetik testle gösterildi (`ONCE_UZUN_BOSLUK.txt`). Bot katmanına 30 saniyede bir kalıcı UTC checkpoint eklendi. Yeni güne otomatik reset yalnızca hesap flat, funding outbox boş, son geçerli checkpoint sınırdan önceki 60 saniye içinde ve ilk işlem sınırdan sonraki 60 saniye içindeyse değerlendirilir; uzun aralık, eksik checkpoint, funding outbox veya açık pozisyonda yeni giriş bilinmeyen durumuna geçer. Aynı gün restart, checkpoint restart, manuel engel, yazım hatası ve açık pozisyon test edildi.
2. **Gelecek tarihli fiyat:** `PaperPortfolio.open_position` bayat fiyat kontrolünde negatif yaşlı geleceğe tarihli fiyatları daha önce kabul ediyordu; önce ağsız olarak hatalı kabul gösterildi (`ONCE_GELECEK_FIYAT.txt`), ardından bu fiyatlar reddedildi. Normal yaş eşiği gevşetilmedi. `price_ts` verilmeyen diğer çağrı yolları bu kontrolden yararlanmaz.
3. **Binance günlükleri:** Bu adayın hazır olduktan sonraki 60 saniyelik watcher'ı ve hazırlık onarımı için eksik UTC dakika gözlemi, istenen dakikalar, REST ile eklenenler, kalanlar ve sonraki turda gerçekten bellekte görülerek iyileşen dakikalar ayrıştırıldı. Sonraki gözlem bir iyileşmenin kaynağını kendiliğinden REST'e atfetmez. Kapanmış mum zaman damgası, başka akışla yarış ve bağlantı nesli kontrolleri korunur. Testler tamamen sahte ağ ile yapıldı; gerçek piyasa boşluğu ölçülmedi.
4. **Sınır zamanı test tutarsızlığı:** Ara tam pakette iki eski entegrasyon testi başarısız oldu, ayrı tekrarları geçti (`ARA_ZAMANA_BAGLI_TEST_HATASI.txt`). Testler gerçek beş dakikalık mum sınırının ilk iki saniyesine düşebiliyor; üretimin 2 sn mum-kapanış guard'ı bu zamanda sentetik son mumu doğal olarak reddediyor. Test saati aralığın ortasında sabitlendi, gerçek 2 sn guard'ı değiştirilmedi; 1.999 ms ret / 2.000 ms kabul sınır testi eklendi. Ara hata ve son sonuç korunmuştur.

**Checkpoint sınırı:** 60 saniyelik pencere yalnızca o aralıkta gözlem olduğuna dair işletimsel koşuldur; pozisyonlu hesapta tam gece yarısı equity'sinin kesin kanıtı değildir. Flat hesap için bile geç gelen funding, harici nakit değişikliği, dosya sistemi arızası veya kaybedilen olayların yokluğu bu testlerle ispatlanamaz. 30 saniyede bir state yazımının canlı sistem performansı ölçülmedi.

## Açık riskler

- `PaperPortfolio`'ya doğrudan erişim yukarıda açıklandığı gibi UTC-risk uygulamasını atlar. Tek doğru risk/state katmanına taşıma ve bütün çağrı yollarının güvenli entegrasyonu gereklidir.
- Gece yarısı equity bilinmeyen durumda güvenilir mutabakat ve açık operatör onayı ile blokeyi kaldıracak araç hâlâ yoktur; pozisyon kapansa bile yeni giriş kilitli kalır. Bu bir **7/24 çözümü değildir**.
- Var olan `_kapat_ve_kaydet` paper kapanışı state yazımı istisnasında tutarlılık için bellekte geri alır. Bu nedenle risk guard'ı kapanışı engellemese de depolama arızasında kapanış engellenebilir. Bu önceki davranışın düzeltilmesi, restart ve funding muhasebesi için açık mutabakat tasarımı gerektirir; bu kabul koşulu henüz tam karşılanmadı.
- Dizin fsync sonucu belirsizleşirse girişler çalışan süreçte fail-closed olur; sistemin depolama kalıcılığı belirsizken sonraki restart'ta eksiksiz kurtarma garanti edilemez.
- `test_multi_exchange_isolation` aynı yön sayımının borsa bazında ayrılığını test eder; tüm limitlerin ayrılmasını kanıtlamaz. Toplam pozisyon ve bazı portföy limitleri ortaktır. `test_balance_never_negative`, modelin izole marj varsayımı ve zarar tavanı altındaki testidir; gerçek borsa tasfiyesinin veya tüm piyasa koşullarının doğrulanması değildir.
- Funding kalabalık yön filtresi hâlâ stratejiden bağımsızdır; eşiği **0.0005** ve `funding_crowding_opposes_fade` etiketi korunmuştur. Momentum politikasını kullanıcının izni olmadan değiştirmedik. MTF, teyit ve indikatör eşikleri gevşetilmedi.
- Kullanıcının Markdown'ındaki 11/11 hash ifadesi kendi önceki paket bağlamına aittir; bu yeni Arena kopyasında `ws_bot.py`, scanner ve `portfolio/paper_futures.py` değiştiği için o eşitlik bu sürüm için iddia edilmez.

## Saat ön kontrolü ve sonraki aşama

Salt `paper_5dk_supertrend_supervisor.py --preflight-only` çalıştırıldı; bot veya servis başlatmaz. 2026-10-31 18:36:42 UTC ölçümünde timedatectl `yes`, Chrony bound yaklaşık 0.000905 sn olsa da doğrudan `adjtimex` `TIME_ERROR` (5) ve `STA_UNSYNC` (64) döndürdü; **preflight başarısız**. Bu tek başına ölçülmüş büyük saat farkı değildir ama güvenlik kapısı geçmedi. Başka makinede sonuç farklı olabilir. Koruma bypass edilmedi.

Sonraki doğru adım: kullanıcının gerçek birleşik paketini veya en az `portfolio/paper_futures.py`, `ws_bot.py`, Binance watcher, `scanner/signal_intel.py`, supervisor/clock dosyaları, `compose.yaml`, testler ve ilgili state şemasını incelemek; tek günlük risk katmanını güvenli hâle getirmek, bu dört portföy testinin güvenli sözleşmesini yeniden yazmak, depolama arızasında kapanış/mutabakat tasarımını test etmek ve ardından güvenilir saatte yalnız önceden kararlaştırılmış 5 dakikalık Binance+OKX public-data paper testi yapmaktır. Önceki kanıtlar/DB'ler korunmalı, uzun veya 7/24 çalışma bu sonuçlar görülmeden başlatılmamalıdır.
