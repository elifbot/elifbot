# 23 Kasım 2026 mail alımı

Gmail'deki `Freqtrade, OctoBot ve Jesse — son çalışma dosyaları` ile bağlantılı üç Google Drive kaynak arşivi alındı. Büyük ham arşivler `data/raw/mail_20261123/` altında tutulur ve `.gitignore` nedeniyle Git'e eklenmez. Dosya kimlikleri, boyutlar, SHA-256 ve upstream revizyonları [`intake.json`](./intake.json) içindedir.

## Test kapsamı

`tools/mail_bot_matrix/` ve `.github/workflows/mail_bot_real_market.yml` aynı anda şu sınırlarla çalışır:

- Freqtrade 2026.10: OKX public USDT linear swap akışı üzerinde yalnız **dry-run**; boş API anahtarları, gerçek emir endpoint'i yok.
- OctoBot 2.1.1: OKX public veri + simüle trader başlatma denemesi; gerçek trader kapalı.
- Jesse 3.7.0: Jesse core araştırma/backtest motoru, OKX public kapanmış mumlarını yerel veri olarak kullanır. Jesse'nin lisanslı live/paper eklentisi ve resmi OKX live adaptörü bu kaynaklarda yok; bu nedenle bu bot için canlı paper iddiası yapılmaz.

Workflow public borsa erişimi olan GitHub runner'da manuel başlatılır. Arena sandbox'ında Binance/OKX hostlarına çıkış izni olmadığı için burada doğrudan canlı piyasa testi çalıştırılmaz. Üçüncü taraf test çıktısı canlı para veya kârlılık kanıtı değildir; işlem sonucu için yeterli örneklem ve yürütme modeli ayrıca gerekir.

Tamamlanan koşu: [Smoke run 45229625681](https://github.com/elifbot/elifbot/actions/runs/45229625681). Özet sonuçlar [`real_market_report.md`](./real_market_report.md), makine okunabilir rapor [`real_market_summary.json`](./real_market_summary.json) içindedir.
