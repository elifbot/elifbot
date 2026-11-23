# Üç bot: kurulum tanısı ve Freqtrade kısa paper denemesi

Bu çalışma eski TradingAgents paper testinden ayrıdır. Hiçbir iş gerçek borsa emri göndermez veya özel OKX kimlik bilgisi kullanmaz.

## GitHub uyumluluk işi

`ollama_sonda.yml` dispatcher `model=bot-uyumluluk`: bağımsız işlerde PyPI üzerinden Freqtrade `2026.10`, OctoBot `2.1.1`, Jesse `3.7.0` kurulur ve kendi modülleri içe aktarılır. OKX public SWAP ve FUTURES enstrüman listeleri çağrılır; sonuçlar ve gerçek bağımlılık sürümleri ayrı artifact'lere yazılır. Freqtrade işi ayrıca CCXT üzerinden lineer perpetual piyasaları sayar. Bu **kurulum/erişim tanısıdır**, işlem testi veya üç motorun karşılaştırmalı performansı değildir. Üst sürümler sabittir ancak alt bağımlılıklar çözümleme sırasında değişebilir; her koşunun `dependencies.txt` dosyası gerçekte yüklenen sürümleri kaydeder.

- Freqtrade `2026.10` kaynak kodunda futures filtresi lineer `swap` tipidir; vadeli kontrat ve inverse swap'ları kapsamaz. Bir hesap yapılandırması tek teminat para birimi kullanır; bir paritede aynı anda bir pozisyon vardır. OKX için isolated teminat kullanılır. Tüm OKX evreni veya aynı sembolde sınırsız pozisyon iddiası **yoktur**.
- OctoBot kurulum başarısı, OKX futures simulator ve strateji yapılandırmasının çalıştığını kanıtlamaz; ayrıca denenmelidir.
- Jesse resmi belgeleri paper/canlı işlem için lisanslı eklenti gerektirir ve desteklenen borsalar listesinde OKX bulunmaz. Resmi lisans/entegrasyon olmadan Jesse'nin canlı OKX paper testi hazırmış gibi gösterilemez. Tarihsel veriyle açık kaynak backtest, canlı paper testi değildir.

## Freqtrade kısa deneme

`model=freq-paper-3m`: Freqtrade'in kurulu paketinden upstream `SampleStrategy` alınır; içindeki mevcut short kurallarını etkinleştirmek için yalnız `can_short` açılır. 5 dakika mumları, RSI/TEMA/Bollinger ve hacim örnek kurallarıdır; performans garantisi değildir. 1.000.000 USDT sanal kasa, 50 USDT hedef tutar, dry-run true, boş API anahtarları, USDT teminatlı lineer perpetual eşleşmeleri, `max_open_trades=-1` ve isolated mod kullanılır. Tek sembolde bir açık pozisyon motor sınırıdır. 180 saniyelik süreç süresi başlangıç kurulumunu da içerir; 180 saniyelik strateji işleyişi garanti edilmez. Süre sonunda SIGINT ile durdurulur, açık pozisyonlar kapatılmış varsayılmaz. `RUNNING` heartbeat yoksa test başarısızdır. Rapor ve işlem veritabanı Actions artifact'ine kaydedilir; başlangıç hataları check anotasyonuna eklenir.

## Arena paneli

```bash
BOT_PROBE_RUN_ID=<tanı-koşu-id> FREQ_RUN_ID=<freqtrade-koşu-id> python3 -m panel.bot_karsilastirma_server
```

Panel yalnızca GitHub koşu ve iş durumlarını ve mevcutsa Freqtrade özet anotasyonunu okur. Canlı pozisyon veya kâr/zarar telemetrisi yoktur. Artifaktlar yedi gün saklanır; her testin tam sonucu artifact erişimine bağlıdır. Hiçbir API veya parola girilmez.
