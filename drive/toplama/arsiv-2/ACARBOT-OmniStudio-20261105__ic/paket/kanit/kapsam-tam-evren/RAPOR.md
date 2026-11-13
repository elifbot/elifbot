# ACARBOT × OmniStudio — PAPER koşu raporu

**Durum:** `COMPLETED` · **Mod:** `observe` · **Strateji:** `trend` · **Konsey:** `RULE_BASED_QUANT`  
**Ölçülen süre:** 7.0 sn (hedef 2.0 sn)  
**Gerçek emir:** 0 · **Gerçek para onayı:** `False`

> Bu rapor PAPER (sanal defter) araştırmasıdır. Kârlılık, gerçek dolum veya gerçek paraya uygunluk **kanıtı değildir**.

## 1. Sözleşme kapsamı (gerçek exchangeInfo)

| Pazar | Toplam | PAPER uygun | Reddedilen | Ana ret nedeni |
|---|--:|--:|--:|---|
| binance_usdm | 942 | 522 | 420 | TRADIFI |
| binance_coinm | 30 | 0 | 30 | vadeli/teslimat |
| okx_swap | 540 | 510 | 30 | kripto dışı dayanak |
| okx_futures | 287 | 0 | 287 | X-PERP |
| gateio_usdt | 1080 | 1080 | 0 | — |
| gateio_btc | 1 | 0 | 1 | inverse |
| **toplam** | **2880** | **2112** | **768** | kapsam **%73.33** |

Reddedilenler rastgele değil: X-PERP, vadeli/teslimat, USDC/USD marj, inverse, tokenize hisse/emtia (TRADIFI) ve durumu TRADING/live olmayanlar. Her birinin gerekçesi `OLCUM.json` ve `SONUC.json → coverage` içinde tek tek yazılı.

## 2. Ölçülen piyasa bağlamı

- **Piyasa genişliği:** %17.1 yukarı (33↑ / 160↓, örnek 193) — ölçüldü
- **Akış (CVD) ölçülen sembol:** 60 (gerçek agresif alış/satış işlemleri)
- **Funding ölçülen sembol:** 40
- **Isınma:** 200 sembol mum, 200 tanesi ≥250 kapanmış mum

**Hacme göre ilk sözleşmeler (24s quote hacmi):**

| Pazar | Sembol | Hacim | ATR% | Makas bps | Akış baskısı | Funding |
|---|---|--:|--:|--:|--:|--:|
| binance_usdm | BTCUSDT | 19469815 | 0.250 | 0.01 | -0.068 | 0.00010 |
| binance_usdm | ETHUSDT | 18730286 | 0.306 | 0.04 | 0.337 | 0.00009 |
| okx_swap | BTC-USDT-SWAP | 11856504 | 0.251 | 0.01 | -0.197 | 0.00008 |
| binance_usdm | ZECUSDT | 8653473 | 0.829 | 0.08 | -0.497 | 0.00010 |
| okx_swap | ETH-USDT-SWAP | 6211812 | 0.311 | 0.04 | 0.494 | -0.00008 |
| okx_swap | ZEC-USDT-SWAP | 4641853 | 0.807 | 0.08 | -0.100 | 0.00010 |
| binance_usdm | SOLUSDT | 3629610 | 0.355 | 1.11 | 0.303 | -0.00007 |
| binance_usdm | XRPUSDT | 1699686 | 0.321 | 0.81 | 0.237 | 0.00010 |
| binance_usdm | NEARUSDT | 1067043 | 0.606 | 2.68 | 0.236 | 0.00010 |
| okx_swap | SOL-USDT-SWAP | 752939 | 0.356 | 1.11 | 0.840 | -0.00007 |

## 3. PAPER defteri

- Başlangıç: **10000** → şimdi: **10000.000000** (gerçekleşen: 0.000000)
- Kapanan işlem: **0** · açık: 0 · kazanma: %0.0 · ort. R: 0.0
- Ücretler: 0.000000 · **funding: 0.000000** (0 olay) · maks. düşüş: 0.000000
- Devre kesici: `False` 

## 4. Konsey: ölçüm var / yok karşılaştırması

Konsey karşılaştırması çalışmadı: `TypeError: float() argument must be a string or a real number, not 'NoneType'`

## 5. Sayaçlar

| Sayaç | Değer |
|---|--:|
| bars_evaluated | 0 |
| warmup_ready | 200 |

## 7. Pazar sağlığı

| Pazar | Erişim | REST ok | REST hata | Son hata |
|---|---|--:|--:|---|
| binance_usdm | ✅ | 165 | 0 |  |
| binance_coinm | ✅ | 1 | 0 |  |
| okx_swap | ✅ | 62 | 83 | HTTP 429 |
| okx_futures | ✅ | 1 | 0 |  |
| gateio_usdt | ✅ | 135 | 0 |  |
| gateio_btc | ✅ | 1 | 0 |  |

## 8. Dürüstlük sınırları

- Gerçek emir yolu yoktur; `real_orders = 0`.
- PAPER dolumu taker fiyatı + varsayımsal kayma ile modellenir; emir defteri derinliği ve kuyruk önceliği bilinmez.
- Likidasyon fiyatı `1/kaldıraç − bakım marjı` yaklaşımıdır; borsanın gerçek tasfiye motoru ve kısmi tasfiye kuralları modellenmedi.
- Funding, koşu sırasında borsanın bildirdiği oranla işlenir; gelecekteki oranlar değişebilir. Oran alınamayan sembollerde funding 0 varsayılmaz, giriş reddedilir (`FUNDING_UNKNOWN`).
- COIN-M hacmi USD'ye yaklaşık çevrilir (etiketli tahmin); ters sözleşme PAPER hesabı bu sürümde bağlı değildir.
- Kısa örneklem ve tek koşu kârlılık kanıtı değildir.
- Konsey anahtarsız modda RULE_BASED_QUANT'tır; YZ çağrısı yapılmadı (`ai_generated=false`).
