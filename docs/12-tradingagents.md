# TradingAgents kurulumu (ayrı araştırma aracı)

[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), LLM kullanan çok ajanlı bir piyasa araştırma çerçevesidir. Bu depoda **ACARBOT'a bağlanmadan** ayrı bir Python ortamına kurulur; ACARBOT'un risk kurallarını değiştirmez ve onun adına emir vermez. Kurulum, performans veya kâr garantisi değildir.

## Kurulum

Python 3.11 veya üzeri ve Git gereklidir. Depo kökünde:

```bash
python3 -m venv .venv/tradingagents
.venv/tradingagents/bin/python -m pip install -r requirements-tradingagents.txt
.venv/tradingagents/bin/python -m pip check
.venv/tradingagents/bin/tradingagents --help
```

Kaynak `requirements-tradingagents.txt` içinde TradingAgents v0.7.1 commit'ine sabitlenmiştir; alt bağımlılıklar sabitlenmemiştir. Sanal ortam Git'e girmez; başka bir makinede veya ortam sıfırlandığında yukarıdaki adımlarla yeniden kurun.

## Çalıştırma

Bir terminalde `.venv/tradingagents/bin/tradingagents` komutunu çalıştırın ve piyasa sembolü, tarih ve model sağlayıcısını seçin. Örneğin Yahoo Finance kapsamındaki kripto sembolleri `BTC-USD` ve `ETH-USD` biçimindedir; bunlar OKX/Binance vadeli işlem sözleşmeleriyle aynı şey değildir.

Gerçek analiz için seçilen model sağlayıcısına erişim ve genellikle API anahtarı gerekir; veri kaynakları için de ağ erişimi ve bazı kaynaklarda ek anahtar gerekebilir. Anahtarları sohbete veya Git'e yazmayın; kendi ortamınızda güvenli şekilde ayarlayın. LLM ve veri sağlayıcıları ücret uygulayabilir.

**Bu geliştirme ortamında** dış ağ erişimi GitHub ve paket depolarıyla sınırlıdır; bu nedenle model ve piyasa verisi servisleriyle uçtan uca analiz burada doğrulanamaz. Kurulum kontrolü yalnızca paket yükleme, bağımlılık kontrolü ve CLI yardım ekranını kapsar.

TradingAgents araştırma amaçlıdır; çıktıları yatırım tavsiyesi değildir. ACARBOT'a entegrasyon, canlı emir veya bu deponun 1.000 $ / 50 $ / 10x / CROSS / −10 $ risk kurallarının uygulanması bu kurulumun kapsamına dahil değildir.
