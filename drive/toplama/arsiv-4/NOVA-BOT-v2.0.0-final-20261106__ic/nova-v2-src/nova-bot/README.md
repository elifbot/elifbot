# NOVA-BOT — bağımsız PAPER vadeli işlem botu

**Sürüm:** 2.0.0 (final) · **Mod:** yalnız PAPER (kâğıt) · **Gerçek emir yolu:** yok · **Özel API anahtarı:** kullanılmaz

NOVA-BOT, önceki hiçbir botun koduyla bağlantısı olmayan, sıfırdan yazılmış bir
kripto vadeli işlem (perpetual) botudur. Borsalardan **yalnız kamu** verisi
(mum, fiyat, emir defteri özeti, funding) okur ve kararlarını **sanal** bir
deftere yazar. Hiçbir dil modeli / YZ servisi çağırmaz; dış onay katmanı yoktur.

## Neden ayrı bir bot?
Önceki çalışma (ACARBOT × OmniStudio) bir entegrasyon işiydi ve kendi mimarisini
taşıyor. Bu istek "bağımsız" olduğu için burada paylaşılan hiçbir modül, SQLite
şeması veya isimlendirme devralınmadı. Tek ortak nokta: borsaların kamu HTTP/WS
uçları ve aynı dürüstlük ilkesi (PAPER, kârlılık iddiası yok).

## Kurulum
```bash
python3 -m pip install -r requirements.txt     # yalnız aiohttp
python3 nova.py doctor                          # bağlantı + ürün tanısı
```

## Kullanım
```bash
python3 nova.py doctor                          # 3 borsa, ürün sayımı, veri kontrolü
python3 nova.py live  --minutes 15 --symbols 45 --out runs/live-15dk
python3 nova.py rejim --minutes 3  --symbols 12 --out runs/rejim   # emir açmaz
python3 nova.py backtest --symbols 60 --bars 1000 --out runs/bt    # geçmiş mumlar
python3 -m pytest -q                            # 58 çevrimdışı test
```

## v2 yetenek anahtarları (CLI)
```bash
--strateji {skor,confluence}   # confluence = 10 filtre oylaması (HTML v3.4 portu)
--conf-th 4                    # confluence eşiği (2..8)
--min-edge-ratio 1.15          # maliyet/hareket kapısı (ACARBOT EDGE_BELOW_COST); 0 = kapalı
--cooldown-dk 5                # sembolde kapanıştan sonra yeniden giriş beklemesi
--max-hold-mum 20              # kapanmış mum sayısıyla zorunlu çıkış
--dca --dca-adim 2 --dca-adet 3  # LONG DCA güvenlik emirleri (HTML v3.4 motoru)
--breadth-guard 0.35           # piyasa genişliği filtresi; 0 = kapalı
--kill                         # koşu sonunda kill switch senaryosu (test)
```
Yetenek envanteri ve kaynak eşlemesi: `docs/YETENEKLER-v2.md`.
Karşılaştırma ve gerekçeler: `docs/KARSILASTIRMA-ve-YETENEKLER.md`.

## Mimari (tek dosya, ~1.4k satır)
| Katman | Ne yapar |
|---|---|
| `VENUES` | Binance USD-M, OKX swap, Gate.io USDT vadeli için kamu uçları |
| `parse_instruments` / `parse_candles` / `parse_tickers` / `parse_funding` | Ham yanıtı doğrulanmış nesneye çevirir; bozuk yanıt **uydurulmaz**, atlanır |
| `Feed` | `aiohttp` ile REST + WS, 5 denemeli yeniden bağlanma, gecikme ölçümü |
| göstergeler | saf Python `ema, rsi, atr, adx, choppiness, stdev` (pandas/numpy yok) |
| `strategi_skoru` | 5 oylu skor: trend (EMA 9/21/55), MACD, RSI bandı, ADX>20, hacim |
| `Book` | PAPER defteri: lot adımı, borsa min. notional, spread, kayma, funding, breakeven, iz süren stop, devre kesici |
| `Store` | SQLite (WAL): `bars, signals, trades, events, equity` + `events.jsonl` |
| `report` | `SONUC.json`, `RAPOR.md` |

## Evren kuralı
Bir sembol ancak şu koşullarla PAPER evrenine girer: USDT marjlı ve işlemde ·
dayanak varlık **hem Binance hem OKX** listesinde (kripto dışı hisse/endeks
sözleşmeleri böyle elenir) · borsa `listing_age` ≥ 7 gün · borsanın bildirdiği
24s quote hacmi ≥ 2.000.000 USDT. Sıralama hacme göredir, borsalara eşit
dağıtılır.

## Karar zinciri
1. Kapanmış 1m mum geldi (WS `closed=true`; yoksa REST yedeği).
2. Yeterli geçmiş + mum tazeliği (`STALE`) kontrolü.
3. Skor ≥ `min_score` (3) ve choppiness < 62 → sinyal.
4. Kapılar sırayla: `SPREAD`, `STALE_QUOTE`, `PRICE_DRIFT`, `FUNDING_*`,
   `QTY_BELOW_MIN`, `EXCHANGE_MIN_NOTIONAL`, `LIQ_TOO_CLOSE`, `MMR_INVALID`,
   `MAX_POSITIONS / MAX_PER_MARKET / MAX_SAME_SIDE / MAX_GROSS / MAX_NOTIONAL`.
5. Pozisyon: stop `1.2×ATR`, hedef `2.4×ATR` (R = 2), 0.8R'de breakeven,
   1.0R'den sonra iz süren stop, en fazla 30 dk, günlük %2 zararda veya
   4 ardışık zararda **devre kesici**.

## Varsayılan ayarlar
sermaye 1000 · işlem riski %0.5 · en çok 4 pozisyon (piyasa başına 2, aynı yönde 3) ·
brüt tavan 1200 · işlem başına 250 · taker 5 bps + 2 bps kayma · azami makas 6 bps ·
likidasyona en az %10 mesafe.

## Dürüst sınırlar
- Gerçek emir gönderilmez; özel API anahtarı, imza, hesap, transfer kodu **yoktur**.
- Dolum modeli iyimser değil ama gerçek de değil: taker + makas + sabit kayma
  varsayımı; emir defteri derinliği ve kısmi dolum modellenmez.
- Tasfiye fiyatı `giriş × (1/kaldıraç − bakım marjı)` yaklaşımıdır; borsaların
  gerçek tasfiye motoru, kademeli marj ve sigorta fonu modellenmedi.
- Funding yalnız oranı alınabilen sembollerde uygulanır; funding anına 3
  dakikadan az kaldıysa yeni giriş reddedilir.
- Kısa koşular (15 dk) kârlılık kanıtı değildir; işlem sayısı istatistiksel
  olarak anlamsızdır. Sonuçlar **KISMİ**dir.
- Gate.io ile Binance/OKX arasında fiyat farkı görülebilir; bot bunu arbitraj
  saymaz, her borsayı kendi fiyatıyla işler.

## Dosya düzeni
```
nova.py            giriş noktası
nova/bot.py        çekirdek (borsa, gösterge, strateji, defter, CLI)
nova/report.py     rapor üretimi
tests/test_nova.py     35 çevrimdışı test (v1 çekirdeği)
tests/test_yetenek.py  23 çevrimdışı test (v2 yetenekleri)
requirements.txt   aiohttp
runs/<koşu>/       SONUC.json, RAPOR.md, nova.sqlite, events.jsonl
```
