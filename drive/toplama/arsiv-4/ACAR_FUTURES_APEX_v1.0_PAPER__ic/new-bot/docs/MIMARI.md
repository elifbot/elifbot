# Mimari

Uygulama yalnızca **paper trading** yapar. Binance USDT-M Futures ve OKX'in
USDT-settled linear Futures/Swap adaptörleri herkese açık market-data GET
uçlarına erişir; API anahtarı, özel hesap uçları ve
borsaya emir gönderme kodu içermez. Emirler yalnızca `infra/paper.py` içindeki
yerel sanal deftere kaydedilir.

## İki motor

- **Motor 1 — FADE:** Sinyal yalnız kapanmış 5m mumlarda hesaplanır. İtki
  `close[-1] / close[-3] - 1`; RVOL son mum hacminin önceki 20 mum ortalamasına
  oranıdır. İtki **-%0.35'in altında** ve RVOL **>= 2.0** ise LONG; SHORT yok.
- **Motor 2 — Trend/Momentum:** EMA20 > EMA50 ve MACD line > signal ise LONG;
  EMA20 < EMA50 ve MACD line < signal ise SHORT. Stop mesafesi `2.5 * ATR(14)`
  (fiyat yüzdesi) olarak hesaplanır.
- İki motor her sembolde değerlendirilir. Aynı mumda ters yöne sinyal verirlerse
  yeni işlem açılmaz (`motor=conflict`). Aynı yöne sinyal oluşursa Motor 1
  önceliklidir. Pozisyonlar her iki motora ve borsaya ortak paper portföyündedir;
  aynı dayanak varlıkta ikinci pozisyon açılmaz. Diğer borsada aynı sözleşmenin
  fiyatı alınabiliyorsa mevcut paper stop/zaman çıkışı yine kontrol edilir.
- `core/symbols.py` içindeki 19 dayanak varlık kara listesi iki motorda da
  sinyal işleme öncesi uygulanır; aynı dayanak biçimleri normalize edilir ve
  kara listedeki sembollerde backtest/işlem açılmaz.
- Risk formülündeki `d`, Motor 1'de tetikleyen iki mumluk hareketin mutlak
  yüzdesinden, Motor 2'de `2.5 * ATR(14) / fiyat` değerinden türetilir.
- Her iki motordan işlem açılabilmesi için ölçülen iki mumluk mutlak impulse
  en az `MIN_IMPULSE_PERCENT = 0.30` ve RVOL en az
  `MIN_RVOL_FOR_ENTRY = 1.5` olmalıdır. FADE'in kendi tetik koşulu daha sıkıdır:
  impulse en az %0.35 düşüş ve RVOL en az 2.0 ister.

## Risk ve çıkış

- Başlangıç paper bakiyesi: 1000 USDT.
- Pozisyon azami nominali 500 USDT; 10x kaldıraçta teminat 50 USDT.
- Boyut: `Q = min(500 / P, (25 - F) / (d * P))`; `d` iki motorda da sinyalin
  stop mesafesidir.
- `F`, azami 500 USDT nominal üzerinden maker giriş ücreti + stop taker ücreti
  + stop slippage tahminidir. Stop fiyatının olumsuz yönde `d` kadar uzamasını
  da hesaba katan maliyet varsayılır. Varsayılan oranlar sırasıyla maker %0.02,
  stop taker %0.04 ve slippage %0.05'tir.
- Stop, LONG'da giriş fiyatının `d` oranı altında, SHORT'ta üstündedir. Stop tetiklenmesi sanal
  reduce-only market çıkışı olarak modellenir; stopta aynı mumda TP de görülürse
  stop önce kabul edilir.
- Sabit TP yoktur. `KÂR_KİLİTLEME_ESİĞİ = 250.0` yalnızca momentumun
  sürdüğünü loglamak/izlemek için kullanılan kâr eşiğidir; bu seviyede işlem
  kapatılmaz. Trend pozisyonu momentum yönü aynı ve RVOL en az
  `MIN_RVOL_FOR_EXIT = 1.0` kaldığı sürece açık tutulur. Momentum yönü tersine
  döner veya RVOL 1.0 altına düşerse pozisyon piyasa simülasyonuyla kapatılır.
  FADE pozisyonlarında momentum-end ve 6-mum time-stop kuralları devre dışıdır;
  zarar, fiyat stopu ve trailing stop uygulanır.
- Brüt pozisyon kârı `TRAILING_ACTIVATION_USDT = 100.0` seviyesine ulaştığında
  trailing stop etkinleşir. LONG için görülen en yüksek fiyat (`best_price`)
  takip edilir ve stop `best_price * (1 - 2.0 / 100)` seviyesine; SHORT için
  en düşük fiyat takip edilerek stop `best_price * (1 + 2.0 / 100)` seviyesine
  taşınır. Stop hiçbir zaman gevşetilmez. Tetiklenince
  `YÜZDESEL TRAILING STOP TETİKLENDİ` loglanır. Trailing durumu ve en iyi fiyat
  SQLite'ta saklanır.
- Trend pozisyonu altı yeni 5m mumdan sonra hâlâ başabaşta veya zarardaysa zaman
  stopuyla kapatılır.
- Dinamik limit: `required = 50 / leverage + 500 * maker_fee_rate + 0.01`
  USDT; `max_positions = min(max(int((equity - 49 - 5) // required), 0), 20)`.
  Serbest marj bu gerekli bakiyenin altındaysa veya dinamik pozisyon limiti
  dolmuşsa sinyal `INSUFFICIENT_FUNDS` ya da `MAX_POSITIONS_REACHED` ile atlanır.
- Her paper fiyat güncellemesinde pozisyonun unrealized PnL'si ayrı kontrol
  edilir. `core/risk.py` içindeki `MAX_LOSS_PER_POS = 25.0` eşiğine (`PnL <=
  -25 USDT`) ulaşan pozisyon reduce-only piyasa çıkışı olarak kapatılır ve
  `STOP LOSS TETİKLENDİ: [SEMBOL] 25 USDT zarar ile kapatıldı` loglanır. Diğer
  pozisyonlar çalışmaya devam eder; botu bütünüyle durduran küresel circuit
  breaker yoktur. Günlük -100 USDT koruması yeni girişleri engeller.
- UTC günündeki gerçekleşmiş PnL ile açık pozisyonların anlık unrealized PnL'si
  toplamı `DAILY_MAX_LOSS_USDT = 100.0` USDT zarara ulaştığında yeni girişler
  engellenir; açık pozisyon yönetimi devam eder. Gerçekleşmiş PnL SQLite close
  kayıtlarından alındığı için yeniden başlatma ile sıfırlanmaz.
- Girişler bir tick fiyat iyileştirmeli `post_only` paper limit emri olarak
  kaydedilir. Borsaların public metadata'sından tick size ve REST order book
  derinliği okunur. Planlanan miktarın karşı emir defterinde yürütülmesi
  varsayılarak VWAP kaynaklı adverse slippage giriş fiyatına yansıtılır;
  karşılanmayan miktar için ilave %0.2 olumsuz fiyat etkisi uygulanır.
  Order book alınamazsa giriş atlanır. Bu muhafazakâr paper tahminidir;
  gerçek borsaya emir gönderilmez ve maker dolum garantisi verilmez.

## Katmanlar

1. `infra/exchanges/`: Binance / OKX public REST Futures enstrüman, mum,
   ticker ve order book verisi ile public WebSocket ticker ve işlemler akışları.
   Binance `aggTrade` ve OKX `trades` eventleri 15 dakikalık saniye hacmini
   oluşturur; OKX sözleşme büyüklüğü para birimi metadata'sıyla USDT'ye çevrilir.
   Hacim patlaması girişleri için FADE ve Trend motorları aynı yönü onaylar.
   Binance
   control Ping/Pong, OKX text Ping/Pong heartbeat kullanır. Bağlantı koparsa
   ortak reconnect katmanı üstel 1/2/4/8 saniye bekler ve her denemeyi loglar.
2. `infra/paper.py`: maker-only sanal giriş ve reduce-only sanal çıkış.
3. `core/`: FADE ve Trend/Momentum sinyalleri, yön bağımsız risk
   boyutlandırması ve portföy hesabı.
4. `app/`: CLI ve paper executor.
5. `state/store.py`: SQLite WAL paper state ve işlem geçmişi.
6. `safety/`: log redaksiyonu, yerel uyarılar ve isteğe bağlı Telegram bildirimi.
7. `backtest/`: geçmiş mumlarda sonraki mum açılışından giriş simülasyonu.

## Güvenlik ve araştırma sınırlamaları

- Çalıştırmak için `--paper` bayrağı zorunludur. Canlı işlem modu yoktur.
- Her borsa istemcisi yalnızca herkese açık market-data uçlarını kullanır;
  emir gönderme uç noktası veya kimlik doğrulama yoktur.
- Sürekli tarama Binance `!miniTicker@arr` ve OKX `tickers` akışlarını pozisyon
  fiyatı için, Binance `aggTrade` ve OKX `trades` akışlarını gerçek saniyelik
  quote-volume hesabı için kullanır. 15 dakikalık baseline ısınması gerekir.
  Minimum 24h likidite 1,000,000 USDT, spike çarpanı varsayılan 3.0'dır.
- `--symbols ALL` seçili borsalarda USDT-settled etkin Futures/Swap
  sözleşmelerini 24 saatlik quote hacmine göre sıralar. Kara liste uygulandıktan
  sonra borsa başına en likit ilk 100 sözleşme taranır. OKX sıralaması public
  API'nin `volCcy24h × last` turnover tahminini kullanır.
- Public API hatası ilgili sembol/borsa için loglanır ve sonraki sembol ile
  diğer borsalar taranmaya devam eder. Hiçbir kullanılabilir piyasa havuzu yoksa
  başlangıç fail-closed olarak sonlanır.
- İsteğe bağlı Telegram uyarıları `TELEGRAM_BOT_TOKEN` ve
  `TELEGRAM_CHAT_ID` ortam değişkenleriyle veya proje dizinindeki `.env`
  dosyasıyla açılır. Pozisyon açılışları, stop çıkışları ve kritik hatalar
  bildirilir. Token loglanmaz; `.env` depoya eklenmemelidir. Ayar yoksa
  bildirimler yerel logda kalır.
- SQLite dosyası oluşturulduğunda `0600`, yeni üst dizin `0700` izinleriyle
  korunur. Durum kaydına API anahtarı/secret yazılmaz.
- Bu depoda atıf yapılan 60.000 işlem raporu/veri seti bulunmadığından FADE
  eşiklerinin veriyle bağımsız doğrulandığı iddia edilmez. Backtest sonuçları
  ücret, slippage ve candle fill varsayımlarına duyarlıdır.
