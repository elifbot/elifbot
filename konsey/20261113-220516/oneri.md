## mimar
Sistem mimarı olarak, v9 smoke verisindeki %81 churn (REJIM_DONUS) ve %15.9 WR oranını düzeltmek için kanıtlara dayalı 4 yama önerim şudur:

### 1. REJIM_DONUS Çıkış Filtresi (Teyit Mekanizması)
**Sorun:** İşlemlerin %81'i rejim dönüşüyle kapanıyor ve PF 0.676. Bu, sinyalin "gürültü" ile "trend değişimi"ni ayıramadığını kanıtlar.
**Yama:** `rejim.py` içerisinde, mevcut rejim değişim sinyalini doğrudan çıkışa bağlamak yerine, `ws_bot.py:86-92` ve `ws_bot.py:111-117` dosyalarında kanıtlanan **CASCADE EŞİĞİ** mantığını çıkışa entegre et.
**Kod Değişikliği:** `REJIM_DONUS` tetiklendiğinde, eğer son 60 saniyedeki toplam sinyal sayısı $\ge 3$ (Eşik 3: %80.7 isabet kanıtı) değilse, pozisyonu kapatma; sadece "izleme" moduna al.

### 2. Giriş Sinyali RVOL Filtresi (Churn Azaltma)
**Sorun:** Düşük WR (%15.9), düşük hacimli/gürültülü girişlerin çok olduğunu gösterir.
**Yama:** `sinyaller.py` içerisinde, giriş şartına `rvol` alt sınırı ekle.
**Kanıt:** `test_trading_system.py:69-75` satırlarında `FadeStrategy` için `signal.rvol >= 2.0` şartının başarılı olduğu ve `signal.impulse_pct < -0.35` ile korele çalıştığı doğrulanmıştır.
**Kod Değişikliği:** Tüm giriş sinyallerine `if signal.rvol < 2.0: return HOLD` filtresini uygula.

### 3. Stop Mesafesi ve Maliyet Optimizasyonu
**Sorun:** Pozisyon başına -10$ stop kuralı ile işlem başına 0.50$ komisyon (toplam 24.66$) arasında uyumsuzluk var. Mevcut stoplar sabit yüzdeyle hesaplanıyor.
**Yama:** `bot/v9/motor.py` (veya `ws_bot.py:1062-1068`) içerisindeki stop hesaplamasını, net -10$ kaybı (komisyon dahil) hedefleyecek şekilde dinamikleştir.
**Kod Değişikliği:** 
`stop_pct = (10 - 0.50) / (50 * 10) * 100` $\rightarrow$ `%1.9`
Sabit `self.sl_pct` yerine, net kaybı 10$'a sabitleyen `stop = giris_fiyat * (1 - 0.019)` (LONG için) formülünü uygula.

### 4. Sinyal Motoru "Trend" Teyidi
**Sorun:** `REJIM_DONUS` çıkışlarının yüksekliği, ters yönde zayıf sinyallerle pozisyon kapatıldığını gösterir.
**Yama:** `sinyaller.py` içerisinde, çıkış tetikleyen ters sinyalin `motor` tipini kontrol et.
**Kanıt:** `test_trading_system.py:128-134` satırlarında `up_signal.motor == "trend"` ayrımı yapıldığı görülmektedir.
**Kod Değişikliği:** Sadece `motor == "trend"` olan ters sinyaller `REJIM_DONUS` çıkışını tetikleyebilsin; `fade` veya `noise` tipi sinyaller pozisyonu kapatmasın.

## risk_subayi
Risk subayı olarak raporu inceliyorum. Veriler korkunç: **%15.9 WR** ve **0.676 PF** ile kasa eriyor. En büyük sorun, işlemlerin %81'inin `REJIM_DONUS` ile kapanması; yani sistem kârı realize edemeden veya stopu beklemeden "rejim değişti" diyerek pozisyonu terk ediyor (churn). Komisyonlar (24.66$), toplam kârı yutacak seviyede.

Sayılar değişmez: **1000$ Kasa / 50$ Teminat / 10x / -10$ Stop.**

İşte churn'ü azaltacak ve çıkışları disipline edecek 4 somut yama:

### 1. `rejim.py`: REJIM_DONUS Çıkışına "Kâr Eşiği" Filtresi
Mevcut durumda rejim değiştiği an pozisyon kapanıyor. Bu, küçük kârları veya hafif zararları sürekli realize ederek churn'ü artırıyor.
*   **Yama:** `REJIM_DONUS` sinyali geldiğinde, eğer pozisyonun mevcut PnL'i $\ge 0$ değilse veya belirli bir minimum kâr eşiğine ulaşmamışsa, çıkış emrini askıya al ve `STOP` veya `TP` bekle.
*   **Kod Mantığı:** `if signal == "REJIM_DONUS" and current_pnl < 0: return "HOLD"`

### 2. `sinyaller.py`: REJIM_DONUS Teyit Mekanizması (Confirmation)
Rejim dönüşleri anlık gürültüden etkileniyor olabilir.
*   **Yama:** Rejim dönüş sinyalini tek bir mum/bar yerine, ardışık 2 bar boyunca aynı yönlü rejim değişikliği onaylandığında tetikle.
*   **Kod Mantığı:** `if current_regime != prev_regime and current_regime == last_confirmed_regime: trigger_exit()`

### 3. `motor.py`: Stop Mesafesi ve Komisyon Optimizasyonu
İşlem başına 0.50$ komisyon, -10$ stop limitinin %5'ini daha işlem başında götürüyor.
*   **Yama:** Stop mesafesini, komisyon maliyetini içerecek şekilde "net -10$" olacak şekilde kalibre et. Stop tetiklendiğinde kasadan çıkan toplam rakamın (komisyon dahil) 10.50$ olmamasını, net 10$ olmasını sağla.
*   **Kod Mantığı:** `stop_price = entry * (1 - ( (10 - commission) / (notional * leverage) ))` (Sayılar sabit kalır, sadece stop tetiklenme noktası komisyon kadar yukarı/aşağı çekilir).

### 4. `motor.py`: Eşzamanlı Pozisyon Korelasyon Kilidi
Sınırsız pozisyon izni var ancak 60 sembolde aynı anda işlem açmak, korelasyon nedeniyle tek bir piyasa hareketinde kasanın %30'unu (maksDD -30.38$) anında kaybetmek demek.
*   **Yama:** Aynı sektörden (örn: tüm Layer 1'ler veya tüm AI coinleri) aynı anda en fazla 3 pozisyon açılmasına izin veren bir "Sektör Kilidi" ekle.
*   **Kod Mantığı:** `if sector_count(symbol) >= 3: return "SKIP_SIGNAL"`

---

### EN KÖTÜ DURUMDA KASA NE OLUR?

**Senaryo:** Tüm botların aynı anda korele sembollere girdiği ve piyasanın sert ters döndüğü durum.

*   **Maksimum Pozisyon Sayısı:** Sınırsız denmiş ancak kasa 1000$, teminat 50$. Teorik olarak 20 pozisyon açılabilir.
*   **Tek İşlem Zararı:** -10$ (Net Stop).
*

## icra
**Kağıtta Çalışır vs. Borsada Çalışır**

"Kağıtta çalışır", `MakerFillSimulator` (kanıt: `paper.py:54`) gibi idealize edilmiş modellerle, kaymanın (slippage) sabit olduğu, emirlerin her zaman limit fiyattan dolduğu ve borsa reddinin (exchange reject) olmadığı bir dünyadır. "Borsada çalışır" ise; **kısmi dolumların** (partial fills) pozisyon büyüklüğünü bozduğu, **post-only** emirlerin fiyat kaydığında reddedildiği, **idempotency** eksikliğinde aynı emrin iki kez gönderildiği ve **borsa reddi** sonrası botun "pozisyonum var" sanıp boşluğa emir gönderdiği gerçekliktir.

---

**SİSTEM İYİLEŞTİRME YAMALARI (v9 Motor)**

Veriler; yüksek churn (%81 REJIM_DONUS) ve düşük WR (%15.9) ile sistemin "sinyal gürültüsüne" yenik düştüğünü, komisyonların ise kârı erittiğini gösteriyor.

**1. `rejim.py`: Rejim Dönüş Filtresi (Churn Azaltma)**
`REJIM_DONUS` çıkışlarını doğrudan tetiklemek yerine, karşıt sinyalin (opposite signal) en az 2 bar boyunca onaylanmasını şart koşan bir "Confirmation Window" ekle.
*   **Yama:** `if current_regime != prev_regime:` kontrolünü `if current_regime != prev_regime and confirmation_count >= 2:` şeklinde güncelle.

**2. `sinyaller.py`: Dinamik Giriş Eşiği (WR Artırma)**
Sinyal üretilen her pariteye girmek yerine, volatiliteye (ATR) bağlı bir giriş filtresi ekle. Sadece volatilite ortalamanın üzerindeyken giriş yap.
*   **Yama:** `if signal == 'BUY':` satırından önce `if current_atr > (avg_atr * 1.2):` kontrolü ekle.

**3. `bot/v9/motor.py`: Stop-Maliyet Senkronizasyonu (Stop Optimizasyonu)**
İşlem başına 0.50$ komisyon, -10$ stop'un %5'ini götürüyor. Stop mesafesini, komisyonu içerecek şekilde "net -10$" olacak şekilde revize et.
*   **Yama:** Stop hesaplama satırını `stop_price = entry_price - (10 + total_commission) / (quantity * leverage)` şeklinde güncelle.

**4. `bot/v9/motor.py`: REJIM_DONUS Teyit Mekanizması (Çıkış İyileştirme)**
`REJIM_DONUS` ile kapanan işlemlerin %81'i churn yaratıyor. Çıkış emrini market yerine, mevcut fiyatın 1-2 tick uzağına `post-only` limit olarak gönder; dolmazsa 30 saniye sonra market ile kapat.
*   **Yama:** `exit_order(type='MARKET')` fonksiyonunu `exit_order(type='LIMIT', post_only=True)` ile değiştir ve bir `timeout` mekanizması kur.

**Özet Etki:**
*   **Churn:** $\downarrow$ (Teyit mekanizması ile)
*   **WR:** $\uparrow$ (Volatilite filtresi ile)
*   **Net PnL:** $\uparrow$ (Komisyon-stop uyumu ile)

## test
Test mühendisi şapkasıyla, paylaşılan gerçek veri setindeki (v9 smoke) düşük WR (%15.9) ve yüksek churn (%81 REJIM_DONUS) oranlarını analiz ettim. "Kanıtlanamıyorsa yoktur" ilkesiyle, mevcut veri setindeki en büyük sızıntı, çıkış sinyallerinin (REJIM_DONUS) piyasa gürültüsünden ayırt edilememesi ve işlem başına 0.50$ maliyetin, -10$ stop mesafesiyle olan matematiksel uyumsuzluğudur.

İşte `bot/v9/motor.py`, `rejim.py` ve `sinyaller.py` dosyaları için 4 somut yama önerisi:

### 1. REJIM_DONUS Teyit Mekanizması (Churn Azaltma)
**Dosya:** `rejim.py`
**Sorun:** İşlemlerin %81'i rejim dönüşüyle kapanıyor ancak WR çok düşük. Bu, rejim tespitinin "yalancı pozitif" (false positive) olduğunu kanıtlar.
**Yama:** Rejim dönüşü sinyalini tek bir mumla değil, ardışık iki mumun veya bir onay göstergesinin (örneğin fiyatın rejim sınırını kırması ve orada kapanması) teyidiyle tetikle.
**Kod Değişikliği:** 
`if current_regime != prev_regime:` $\rightarrow$ `if current_regime != prev_regime and confirmation_candle_closed(symbol):`

### 2. Çıkış Filtresi: Minimum Kar Eşiği (Maliyet Uyumu)
**Dosya:** `bot/v9/motor.py`
**Sorun:** İşlem başına 0.50$ komisyon varken, REJIM_DONUS sinyali fiyat nötrken tetikleniyor. Bu, komisyonun kârı eritmesine neden oluyor.
**Yama:** REJIM_DONUS çıkışını sadece pozisyonun net kârı $\ge 1.00\$$ (komisyonun 2 katı) olduğunda veya stopa çok yakınken aktif et.
**Kod Değişikliği:** 
`if signal == REJIM_DONUS:` $\rightarrow$ `if signal == REJIM_DONUS and (unrealized_pnl > 1.0 or current_pnl < -8.0):`

### 3. Stop Mesafesi ve Maliyet Optimizasyonu
**Dosya:** `sinyaller.py`
**Sorun:** -10$ stop, 50$ giriş (10x) için %2'lik bir harekete tekabül eder. 0.50$ komisyon, her işlemde kasanın %0.05'ini götürürken, stop mesafesi çok geniş kalıyor ve WR'ı düşürüyor.
**Yama:** Giriş sinyaline "volatilite filtresi" ekle. Eğer sembolün anlık volatilitesi (ATR), -10$ stop mesafesini 3 mumdan kısa sürede tetikleyecek kadar yüksekse işleme girme.
**Kod Değişikliği:** 
`if signal_detected:` $\rightarrow$ `if signal_detected and (atr_value < stop_distance_pct):`

### 4. Sinyal Geçerlilik Süresi (Replay Tutarlılığı)
**Dosya:** `bot/v9/motor.py`
**Sorun:** Yüksek churn, sinyallerin çok hızlı üretilip tüketildiğini gösteriyor.
**Yama:** Bir sembolde REJIM_DONUS ile çıkış yapıldıktan sonra, aynı sembol için yeni bir giriş sinyali üretilmeden önce "soğuma süresi" (cool-down period) uygula (Örn: 3 mum).
**Kod Değişikliği:** 
`if can_open_position(symbol):` $\rightarrow$ `if can_open_position(symbol) and (current_time -

## olcum
Ölçüm analisti olarak verileri değerlendiriyorum:
**Örneklem (44 işlem) < 100 olduğu için bu sonuçlar bir "yön göstergesidir".**

**Mevcut Durum Analizi:**
*   **WR %15.9 / PF 0.676:** Sistem şu an zarar ediyor.
*   **Churn Problemi:** İşlemlerin %81'i `REJIM_DONUS` ile kapanıyor. Bu, stratejinin kârı realize edemeden veya stopu beklemeden "rejim değişti" diyerek pozisyonu erken terk ettiğini gösteriyor.
*   **Maliyet Baskısı:** İşlem başına 0.50$ komisyon, -10$ stop bütçesinin %5'ini tek başına tüketiyor.

Değişmez kurallar (1000$ kasa, 50$ teminat, 10x, -10$ stop) çerçevesinde, kanıt demetindeki `risk.py` ve `executor.py` mantığına dayalı 4 somut yama önerim şudur:

### 1. REJIM_DONUS Çıkışına "Kâr Eşiği" Filtresi (Churn Azaltma)
`REJIM_DONUS` çıkışlarının %81 gibi baskın bir oranda olması, sinyalin çok hassas olduğunu gösteriyor.
*   **Yama:** `rejim.py` veya `motor.py` içerisindeki çıkış mantığına; eğer pozisyon kârda değilse (`pnl <= 0`), `REJIM_DONUS` sinyalini görmezden gel ve sadece `STOP` veya `Trailing Stop` bekle kuralını ekle.
*   **Amaç:** Zarardaki pozisyonu "rejim değişti" diye kapatıp komisyon ödemek yerine, -10$ stop bütçesinin sonuna kadar şans vermektir.

### 2. Trailing Stop'u "Break-Even" (BE) ile Teyide Bağla
Kanıt demetinde (`risk.py:702-708`) trailing stop'un `pos.entry` ile karşılaştırıldığı görülüyor.
*   **Yama:** Trailing stop mekanizmasını, fiyat girişin belirli bir yüzdesi (örneğin %0.5) üzerine çıkmadan aktif etme. `pos.stop` değerini `pos.entry` seviyesine (BE) çekmeden önce `REJIM_DONUS` sinyalini "geçersiz" say.
*   **Amaç:** Pozisyonu risksiz hale getirmeden (BE yapmadan) erken çıkışları engellemek ve WR'ı artırmak.

### 3. Stop Mesafesini Komisyonla Optimize Et (Net -10$ Koruma)
Kanıt demetinde (`executor.py:1546-1552`) stop mesafesinin `max_stop_pct` ile hesaplandığı görülüyor.
*   **Yama:** `risk.py` içerisindeki stop hesaplamasına, 0.50$ komisyonu "sabit maliyet" olarak ekle. Stop seviyesini belirlerken `(10$ - 0.50$) = 9.50$` net kayıp üzerinden fiyat seviyesini hesapla.
*   **Amaç:** Komisyon sonrası net kaybın -10$ sınırını aşmamasını garanti altına almak.

### 4. ATR Tabanlı Dinamik Stop'u "Sert Stop" ile Sınırla
Kanıt demetinde (`risk.py:312-318`) `ATR+SWING` stop yapısı mevcut.
*   **Yama:** `structure_stop` hesaplandıktan sonra, bu değerin giriş fiyatından uzaklığı kontrol edilmeli. Eğer `abs(entry - structure_stop) * qty * leverage` değeri 10$'dan büyükse, stop'u zorla 10$'lık mesafeye (hard stop) çek.
*   **Amaç:** ATR'nin volatilite

## ops
Operasyonel sorumluluk kapsamında, 7/24 ayakta kalma için asgari gereksinimler ve v9 smoke verileri ışığında churn'ü azaltmaya yönelik 4 somut yama önerisi aşağıdadır.

### 1. 7/24 Operasyonel Asgari Gereksinimler
Kanıt demetine göre (`main.py`, `live_runner.py`), bir botun kesintisiz çalışması için gereken minimum yapı şudur:
*   **Kopma ve Yeniden Başlatma:** `RestartRecovery` mekanizması (bayat emir iptali ve stop restore için) ve `LiveMirror` ile durumun `store.save_mirror_state` üzerinden kalıcı hale getirilmesi.
*   **Kill Switch:** `EmergencyController` ve `daily_hard_loss` (günlük zarar freni) kontrolü.
*   **Log ve Alarm:** `setup_logging` ile log rotasyonu (sınırsız büyüme engelleme) ve `runtime_supervision` üzerinden `operational_health` (feed lag ve alarm takibi) izlemesi.

---

### 2. Sistem İyileştirme Yamaları (v9 Smoke Verisi Odaklı)

Veri: %81 REJIM_DONUS (Churn yüksek), WR %15.9, İşlem başı 0.50$ maliyet, -10$ stop.

#### Yama 1: `rejim.py` $\rightarrow$ REJIM_DONUS Teyit Mekanizması
**Sorun:** İşlemlerin %81'i rejim dönüşüyle kapanıyor, bu da yüksek churn ve düşük WR'ye yol açıyor.
**Yama:** `REJIM_DONUS` sinyalini doğrudan çıkış tetikleyicisi yapmak yerine, bir "teyit barı" veya "momentum eşiği" ekle.
*   **Kod Değişikliği:** `if current_regime != previous_regime:` kontrolüne, `and abs(momentum) > threshold` veya `and bar_count >= 2` şartı ekle. Rejim değişse bile fiyat momentumu tersine dönmeden pozisyonu kapatma.

#### Yama 2: `sinyaller.py` $\rightarrow$ Giriş Filtresi (Churn Azaltma)
**Sorun:** %15.9 WR, sinyallerin çok zayıf olduğunu veya gürültüye girdiğini gösteriyor.
**Yama:** `sinyaller.py` içerisindeki giriş koşullarına, kanıt demetinde (`main.py:860`) belirtilen **Hacim Filtresi v5.0**'ı entegre et.
*   **Kod Değişikliği:** Sinyal üretilmeden önce `taban hacim < X USDT/sn` ise sinyali `None` döndür. Likiditesi düşük paritelerde rejim dönüşleri yanıltıcıdır; sadece yüksek hacimli/RVOL stabil paritelerde işlem aç.

#### Yama 3: `motor.py` $\rightarrow$ Dinamik Stop ve Maliyet Uyumu
**Sorun:** -10$ stop, 0.50$ komisyonla birleştiğinde, düşük WR ile kasa hızla erir.
**Yama:** Stop mesafesini, giriş anındaki volatiliteye (ATR) bağla ancak üst sınırı -10$ olarak sabitle.
*   **Kod Değişikliği:** `stop_loss = min(fixed_10_usd, atr_based_stop)`. Eğer ATR çok düşükse, komisyonun etkisini azaltmak için minimum bir kâr hedefi (Take Profit) oluşmadan `REJIM_DONUS` çıkışını engelle (Break-even koruması).

#### Yama 4: `motor.py` $\rightarrow$ Çıkış Önceliği Değişimi
**Sorun:** PF 0.676 (Kayıplar kazançlardan fazla).
**Yama:** `REJIM_DONUS` çıkışını, pozisyon kârdayken "erken çık