# Çalıştırma

Python 3.10+ ve `requirements.txt` içindeki WebSocket bağımlılığı gerekir.
Komutları `new-bot/` dizininden çalıştırın.

```bash
python -m pip install -r requirements.txt
```

## İsteğe bağlı Telegram bildirimleri

Proje dizininde `.env` oluşturun (veya aynı değişkenleri ortam değişkeni olarak
tanımlayın):

```dotenv
TELEGRAM_BOT_TOKEN=123456789:bot-token
TELEGRAM_CHAT_ID=123456789
```

Telegram ayarı yoksa bot yalnızca yerel log üretir. Ayarlar mevcutsa pozisyon
açılışları, stop çıkışları ve kritik hatalar Telegram'a bildirilir. Gerçek
token'ı kaynak koda veya paylaşılan arşive koymayın.

## Testler

```bash
python -m unittest discover -s tests -v
```

## Tek public-data çevrimi

```bash
python -m app.main --paper --exchange binance --symbols BTCUSDT --once
```

`--once` yalnızca REST tabanlı bir kerelik doğrulama modudur. Sürekli WebSocket
izlemesi için `--once` kullanmayın.

OKX için `--exchange okx`, iki borsa için `--exchange all` veya
`--exchange binance+okx` kullanın. Sürekli çalışmada (`--once` olmadan)
Binance `!miniTicker@arr` ve OKX public ticker WebSocket akışları izlenir;
başlangıçta USDT Futures/Swap enstrümanları yüklenir, blacklist hariç bütün
enstrümanlar izlenir. OHLCV yalnızca hacim patlaması bulunan coinlerde çekilir.
Ek olarak açık pozisyonlar için 5 dakikalık kapanışlarda OHLCV kontrol edilir;
bu, mevcut momentum/time-stop çıkışlarını korur.
Pozisyon çıkışlarında mevcut public ticker fiyatı kullanılır; aynı 5 dakikalık
bar içindeki ticker fiyatı, borsadan gelen o anki OHLC aralığının dışındaysa
çıkış reddedilir ve `HATALI FİYAT VERİSİ REDDEDİLDİ` loglanır. Yüzdesel fiyat
sapma eşiği kullanılmadığından, mum ve ticker aynı gerçek pump fiyatını
doğrularsa büyüklüğünden bağımsız şekilde kabul edilir. Binance/OKX mum
uç noktalarının kline satırları sembol alanı taşımaz; bu nedenle mum sembolü
yanıt gövdesinden ayrıca doğrulanamaz. Canlı ticker uç noktalarının döndürdüğü
sembol/enstrüman ise istenen sembolle birebir eşleştirilir.
Başlangıç paper bakiyesi varsayılan olarak
1.000 USDT'dir. Pozisyon başına azami nominal 500 USDT, teminat 50 USDT (10x),
maker komisyonu ve 0.01 USDT funding buffer gerekir. Açık pozisyon limiti
equity'den dinamik hesaplanır ve `MAKS_POZ_SABİT = 20` üst sınırını aşmaz.
İşlem açmak için ölçülen mutlak impulse en az %0.30, RVOL en az 1.5 olmalıdır;
altındaki sinyaller `rejection=dusuk_momentum` veya `rejection=dusuk_hacim`
ile atlanır. Serbest marj yetersizse
sinyal `INSUFFICIENT_FUNDS` ile atlanır. Her pozisyonun gerçekleşmemiş zararı
25 USDT'ye ulaştığında yalnızca o pozisyon reduce-only piyasa çıkışıyla
kapatılır; diğer pozisyonlar ve tarama çalışmaya devam eder. Eşik
`core/risk.py` içindeki `MAX_LOSS_PER_POS` değişkeniyle değiştirilebilir.
Sabit take-profit yoktur. `KÂR_KİLİTLEME_ESİĞİ = 250.0` seviyesine ulaşıldığında
momentum/volume sürüyorsa pozisyon açık tutulur; Trend motorunda impulse yönü
tersine dönerse veya RVOL 1.0 altına düşerse kapanır. Giriş RVOL eşiği 1.5'tir.
FADE pozisyonlarında momentum ve 6 mum time-stop çıkışları uygulanmaz; yalnızca
pozisyon bazlı zarar, fiyat stopu ve trailing stop çalışır. Kâr 100 USDT'ye
ulaştığında stop trailing etkinleşir. LONG pozisyon stop'u en yüksek fiyattan
%2 aşağıda, SHORT pozisyon stop'u en düşük fiyattan %2 yukarıda tutulur; yeni
en iyi fiyat geldikçe stop yalnızca sıkılaşır. Tetiklenince
`YÜZDESEL TRAILING STOP TETİKLENDİ` loglanır. Eşikler `core/risk.py` içindeki
`TRAILING_ACTIVATION_USDT` ve `TRAILING_DISTANCE_PERCENT` sabitleridir
(varsayılan trailing mesafesi %2).
Sürekli paper
çalıştırmak için `--once` parametresini kaldırın;
varsayılan aday toplama aralığı 5 saniyedir. Bir aralıkta birden çok spike
oluşursa en yüksek spike çarpanına sahip ilk 30 adayın mumları değerlendirilir.
OHLCV istekleri arasında varsayılan 0.1 saniye beklenir; bu değer
`--request-delay` ile değiştirilebilir. WebSocket bağlantısı kesilirse her
borsa ayrı ayrı yeniden bağlanır; heartbeat/Ping-Pong kontrolü ve 1, 2, 4, 8
saniyeye kadar üstel geri çekilme uygulanır.

Günlük net zarar (UTC günündeki gerçekleşmiş PnL + açık pozisyonların anlık
unrealized PnL'si) -100 USDT'ye ulaştığında yalnızca yeni girişler o gün
engellenir; açık pozisyon yönetimi devam eder. Gerçekleşmiş bölüm SQLite işlem
geçmişinden hesaplandığı için süreç yeniden başlatılsa da limit sıfırlanmaz.
15 dakikalık saniye-hacim ortalaması için her sembolde 15 dakika ısınma gerekir.
24 saatlik hacim filtresi yalnızca 1,000,000 USDT ve üzeri sözleşmelerde spike
kontrolü yapar. Saniyelik hacim Binance `aggTrade` ve OKX `trades` WebSocket
olaylarından, OKX sözleşme büyüklüğü metadata'sı kullanılarak USDT notional'a
çevrilir; 24 saatlik hacim yalnızca likidite filtresidir. Hacim patlaması
adayları, 5m FADE ve EMA/MACD Trend motorlarının ikisinin de aynı yönü
onaylaması ve impulse/RVOL eşiklerini geçmesi halinde işleme alınır.
Uygulama yalnızca paper emir üretir.

```bash
python -m app.main --paper --exchange all --symbols ALL
```

Motor 1 FADE kuralına göre yalnız LONG, Motor 2 EMA20/50 ve MACD teyidiyle
trend yönünde LONG veya SHORT sinyali verir. Sinyaller aynı dayanak varlıkta
çakışırsa işlem atlanır; ortak risk katmanı her iki motorun stop zararını
komisyon/slippage tahmini dahil 25 USDT ile sınırlar.
Her iki borsa ve motor birlikte dinamik limite kadar pozisyon tutar; dolu
limitte gelen sinyaller `MAX_POSITIONS_REACHED` koduyla atlanır. Küresel
circuit breaker yoktur; UTC günlük -100 USDT net zarar sınırı (gerçekleşmiş PnL
ve açık pozisyonların unrealized PnL'si) yalnızca yeni girişleri engeller.
Public API hataları
loglanıp sonraki piyasa taranır; kullanılabilir piyasa havuzu yoksa başlangıç
devam etmez.

SQLite durum dosyasını `--state /path/to/paper_state.sqlite3` ile belirleyin.
`--balance` yalnızca yeni paper defteri için başlangıç bakiyesidir; var olan
durum dosyasındaki bakiye geri yüklenir. Yeni 1.000 USDT defteri başlatmak
istiyorsanız daha önce kullanılmamış bir `--state` yolu verin.
`--paper` bayrağı zorunludur:
uygulamanın canlı emir modu yoktur. Girişler bir tick iyileştirmeli post-only
paper limit emri olarak kaydedilir. 3 saniyelik canlı borsa emir zaman aşımı
uygulanmaz; canlı emir defteri, gönderim ve iptal uç noktaları kullanılmaz.
İnternet bağlantısı public API verisi için
gereklidir; API anahtarı tanımlamayın.
Yeni paper girişlerinde public order book derinliği okunur; planlanan miktarı
defter seviyelerinde yürütmenin oluşturduğu fiyat etkisi simüle edilir. Defter
derinliği yetersizse kalan miktar için ilave %0.2 olumsuz kayma varsayılır.
Order book erişilemiyorsa yeni giriş fail-closed olarak atlanır. Bu bir dolum
garantisi değildir ve canlı emir göndermez.

İlk 23 mum RVOL 20 dönem ısınması içindir; bu sürede işlem sinyali oluşmaz.
Paper maker dolumları, mum verisi üzerinden varsayıldığı için gerçek emir
defteri dolumunu veya gerçek kârlılığı temsil etmez; canlı akışta order book
fiyat etkisi ayrıca paper giriş maliyetine yansıtılır. Bir borsanın public API'si
çökerse hata loglanır, diğer borsanın taraması sürer.
