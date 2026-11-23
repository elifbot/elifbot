# TradingAgents · OKX vadeli paper testi

Bu deney yalnızca OKX'in **genel** REST verilerini kullanır; borsa anahtarı veya özel API çağrısı yoktur ve borsaya gerçek emir göndermez. Yerel simülasyondur, OKX demo hesabı değildir.

## Evren, sinyal ve işlem

- Aktif OKX `SWAP` ve `FUTURES` sözleşmeleri alınır ve yaklaşık dakika başı güncellenir. Sabit sembol sayısı veya hacme göre ilk N filtresi yoktur. Ticker'lar yaklaşık 5 saniyede bir sorgulanır; taze fiyat yoksa sinyal üretilemez.
- Yaklaşık bir dakikalık örneklenen fiyat yönü LONG veya SHORT **aday sinyalidir**. En az 50 saniye veri gerekir, fiyat değişmemişse sinyal yoktur. Her yeni fiyat örneğinde tekrar sinyal doğabilir; yapay işlem sayısı limiti veya sembol başına bekleme süresi yoktur. Bu basit sinyalin kârlılığı kanıtlanmış değildir.
- **Doğrudan sinyal modu:** Her aday, model cevabı beklenmeden sanal işlem motoruna gönderilir. TradingAgents araştırmacı, trader, risk ve portföy düğümleri ayrı dört işçiyle eş zamansız değerlendirir; bu değerlendirme işlemi onaylamaz, iptal etmez veya yönünü değiştirmez. Dolayısıyla işlem kararının kaynağı TradingAgents değil, fiyat yönü sinyalidir. Model çıktıları yalnızca gözlemdir.
- Yaklaşık fiyat doğrulaması, kontrat biçimi, sözleşme miktar adımları ve teminat yeterliliği kontrolleri uygulanır; koşu süresince vadesi dolacak sözleşmede yeni giriş yapılmaz. Sinyal geldi diye bu zorunlu koşulları sağlayamayan işlem açılmış sayılmaz ve reddin nedeni kaydedilir.
- Aynı sözleşmede birden fazla LONG ve SHORT sanal girişi mümkündür. Bunlar ayrı simüle pozisyonlardır; OKX gerçek hedge/net işlemleriyle birebir aynı değildir. Ek eşzamanlı pozisyon sayısı sınırı yoktur. 1.000 USD kasa ve pozisyon başına hedef 50 USD teminat olduğu için yeterli özkaynak kalmadığında borsa fiziği gereği emir reddedilir.
- GitHub standart koşucusunda dört CPU ve dört model değerlendirme işçisi kullanılır. Bu, her sinyalin anında yapay zekâ analizi alacağını garanti etmez. Model kuyruğundaki eski değerlendirmeler silinebilir; doğrudan paper işlemler bu kuyruktan etkilenmez. Model yanıtları ve hataları panelde ayrı gösterilir.

## Simülasyon sınırlamaları

- USD/USDT/USDC fiyatlı lineer ve inverse sözleşmeler desteklenir. OKX'in USD_UM ve USD_UM_XPERP kimlikleri, USD teminatlı lineer oldukları doğrulanarak USD olarak değerlendirilir. USD/USDT/USDC yaklaşık 1 USD sayılır. Farklı bir para biriminin gerçek dönüşümü veya teminat parası riski modellenmez.
- Hedef 50 USD teminat / 10x, 500 USD notional. OKX kontrat değeri, çarpanı, lot ve minimum miktarı kullanılarak aşağı yuvarlanır; hedefe %10'dan fazla uzaksa reddedilir. Komisyon %0,05 ve varsayımsal kayma %0,05 her yönde uygulanır.
- Örneklenen fiyatta tahmini net zarar −10 USD'ye ulaşınca pozisyon kapatılır; örnekleme, boşluklar ve kayma yüzünden zarar daha büyük olabilir. Yaklaşık CROSS bakım marjı %0,5'tir. Funding, emir defteri, spread, kısmi dolum, gerçek kaldıraç limitleri ve OKX'in tasfiye kademeleri modellenmez.
- Süre kurulum/model indirme tamamlandıktan sonra ölçülür. Açık pozisyonlar süre bitince zorla kapatılmaz; son fiyattan işaretlenir. `summary.json` ve `events.jsonl` bitince Actions artifact'idir. Sinyaller, giriş/reddetme, açık pozisyonlar, kapanış ve model hataları kaydedilir.
- Fiyat akışı ve sinyal denemesi yoksa koşu başarısız olur. İşlemlerin doğrudan sinyalden açılması, TradingAgents'in çalıştığı veya karar ürettiği anlamına gelmez; model durumu ayrıca raporlanır. Kısa bir test sonucu kârlılığı kanıtlamaz.

## GitHub Actions

```bash
gh workflow run ollama_sonda.yml --ref "$(git branch --show-current)" -f model=paper-30m
```

## Arena inceleme paneli

```bash
.venv/tradingagents/bin/python -m panel.tradingagents_server --host 0.0.0.0 --port 8000
```

Gerçek verili koşu GitHub Actions'ta çalışır; toplu canlı durum yaklaşık 12 saniyede bir GitHub Checks üzerinden Arena paneline aktarılır. Depo herkese açık olduğu için telemetri de herkese açıktır, anahtar içermez. `PAPER_RUN_ID` ile belirli koşu sabitlenebilir. Panel açılırken yapılan teknik prova ayrı bir bölümdedir ve sentetik veri + sahte model kullanır; gerçek koşunun sonucu değildir.
