# FUSION PRO 3.0 — Binance + OKX Cross-Margin Trading Engine

Bu sürüm sade bir kullanım modeline göre yeniden düzenlendi:

- Başlangıç kasa: **1.000 USDT**
- Her sinyalde hedef işlem marjini: **50 USDT**
- Kaldıraç: **10x**
- Hedef nominal: **500 USDT**
- Stop-loss: **işlem başına 20 USDT fiyat hareketi kaynaklı risk**
- Giriş: **maker / post-only**
- TP: sabit bir yüzde değil; **sinyal + rejim + ATR + maliyet sonrası edge** tarafından belirlenir ve açık pozisyonda sinyal geldikçe güncellenebilir.
- Margin: **cross**
- Pozisyon sayısı: kod içinde yapay `20 işlem` veya `3 pozisyon` limiti yoktur. Her yeni sinyal yeni bir $50 marjin dilimi açabilir; gerçek borsanın kullanılabilir teminatı, risk kill-switch'i ve enstrüman limitleri doğal sınırdır.

## Önemli: "sınırsız" ne demek?

Borsada fiziksel olarak sınırsız pozisyon açılamaz. Cross margin'de yeni bir pozisyon için kullanılabilir teminat gerekir. Bu nedenle bot **yapay pozisyon sayısı limiti koymaz**, fakat kullanılabilir bakiye/teminat bittiğinde borsa veya risk katmanı yeni emri reddeder. Bu, 1.000 USDT kasayı 20 işlemde mekanik olarak durdurmaktan farklıdır.

## Maker konusunda önemli ayrım

Giriş emirleri `post_only` olarak tasarlanmıştır. Binance'te post-only için `GTX`, OKX'te `post_only` kullanılır. Emir hemen taker olacaksa reddedilip yeniden fiyatlanabilir. Binance dokümanlarında GTX post-only olarak tanımlanır; GTX emir maker olarak gerçekleşemediğinde reddedilebilir. 

TP ve SL'nin tetiklendiği anda **maker kalacağı garanti edilemez**. Koruyucu stop'un amacı komisyon minimizasyonu değil, hesabı korumaktır. Bu nedenle koruyucu çıkışlar koşullu emirlerle tasarlanır.

OKX tarafında cross margin `tdMode=cross` ile, post-only giriş `ordType=post_only` ile desteklenir. 

## Borsalar

### Binance Futures
- Public market data: API key gerekmez.
- Live trading için API key/secret environment değişkenlerinden okunur.
- Cross margin ve 10x leverage hedeflenir.
- One-way pozisyon modu varsayılandır.
- Maker giriş `LIMIT + GTX`.

### OKX SWAP
- Public market data: API key gerekmez.
- Live trading için API key/secret/passphrase environment değişkenlerinden okunur.
- `tdMode=cross`.
- 10x leverage.
- Maker giriş `post_only`.

OKX API, cross/isolated trade mode ve post-only emir tipini açıkça destekler. 

## Çalıştırma

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# Linux
source .venv/bin/activate

pip install -r requirements.txt

# Binance paper
python -m src.main --exchange binance --mode live-paper --symbols BTCUSDT ETHUSDT SOLUSDT

# OKX paper
python -m src.main --exchange okx --mode live-paper --symbols BTCUSDT ETHUSDT SOLUSDT

# Tek tarama
python -m src.main --exchange binance --mode live-paper --symbols BTCUSDT --once
```

OKX sembolleri otomatik olarak `BTC-USDT-SWAP` biçimine çevrilir.

## Live trading güvenliği

Gerçek emir modu **varsayılan olarak kapalıdır**:

```yaml
trading:
  live_enabled: false
```

Önce demo/test ortamında doğrulama yapılmalı. Gerçek moda geçmek için API anahtarlarını `.env`/işletim sistemi environment'ından sağlamak ve `live_enabled: true` yapmak gerekir. Anahtarlar config dosyasına yazılmaz.

`.env.example` sadece isimleri gösterir.

## Strateji

Bot sadece indikatör çoğunluğu ile işlem açmaz. Akış:

`data health → MTF → regime → trend/range → volume → taker flow → OI → funding → depth → spread → cost-after-edge → signal score → risk → execution`

### TP

TP, `target_r` ile başlayan dinamik bir hedef olarak hesaplanır. Açık pozisyonda yeni sinyal aynı yönde güçlenirse hedef yeniden hesaplanabilir. Ayrıca break-even ve ATR trailing devreye girer.

### SL

Her giriş diliminde hedeflenen nominal yaklaşık 500 USDT'dir. 20 USDT stop riski için miktar ve stop mesafesi birlikte hesaplanır. Bu nedenle stop mesafesi coin fiyatına göre değişir; amaç **işlem başına yaklaşık 20 USDT fiyat kaynaklı zarar** sınırı koymaktır.

Komisyon ve olası slipaj bunun üstüne gelebilir; gerçek net -20 USDT garantisi vermez.

## Test

```bash
pytest -q
python -m compileall -q src
```

## Durum

Bu paket gerçek borsa emirlerini varsayılan olarak göndermez. Live execution adaptörleri Binance ve OKX için ayrı tutulmuştur. Bu ortamda borsa DNS/erişim problemi nedeniyle canlı Binance fiyat akışı doğrulanamadı; dolayısıyla testler gerçek piyasa emri başarı iddiası değildir.


## FUSION PRO 4.0 changes
- Full Binance + OKX linear futures universe discovery; no fixed 100-coin list.
- Full-universe lightweight tracking + event-driven deep scanning.
- Multi-level orderbook pressure, liquidation proxy, signal quality ranking and signal freshness.
- Dynamic TP, partial TP and trailing runner.
- $50 margin × 10x = $500 nominal; cross margin; no artificial position-count cap.
- $20 all-in risk budget with fee/slippage reserve for linear USDT/USDC contracts.
- See `UNIVERSE_ARCHITECTURE.md` and `RISK_MATH.md`.
