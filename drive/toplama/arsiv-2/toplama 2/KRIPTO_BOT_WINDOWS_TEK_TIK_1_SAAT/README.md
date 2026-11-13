# 🛡️ KRIPTO-BOT v7.2 — Canlı Veri + Gerçekçi Paper + Çoklu Borsa Kripto Botu

Binance ve OKX vadeli/spot piyasalarında çalışan; **50 USDT sabit marj + 10x**, **40 USDT (%80 marj) başlangıç stopu**, **sabit TP olmadan trailing + order-flow kâr çıkışı**, **Multi-Timeframe (1h / 4h) Trend Filtresi**, **20 Kademe Emir Defteri**, **CVD divergence / absorption**, **gerçek tick VPVR**, **Eşleştirilmiş Shadow Lab + PDF v2 Araştırma Paketi**, **Multi-Exchange Failover**, **SQLite WAL**, **Prometheus `/metrics` ve `/health`**, **%0.30 Maksimum Kayma & Chase Order** ve **Çapraz İkili Kurtarma** özelliklerine sahip alım-satım sistemi.

---

## 🟢 Canlı Benzeri Paper (Gerçek Veri, Sanal Emir)

`MODE=paper` ile hayali başlangıç kasası kullanılır; gerçek para/emir kullanılmadan canlı piyasa koşulları taklit edilir:

- **Doğru enstrümanlar:** Paper modunda Binance/OKX kataloglarındaki **tüm aktif, USDT marjlı perpetual** kontratlar keşfedilir; spot ve tarihli vadeliler dışlanır. Her sembolün verisi/emir simülasyonu yalnız onu listeleyen borsalara yönlendirilir. 10x üst sınırı olmayan kontratlar da analizde kalır ancak sabit kaldıraç kuralı gereği işlem açmaz. Geniş keşif yalnız paper içindir; live/testnet yapılandırılmış sembolleri ve sıkı limitleri korur.
- **Gerçek para akışı:** Binance `aggTrade`, `bookTicker`, 20 kademe derinlik ve tasfiye akışı; OKX `trades`, `tickers` ve `books` akışı. OKX kontrat adetleri borsadan okunan `contractSize` ile coin miktarına çevrilir.
- **Teknik analiz:** MA/EMA, RSI/MACD, ADX, Supertrend, UTC günlük/haftalık session VWAP, swing-anchored VWAP, Bollinger/Keltner sıkışması, mum-tabanlı yaklaşık Volume Profile ve ayrı `TICK_VPVR` (POC/VAH/VAL).
- **Sabit 50/40 risk planı:** Her pozisyon toplam 50 USDT marj × 10x = 500 USDT büyüklüğündedir. Başlangıç stopu 40 USDT fiyat K/Z'yi hedefler; 10x'te %8 fiyat mesafesidir. Kademe ekleme kapalıdır, bakiye 50 USDT altındaysa giriş yapılmaz.
- **Kâr koşusu:** Girişte sabit bir TP fiyatı belirlenmez. Pozisyon kârda kaldığı sürece açık kalır; trailing/Supertrend stopu zirveyi/dibi izler. Trailing/Supertrend adayı başabaş veya kâr bölgesine ulaşmadan başlangıç koruyucu stopu daraltılmaz; kapanış nedeni başlangıç stopu ile trailing/kâr stopunu ayırır. Long'da satış baskısı + negatif CVD + zirveden geri çekilme, Short'ta alış baskısı + pozitif CVD + dipten yükseliş de çıkış üretir.
- **Order-flow onayı:** Fiyat yeni tepe/dip yaparken CVD'nin doğrulamaması divergence; baskın agresif hacme rağmen fiyatın tutunması ve karşı defter derinliğinin korunması absorption üretir. Bunlar skoru şişirmek yerine karşı yönlü girişi veto eder ve kârdaki pozisyona simetrik çıkış onayı sağlar.
- **Gerçekçi paper muhasebesi:** Market alışta ask, satışta bid; taker/maker komisyonu, kayma kaydı ve geçen süreye göre funding. Bakiye, komisyon ve funding SQLite'ta korunur.
- **Eşleştirilmiş Shadow Lab & PDF v2:** Ana strateji ve eşikleri değiştirmeden izole shadow varyantları (**net-exit**, **flow-confidence**, **volatility-gate**, **range-confirmation**, **technical-harmony**, **portfolio-guard** ve opsiyonel **pdf-confluence**) çalıştırır ve oturum sonunda kanıt raporlarını üretir.

---

## 🏗️ Temel Bileşenler

- **Multi-Exchange Failover (`src/exchanges.py`):** Birincil borsa üst üste 3 timeout verirse işlemleri kesintisiz olarak yedek borsaya (**OKX**) kaydırır; `BINANCE_PUBLIC_WWW=1` ile bulut ortamlarında resmî Binance USDⓈ-M public uçlarına erişimi korur.
- **SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı (`src/state_store.py`):** `PRAGMA journal_mode=WAL` + her 24 saatte bir eski kayıtları `.jsonl.gz` olarak arşivleyip `VACUUM` ile veritabanı şişmesini önler.
- **Gerçek Zamanlı `/health`, `/healthz` ve Prometheus `/metrics` (`src/health.py`):** Dış izleme araçlarının her saniye botun sağlık ve metriklerini kontrol etmesini sağlar.
- **Sabit 50 USDT marj + 10x + 40 USDT stop + kâr koşusu + %0.30 Kayma & Chase Order** (kademe ekleme kapalı; eski risk modelleri alternatif olarak korunur).
- **İki Yönlü Telegram Botu (`src/telegram.py`):** `/guncel`, `/pnl`, `/durum`, `/piyasa`, `/rapor`, `/gunluk`, `/kill`, `/durdur`, `/baslat`, `/sigorta`.

---

## 🚀 Hızlı Başlangıç ve Doğrulama Komutları

```bash
# 1) Regresyon ve çevrimdışı paper doğrulamalarını çalıştırın
python3 -m ruff check .
python3 -m pytest -q -W error     # 111+ regresyon ve Shadow Lab testi
python3 test_hizli.py             # 101 ana paket senaryosu
python3 test_bot_v7.py            # 27 bağımsız paper senaryosu

# 2) Canlı veri ile paper modunda ana botu başlatın
MODE=paper python3 -m src.main

# 3) Gerçek Zamanlı Web Panelini + /health & /metrics sunucusunu başlatın (Port 8501)
python3 -m src.dashboard
```
