# ACARBOT × OmniStudio — PAPER koşu raporu

**Durum:** `COMPLETED` · **Mod:** `ws` · **Strateji:** `trend` · **Konsey:** `RULE_BASED_QUANT`  
**Ölçülen süre:** 904.5 sn (hedef 900.0 sn)  
**Gerçek emir:** 0 · **Gerçek para onayı:** `False`

> Bu rapor PAPER (sanal defter) araştırmasıdır. Kârlılık, gerçek dolum veya gerçek paraya uygunluk **kanıtı değildir**.

## 1. Sözleşme kapsamı (gerçek exchangeInfo)

| Pazar | Toplam | PAPER uygun | Reddedilen | Ana ret nedeni |
|---|--:|--:|--:|---|
| binance_usdm | 440 | 20 | 420 | TRADIFI |
| binance_coinm | 30 | 0 | 30 | vadeli/teslimat |
| okx_swap | 50 | 20 | 30 | kripto dışı dayanak |
| okx_futures | 287 | 0 | 287 | X-PERP |
| gateio_usdt | 20 | 20 | 0 | — |
| gateio_btc | 1 | 0 | 1 | inverse |
| **toplam** | **828** | **60** | **768** | kapsam **%7.25** |

Reddedilenler rastgele değil: X-PERP, vadeli/teslimat, USDC/USD marj, inverse, tokenize hisse/emtia (TRADIFI) ve durumu TRADING/live olmayanlar. Her birinin gerekçesi `OLCUM.json` ve `SONUC.json → coverage` içinde tek tek yazılı.

## 2. Ölçülen piyasa bağlamı

- **Piyasa genişliği:** %10.3 yukarı (4↑ / 35↓, örnek 39) — ölçüldü
- **Akış (CVD) ölçülen sembol:** 40 (gerçek agresif alış/satış işlemleri)
- **Funding ölçülen sembol:** 40
- **Isınma:** 40 sembol mum, 40 tanesi ≥250 kapanmış mum

**Hacme göre ilk sözleşmeler (24s quote hacmi):**

| Pazar | Sembol | Hacim | ATR% | Makas bps | Akış baskısı | Funding |
|---|---|--:|--:|--:|--:|--:|
| binance_usdm | BTCUSDT | 42729336 | 0.250 | 0.01 | 0.257 | 0.00010 |
| binance_usdm | ETHUSDT | 23660428 | 0.316 | 0.04 | 0.187 | 0.00008 |
| okx_swap | ETH-USDT-SWAP | 22088808 | 0.320 | 0.04 | -0.827 | -0.00008 |
| okx_swap | BTC-USDT-SWAP | 17229774 | 0.250 | 0.01 | -0.651 | 0.00009 |
| binance_usdm | ZECUSDT | 7435165 | 0.834 | 0.08 | 0.499 | 0.00010 |
| okx_swap | ZEC-USDT-SWAP | 3600977 | 0.821 | 0.08 | -0.306 | 0.00010 |
| binance_usdm | XRPUSDT | 2030558 | 0.328 | 0.80 | -0.199 | 0.00010 |
| okx_swap | SOL-USDT-SWAP | 1208054 | 0.366 | 1.11 | 0.499 | -0.00006 |
| okx_swap | ANTHROPIC-USDT-SWAP | 1010801 | 0.688 | 6.03 | -0.499 | 0.00000 |
| okx_swap | DOGE-USDT-SWAP | 563358 | 0.319 | 1.38 | 0.793 | -0.00003 |

## 3. PAPER defteri

- Başlangıç: **10000** → şimdi: **10000.000000** (gerçekleşen: 0.000000)
- Kapanan işlem: **0** · açık: 0 · kazanma: %0.0 · ort. R: 0.0
- Ücretler: 0.000000 · **funding: 0.000000** (0 olay) · maks. düşüş: 0.000000
- Devre kesici: `False` 

## 4. Konsey: ölçüm var / yok karşılaştırması

- Değerlendirilen aday: 4
- **Ölçülmüş bağlamla onaylanan:** 0
- **Maildeki varsayımla (akış=0, genişlik=0, 15dk=uyumsuz) onaylanan:** 0
- **Kararı değişen aday:** 0

> Adaylar `signal_at_close` ile üretildi: strateji kararı mumun kapanış anındaki veriyle verilmiş gibi hesaplandı (geçmiş karar), akış/funding/makas bağlamı ise ölçüm anındaki gerçek değerlerdir. Konsey anahtarsız RULE_BASED_QUANT modunda çalıştı; bu bir YZ onayı değildir. Karşılaştırma yalnız, maildeki botun ÖLÇMEDİĞİ üç boyutun kararı değiştirip değiştirmediğini gösterir.

## 5. Sayaçlar

| Sayaç | Değer |
|---|--:|
| bars_evaluated | 102 |
| signals | 5 |
| council_calls | 5 |
| warmup_ready | 40 |
| flow_ok | 1800 |
| funding_ok | 1200 |
| quote_refresh_ok | 528 |

**Ret sayaçları:**

| Neden | Adet |
|---|--:|
| warmup | 18 |
| COUNCIL | 5 |

## 6. WebSocket akışı

| Pazar | Bağlantı | Güncelleme | Kapanmış mum | Medyan gecikme | En uzun |
|---|--:|--:|--:|--:|--:|
| binance_usdm | 1 | 18144 | 60 | 986 ms | 3042 ms |
| gateio_usdt | 1 | 0 | 0 | 0 ms | 0 ms |
| okx_swap | 1 | 9548 | 60 | 799 ms | 1373 ms |

## 7. Pazar sağlığı

| Pazar | Erişim | REST ok | REST hata | Son hata |
|---|---|--:|--:|---|
| binance_usdm | ✅ | 818 | 0 |  |
| binance_coinm | ✅ | 1 | 0 |  |
| okx_swap | ✅ | 812 | 0 |  |
| okx_futures | ✅ | 1 | 0 |  |
| gateio_usdt | ✅ | 204 | 0 |  |
| gateio_btc | ✅ | 1 | 0 |  |

## 8. Dürüstlük sınırları

- Gerçek emir yolu yoktur; `real_orders = 0`.
- PAPER dolumu taker fiyatı + varsayımsal kayma ile modellenir; emir defteri derinliği ve kuyruk önceliği bilinmez.
- Likidasyon fiyatı `1/kaldıraç − bakım marjı` yaklaşımıdır; borsanın gerçek tasfiye motoru ve kısmi tasfiye kuralları modellenmedi.
- Funding, koşu sırasında borsanın bildirdiği oranla işlenir; gelecekteki oranlar değişebilir. Oran alınamayan sembollerde funding 0 varsayılmaz, giriş reddedilir (`FUNDING_UNKNOWN`).
- COIN-M hacmi USD'ye yaklaşık çevrilir (etiketli tahmin); ters sözleşme PAPER hesabı bu sürümde bağlı değildir.
- Kısa örneklem ve tek koşu kârlılık kanıtı değildir.
- Konsey anahtarsız modda RULE_BASED_QUANT'tır; YZ çağrısı yapılmadı (`ai_generated=false`).
