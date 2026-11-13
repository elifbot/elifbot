# ACARBOT FINAL v1.0 — Değişiklik Günlüğü (7 Kasım 2026)

## Taban seçimi
"son sürümler" klasöründeki 6 sürüm karşılaştırıldı:

| Sürüm | Durum |
|---|---|
| trading_system_v2_final / ultra / ultra_plus | Eski nesil (26-31 py dosyası); ultra_plus'taki iyi fikirler (haber koruması hariç) zaten süper sürüme taşınmış |
| ACAR_FUTURES_APEX v1.0 / v1.1 | Ara sürüm; v1.1 pozisyon limitini ve günlük freni kaldırmıştı (risk geri adımı) |
| **acarbot_super (bot_super)** | **TABAN SEÇİLDİ** — en güncel (06.11 20:50), 3 bağımsız inceleme + kod inceleme raporunun 20 bulgusunu birleştiren mimari, 145 test, Docker/CI, izleme |

FINAL = bot_super + aşağıdaki düzeltme ve eklemeler. Strateji/risk parametreleri
değiştirilmedi (1.000 USDT bakiye, 10x, 500 nominal, 25 USDT net risk tavanı,
maks 6 pozisyon, günlük -100 soft / -150 hard).

## Hata düzeltmeleri
1. **`websockets` bağımlılığı eksikti** — `infra/exchanges/okx.py` ve `binance.py`
   `websockets` kullanıyor ama `requirements.txt` yalnızca `aiohttp` listeliyordu.
   Temiz kurulumda OKX/Binance akışı `ModuleNotFoundError` ile çöküyordu. Eklendi.
2. **Paper modunda `--max-positions` yok sayılıyordu** — CLI argümanı yalnızca
   backtest'te uygulanıyordu; README'deki "katı mod" (`--max-positions 1`)
   canlı paper'da sessizce etkisizdi. Artık `config.portfolio.max_positions`
   gerçekten güncelleniyor.
3. **Paper modunda `--warmup-seconds` yok sayılıyordu** — aynı şekilde
   `config.data.warmup_seconds`'e artık uygulanıyor.

## Yeni özellikler
1. **`--duration-minutes N`** — süreli oturum: N dakika sonunda bot kendiliğinden
   kapanır, durumu kaydeder ve rapor yazar (15 dakikalık test için: `15`).
   `0` (varsayılan) = süresiz, Ctrl+C ile kapanır.
2. **`--report-file dosya.json`** — oturum sonunda JSON rapor: süre, başlangıç/
   bitiş bakiyesi, equity, gerçekleşen/açık PnL, giriş/kapanış sayıları, açık
   pozisyonlar, kill switch ve güvenli mod durumu, tick sayaçları.
   Kapanışta ayrıca günlük rapor formatında log özeti yazılır.
3. **Sürüm bilgisi** — `app.__version__ = "1.0-final"`, başlangıç afişinde görünür.
4. **`run_test_15min.sh`** — tek komutla 15 dk OKX paper testi.
5. **`run_paper_windows.bat`** — kendi venv'ini kuran Windows başlatıcı
   (APEX v1.1'deki başlatıcının FINAL'e uyarlanmış hâli).

## Test durumu
- Süper sürüm tabanı: 145/145 test geçti (Python 3.13).
- FINAL eklemeleri: 7 yeni test (`tests/test_final_cli.py`).

## Operasyonel notlar
- Bu derleme ortamında **Binance public API HTTP 451 (bölgesel engel)** döndürüyor;
  **OKX sorunsuz** (REST + WS doğrulandı). Varsayılan test senaryosu OKX kullanır.
  Binance'in açık olduğu ağlarda `--exchange binance` veya `--exchange all` kullanılabilir.
- OKX için sembol biçimi: `BTC-USDT-SWAP` (Binance biçimi `BTCUSDT` de REST
  tarafında normalize edilir; WS eşleşmesi için tam instId önerilir).
- Paket PAPER ONLY'dir: gerçek emir ucu yoktur, kârlılık kanıtı değildir.
