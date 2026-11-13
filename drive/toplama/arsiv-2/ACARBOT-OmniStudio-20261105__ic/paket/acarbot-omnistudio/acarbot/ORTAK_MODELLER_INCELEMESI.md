# Ortak model incelemesi ve çapraz değerlendirme

Bu inceleme 5 Kasım 2026'daki futures kodu içindir. OmniStudio'nun 20 sağlayıcı kaydı kendi başına yanıt üretmez; erişim/anahtar gerekir. Gerçek erişilebilir dış servisler kullanıldı. İlk turda `futures_market.py`, `futures_paper.py`, `ledger.py`, `strategy.py` kodları Kilo ve OVHcloud'a gönderildi. Gizli anahtarlar, e-postalar, kullanıcı verileri, çevresel değişkenler gönderilmedi. Kodun gönderildiği servisler içeriği kendi politikalarına göre işleyebilir. `reviews/futures-ortak-inceleme-20261105/gorusler.json`: 9 gerçek istek, 7 yanıt, 2 timeout. Model adı servis etiketidir; bağımsız doğrulanmış kimlik değildir.

Yanıt verenler: Kilo üzerinden Cohere North Mini Code, NVIDIA Nemotron 3.5 Lightning, Dots-3 Note, NVIDIA Nemotron 3 Ultra; OVHcloud üzerinden Mistral Small 3.2, Qwen3.5-397B, Qwen3.6-27B. Kuzey Mini cevabında ciddi tekrar ve yanlış istek sayısı var, kanıt sayılmadı.

İkinci turda diğer model cevaplarından kesitler üç modele verilip çapraz eleştiri istendi. `reviews/futures-capraz-inceleme-20261105/gorusler.json`: Nemotron 3.5 Lightning, Mistral Small 3.2, Qwen3.6-27B yanıtladı. Bu süreç gerçek API yanıtlarıdır; 20 bağımsız sağlayıcı katılmış gibi sunulmaz. Yanıtlar emir onayı değil; kod gözlemleri öneriler bağımsız olarak doğrulanır.

## Değerlendirilen öneriler
- **Kabul:** Her sözleşmeyi global bekleme olmadan kapanmış mum akışı ile işle; sembol/borsa bazlı durum ve tekil kayıt tut. Binance `k.x=true`, OKX `confirm=1`. REST yalnız başlangıç geçmişi veya gerektiğinde boşluk giderme için düşünülebilir.
- **Kabul:** Lineer ve inverse PnL farklıdır; sözleşme büyüklüğü ve yerel settlement para birimini koru, bilinmeyen kur ve bakiyeleri uydurma.
- **Kabul ama tamamlanmadı:** Kopma/boşluk tespiti ve hedefli REST onarımı; collector boşlukları kaydeder, otomatik backfill henüz uygulamaz. PAPER stratejisinin CANDLE_GAP kontrolü vardır.
- **Reddedildi/düzeltildi:** Bazı cevaplar OKX mum dizisinde hacim ve kapanış indeksini yanlış verdi. Doğrusu `[ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]`, yani indeks 7 ve 8.
- **Reddedildi:** Binance USD-M için `/market` olmadan yazılan eski stream yolları veya OKX REST yollarının `wss://` ile değiştirilmesi. Gerçek uçlar gerçek ağ testi ve borsa dokümanlarıyla kontrol edildi.
- **Reddedildi:** Funding zamanını bütün sözleşmeler için sabit 8 saat olarak varsaymak; borsadan/sözleşmeden güncel değer ve etkin zaman gereklidir. 180.000 ms üç dakikadır.
- **Reddedildi:** Inverse kârı settlement para biriminde verirken otomatik mark fiyatıyla çarpmak ve bunu yine native coin olarak nitelemek. Bu ancak ayrı, açıkça etiketli değerleme olabilir. Ayrıca USDT, USD ve USDC 1:1 varsayılmadı.
- **Reddedildi:** 1.661 sözleşme × 260 mum = 431.860 HTTP isteği iddiası; 260 tek bir endpoint yanıtındaki mum sayısıdır, istek sayısı değil. Başka hatalı hız limiti iddiaları doğrulama olmadan uygulanmadı.

## Resmî kaynaklar
- Binance USD-M 5m kline ve `/market` yönlendirmesi: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Kline-Candlestick-Streams
- Binance COIN-M mum birimleri: https://developers.binance.com/docs/derivatives/coin-margined-futures/websocket-market-streams/Kline-Candlestick-Streams
- OKX WebSocket/mum/sözleşme açıklamaları: https://www.okx.com/docs-v5/en/
- OKX lineer ve inverse PnL: https://www.okx.com/help/iii-calculation-of-contract-profit-and-loss-6-20-2022
