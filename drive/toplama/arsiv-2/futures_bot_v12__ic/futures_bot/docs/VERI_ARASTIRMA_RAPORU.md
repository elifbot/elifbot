# Veri Kaynağı Araştırma Raporu — Binance FAPI & OKX V5

**Tarih:** 2026-10-27 · **Yöntem:** Bu ortamdan yapılan **gerçek HTTP istekleri**
(sonuçlar aşağıda birebir raporlanmıştır). Doğrulanmayan hiçbir uç nokta
"erişilebilir" sayılmamıştır.

---

## 1. Özet tablo

| Uç nokta | Durum | Not |
|---|---|---|
| `GET fapi.binance.com/fapi/v1/ping` | **451** | Bölgesel kısıtlama |
| `GET fapi.binance.com/fapi/v1/klines` | **451** | Bölgesel kısıtlama |
| `GET fapi.binance.com/fapi/v1/exchangeInfo` | **451** | Bölgesel kısıtlama |
| `GET www.okx.com/api/v5/public/time` | **200** | Çalışıyor |
| `GET www.okx.com/api/v5/market/candles` | **200** | Çalışıyor |
| `GET www.okx.com/api/v5/public/instruments` | **200** | Çalışıyor |

Binance yanıtı (birebir):

```json
{"code": 0, "msg": "Service unavailable from a restricted location according to
 'b. Eligibility' in https://www.binance.com/en/terms. Please contact our customer
 service for more information."}
```

**Sonuç:** Bu ortamdan Binance public verisi **kullanılamaz**. Bot, Binance
pair'lerinde her turda `FeedAccessError` üretir ve o pair'i atlar (çökmez).
Deneme oturumları **OKX** üzerinde yürütülmüştür.

## 2. OKX mum (candles) semantiği — doğrulandı

Gerçek yanıt örneği (`BTC-USDT-SWAP`, `bar=1m`):

```
["1793118360000","80523.9","80544.3","80523.9","80544.3","364","3.64","292848.6","0|1"]
```

| Alan | Anlam | Bu projedeki kullanım |
|---|---|---|
| `ts` | Açılış zamanı (ms) | `open_time`; kapanış = `ts + 60_000` |
| `o,h,l,c` | OHLC | doğrudan |
| `vol` | **Kontrat** adedi | `ctVal` ile çarpılır |
| `volCcy` | Base cinsinden hacim | çapraz kontrol (364 × 0.01 = 3.64) |
| `confirm` | `"1"` = mum kapandı | **`!= "1"` ise satır atılır** |

**ctVal doğrulaması:** `BTC-USDT-SWAP` için `ctVal = 0.01`, `ctValCcy = "BTC"`;
`ETH-USDT-SWAP` için `ctVal = 0.1`. Kontrat × ctVal = base hacim eşitliği
örnekte birebir sağlandı (364 kontrat → 3.64 BTC).

> Bu projede hacim **yalnızca** `contracts × ctVal` ile hesaplanır. `ctVal <= 0`
> olan enstrüman **atlanır** (hacim çevrimi yapılamaz).

## 3. Binance klines semantiği (doküman bilgisi — canlı doğrulanamadı)

`/fapi/v1/klines` alan sırası: `[openTime, open, high, low, close, volume,
closeTime, quoteVolume, trades, takerBuyBase, takerBuyQuote, ignore]`.
Kod bu şemaya göre yazıldı ancak **451 nedeniyle canlı yanıt alınamadı**;
ilgili parser yalnızca birim testlerde mock'lanmış yanıtla doğrulanmıştır.

**Durum: DOĞRULANMADI (canlı).** Test: `tests/test_feeds.py`.

## 4. Rate limit ve hata davranışı

| Kod | Davranış | Kod tarafı |
|---|---|---|
| 200 | normal | JSON parse; bozuksa `FeedError` |
| 429 | rate limit | beklemeli yeniden deneme (3 deneme) |
| 451 | bölgesel engel | `FeedAccessError`, pair atlanır |
| 403 / 418 | erişim reddi | `FeedAccessError` |
| Timeout | ağ | geri çekilmeli yeniden deneme |
| `code != "0"` (OKX) | uygulama hatası | `FeedError` |

Sınırlar: istek başına 300 mum; 60 sn yoklama (1m mum). OKX dokümanına göre
`candles` uç noktası 40 istek/2 sn ile sınırlıdır — bu proje dakikada ~2 istek
yapar, limitin çok altındadır. **Bu limit canlı yük testiyle doğrulanmadı.**

## 5. Sembol çakışması riski (spec'teki BB/USDT örneği)

- Binance `BBUSDT` → **BounceBit** (spot/futures tokeni)
- OKX `BB-USDT-SWAP` → **BlackBerry** hissesi (pre-IPO/hisse kontratı olabilir)

Aynı sembol adı iki farklı varlığı gösterebilir. Bu projede:

1. Pozisyonlar `(exchange, symbol)` ile anahtarlanır; **asla birleştirilmez**.
2. Aynı sembol farklı borsalarda listelenmişse ve fiyat farkı **> %1.5** ise
   bu bir çakışma sinyalidir — ikincil borsa devre dışı bırakılmalıdır.

> **DOĞRULANMADI:** Bu ortamda Binance erişilemediği için canlı fiyat
> karşılaştırması yapılamadı. Kural kodda uygulanabilir durumdadır ancak
> gerçek çakışma örnekleriyle test edilmemiştir.

## 6. Vadeli mikroyapı verileri (Phase C)

| Veri | Durum | Sonuç |
|---|---|---|
| Funding rate | **DOĞRULANMADI** | `DataUnavailableError`; PnL funding **hariç** |
| Open interest | **DOĞRULANMADI** | Sinyalde kullanılmıyor |
| Mark / index price | **DOĞRULANMADI** | Basis hesabı yok |
| Order book / spread | **ERİŞİLMEDİ** | Aile envanterinde MISSING |
| CVD / taker delta | **ERİŞİLMEDİ** | Aile envanterinde MISSING |
| Liquidation flow | **ERİŞİLMEDİ** | Aile envanterinde MISSING |

Funding'in "sıfır" olduğu **hiçbir yerde iddia edilmez**; tüm çıktılar
`funding hariç / bilinmiyor` etiketlidir ve CSV'de `bilinmiyor` yazılır.

## 7. Referans projeler (kod kopyalanmadı)

Freqtrade (dry-run mimarisi) ve Hummingbot (connector tasarımı) yalnızca
**mühendislik referansı** olarak incelendi; lisanslı kod kopyalanmadı.
Bu projenin paper modeli ile aralarındaki temel fark: burada tek paper
hesap, pozisyon bazında İZOLE marj varsayımı ve funding verisi yoksa
`bilinmiyor` etiketi kullanılır. Çapraz marj veya çapraz zarar kurtarma yoktur.

## 8. Gerçek veri anlık görüntüsü (kanıt)

`data/fixtures/okx_BTC-USDT-SWAP_1m_real_snapshot.csv` ve
`okx_ETH-USDT-SWAP_1m_real_snapshot.csv` dosyaları **gerçek OKX verisidir**:

- 299 kapalı 1m mum
- 2026-10-27 11:30 → 16:28 UTC
- BTC 80.556,7 · ETH 2.347,5 (snapshot anındaki son kapanışlar)

Bu dosyalar test ve backtest için kullanılabilir; **sentetik değildir**.
`synthetic_btc_1m.csv` ise adından da anlaşılacağı üzere tamamen **uydurma**
veridir ve yalnızca kod yolu doğrulaması içindir.
