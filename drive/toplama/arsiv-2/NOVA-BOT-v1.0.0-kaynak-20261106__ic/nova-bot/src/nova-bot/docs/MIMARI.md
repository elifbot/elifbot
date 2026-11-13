# NOVA-BOT — mimari ve karar akışı

> Bu belge kodu tekrar anlatmaz; **neden** böyle kurulduğunu anlatır. Kod:
> `nova/bot.py` (çekirdek), `nova/report.py` (rapor), `tests/test_nova.py`.

## 1. Bağımsızlık
Talep "diğerinden bağımsız, yeni bir bot" olduğu için önceki çalışmalardan
(ACARBOT/OmniStudio entegrasyonu, MEGA-BOT v6) **tek satır kod alınmadı**.
Devralınmayanlar: SQLite şeması, `ccxt` veri katmanı, panel/tema, strateji
isimleri, oylama/onay katmanı, CLI komut adları. Devralınan tek şey: borsaların
kamu uçları ve dürüstlük ilkesi (PAPER, gerçek emir yok, kârlılık iddiası yok).

## 2. Bağımlılık seçimi
Ortamda `ccxt` ve `websockets` **yok**. Bot bu yüzden yalnız `aiohttp` +
standart kütüphane kullanır: HTTP istekleri ve WebSocket bağlantıları elle
kurulur. Gösterge katmanında `pandas`/`numpy` de kullanılmaz (saf Python
döngüleri) — böylece testler ağ ve ağır paket olmadan çalışır.

## 3. Akış
```
REST instruments ──► parse_instruments ──► işlem-uygun sözleşme listesi
REST tickers     ──► 24s quote hacmi ──► borsa başına en likit N sembol
REST candles     ──► ısınma (200 mum)
WS  kline_1m     ──► kapanmış mum ──► strateji ──► kapılar ──► PAPER defteri
REST ticker      ──► çıkış kontrolü (stop / hedef / iz süren) her 2 sn
```
Kapanmış mum gelmezse REST yedeği devreye girer; ikisi de yoksa **sinyal
üretilmez** (uydurma yok).

## 4. Neden bu kapılar var
| Kapı | Engel olduğu hata sınıfı |
|---|---|
| `SPREAD` | İnce likit sözleşmelerde makas, R=2 hedefi işlem maliyetine çevirir |
| `STALE_QUOTE` | Bayat fiyatla hesaplanan R gerçekçi değildir |
| `PRICE_DRIFT` | Sinyal mumunun kapanışı ile emrin anı arasında kaçak giriş |
| `FUNDING_UNKNOWN` / `FUNDING_SOON` | Bilinmeyen veya 3 dk içinde ödenecek funding maliyeti |
| `QTY_BELOW_MIN` / `EXCHANGE_MIN_NOTIONAL` | Borsada reddedilecek emir boyu |
| `LIQ_TOO_CLOSE` / `MMR_INVALID` | Stop'tan önce tasfiye riski |
| `MAX_*` | Tek sembolde/tek yönde/korelasyonda yığılma |

Her ret `events.jsonl`'e ve `SONUC.json`'daki `stats` sözlüğüne sayaç olarak
yazılır. Rapor, "işlem yok" bilgisini **neden**iyle birlikte verir.

## 5. Ölçülen ve düzeltilen dört tasarım hatası
1. **Sembol seçimi.** İlk sürüm sözleşmeleri alfabetik alıyordu; bu, ince
   likit ve hatta kripto dışı tokenize ürünleri (ör. `ANTHROPIC-USDT-SWAP`)
   öne çıkardı. Düzeltme: borsanın kendi 24s quote hacmiyle sıralama +
   `NON_CRYPTO_NAMES` filtresi.
2. **Hacim alanı okuma.** Likidite sıralaması ilk sürümde Gate.io ticker'ında
   bulunmayan `volume_24h_usd` alanını okuyordu → sessizce 0 → Gate havuzu
   tamamen elendi. Düzeltme: her borsa kendi gerçek alanından okunur
   (Binance `quoteVolume`, OKX `volCcy24h×last`, Gate `volume_24h_quote`).
3. **Kripto dışı / tek borsalık ürünler.** Gate listesinde hisse ve endeks
   sözleşmeleri (SNDK, INTC, SOXS) var ve likidite filtresini geçiyordu. Ek
   istek gerektirmeyen bir kural eklendi: bir dayanak varlık PAPER evrenine
   girmek için **hem Binance hem OKX** listesinde bulunmalı. Referans küme iki
   borsanın kesişimi (261 dayanak); Gate'in 128 likit ürününden 54'ü kalıyor.
4. **MACD oyu.** "Histogram genişliyor" şartı, sabit eğimli trendde histogram
   sabit kaldığı için sağlıklı trendleri de eliyordu (ölçüldü: temiz yükseliş
   serisinde 0 sinyal). Düzeltme: çizgi sinyalin doğru tarafında **ve** sıfırın
   aynı tarafında. Bu dört hata `tests/test_nova.py` içinde regresyon testi
   olarak kilitlendi.

## 6. Evren kuralı (özet)
Bir sembol PAPER evrenine ancak şu dört koşulla girer:
1. sözleşme USDT marjlı ve işlem görüyor (delist/askıda değil),
2. dayanak varlık **hem Binance hem OKX** listesinde,
3. varsa borsa `listing_age` ≥ 7 gün (fiyat keşfi oturmuş),
4. borsanın bildirdiği 24s quote hacmi ≥ 2.000.000 USDT.
Sıralama borsa içinde bu hacme göre yapılır; seçilen sembol sayısı borsalar
arasında eşit dağıtılır.

## 7. Geriye dönük testin kötümser varsayımları
- Giriş **sonraki mumun açılışı** (ileriye bakış yok).
- Aynı mumda hem stop hem hedef görülürse **STOP** kazanır.
- Pozisyon kapanana kadar yeni sinyal aranmaz; çıkıştan sonra 5 mum bekleme.
- Sermaye yarıya inerse koşu durur (`EQUITY_HALT`).
- Funding sabit 0,01%/8saat varsayılır (geçmiş funding arşivi tutulmuyor).
