> **Tarihsel belge:** Aşağıdaki ifadeler yazıldıkları aşamanın durumunu anlatır. Güncel kullanım ve funding sınırları için `README.md` ve `docs/OKX_SON_SURUM_KILAVUZ.md` önceliklidir.

# OKX / Binance public vadeli piyasa verisi

> **Sonraki güncelleme:** Önceki belgelerdeki açıkça seçilebilen `www.binance.com` public yolundan 519 Binance kontratı alındı; `fapi` 451 durumu ve yetkilendirme belirsizliği sürüyor. En güncel iki-borsa snapshot: `reports/okx_binance_iki_borsa_2026-11-09.json`; ayrıntı `BINANCE_ONCEKI_BELGE_INCELEMESI.md`. Aşağıdaki ilk deneme tarihsel kayıttır.

## Gerçek bağlantı denemesi — 9 Kasım 2026, 21:05:30 UTC

- OKX `public/instruments?instType=SWAP` ve `market/tickers?instType=SWAP`: HTTP 200. Kaynak 543 SWAP metadatası içerdi; bunların 528'i canlı lineer USDT teminatlıydı. Ancak **239'u kripto olmayan veya sınıfı belirsizdi** (hisse/emtia dahil), 15'i lineer USDT kapsamı dışındaydı. OKX'in `instCategory=1` beyanına göre sonuç: **289 kripto USDT sürekli vadeli kontratı**. Bunlar borsa kontratlarıdır; benzersiz ve bağımsız coin sayısı, alım izni veya yatırım uygunluğu değildir.
- O anda 289 ticker tazelik kontrolünden geçti; 283'ü basit OKX ön filtreyi geçti. Bu son sayı yalnız *o andaki* taze fiyat, metadata uyumu ve en fazla 30 bps anlık makastır; strateji sinyali, derinlik, likidite, kalıcı fiyat veya işlem önerisi değildir. Her şey değişebilir.
- Binance USD-M Futures `https://fapi.binance.com/fapi/v1/exchangeInfo` bu çalışma ortamında **HTTP 451** verdi. İlk bağımsız erişim kontrolünde toplu 24 saat ticker uç noktası da 451 döndürdü; sonraki rutin, metadata yoksa ticker isteğini yeniden yapmadı. 451 başka bir ağda erişim durumu veya kullanıcı konumu hakkında kesin hüküm değildir. Erişim engeli aşılmadı, alternatif host/proxy denenmedi. Binance gerçek sembol sayısı veya anlık fiyatlar elde edilmiş gibi gösterilmez.
- `reports/okx_binance_universe_2026-11-09.json` ve `.csv` eklenmiş **tarihsel anlık görüntülerdir**, canlı akış değildir ve şimdi güncel fiyat olarak kullanılmamalıdır. CSV kısa inceleme görünümüdür; JSON kaynak/tazelik/hata bilgilerini de içerir. Binance verisi erişilemediği için iki borsada **1000 gerçek sözleşmeye ulaşıldığı iddia edilmez**.

## Uygulanan veri hattı

`market_universe_cli.py` varsayılan yalnız OKX SWAP enstrüman + toplu ticker alır; `--venues both` açık seçildiğinde ayrıca Binance USD-M `exchangeInfo` + toplu 24 saat ticker uçlarına, API anahtarı olmadan **bir kez** herkese açık GET yapar. Gizli endpoint, emir, Paper DB veya sonsuz döngü yoktur. Borsalar ayrı kaydedilir; aynı isimli varlıklar/1000 çarpanlı sözleşmeler otomatik birleştirilmez. OKX sadece borsanın kripto sınıfı (`instCategory=1`) ve canlı lineer USDT SWAP; Binance ise `TRADING`, `PERPETUAL`, USDT quote ve margin için listelenir. Binance `underlyingType=COIN` borsa sınıflandırması kullanılır ama bağımsız doğrulanmadığından; her Binance varlığının kripto olduğuna dair iddia yoktur. Çoklama üst sınırı 20.000 satırdır; **1.400 sahte Binance simgesi** testte eksiksiz işlendi, bu gerçek 1.400 simge bulunduğu anlamına gelmez.

Borsa/endpoint hataları ayrı kaydedilir. Bozuk/tekrarlı sembol, API hata yanıtı ve aşırı büyük yanıt reddedilir; eksik ticker `MISSING`, bayat veri `STALE`, gelecek veri `FUTURE` veya geçersiz veri `INVALID` görünür. HTTP 429/451 gibi durumlarda otomatik retry veya kısıt aşma yoktur. Dört tekil sabit HTTPS adresi dışında tarayıcı istek yapmaz, redirect izlemez; erişim izinleri ve platform kullanım koşulları ayrıca kullanıcı tarafından doğrulanmalıdır. Binance `/ticker/24hr` toplu istek weight **40**; sık periyodik sorgulama, 1000 sembole REST istek yağdırma veya paralel paylaşılan IP'ler için rate-limit garantisi verilmez.

Güncel anlık görüntüyü daha sonra almak için yeni bir dosya adıyla:

```bash
mkdir -p data
python market_universe_cli.py --out data/yeni-pazar-anlik.json
```

Bu komut yalnız **veri taraması** yapar; Paper işlemi başlatmaz. Var olan çıktı dosyası üzerine yazılmaz. Kullanıcının ortamında Binance erişilebilirse parser borsa verisini ekleyebilir; bu, burada gerçek Binance entegrasyonu doğrulanmış demek değildir.

`acar/binance_public_data.py` ayrıca Binance 1m kapalı mum, 20 kademeli public derinlik ve mark/premium verisi için sabit GET adaptörleri içerir; sahte veriyle birim testinden geçti ve sonradan eski belgede işaret edilen www public adresiyle BTC için kısaca denendi; fapi 451 ve kullanım yetkisi soruları sürmektedir. Latest funding rate kesin settlement kanıtı diye yorumlanmaz. Bu adaptör **Binance PAPER motoruna veya otomatik settlement'a bağlı değildir**.

## Bot ile sınırlı bağlantı: izleme listesi üretme

`market_watchlist_cli.py` taze rapor içindeki OKX kripto normal kurallı kontratları basit ön filtreyle seçip mevcut OKX PAPER worker'ın kabul ettiği **en fazla 4 simgeli** konfigürasyonu üretir. Verinin her simge için en fazla 30 saniye, raporun en fazla 120 saniye yaşında olmasını ister. Sıralama yalnız `24 saat base hacmi × son fiyat` yaklaşık büyüklüğüdür; gerçek işlem hacmi, yatırım sinyali veya başarı sıralaması değildir. Pozisyon başı hedef notional, kaldıraç ve minimum notional kullanıcı tarafından açıkça sağlanır; minimum notional OKX'ten doğrulanmaz. Aşağıdaki rakamlar *sadece sözdizimi örneğidir*:

```bash
python market_watchlist_cli.py --report data/yeni-pazar-anlik.json --out data/yeni-izleme.json --target-notional 20 --leverage 2 --min-notional 5
```

Bu aşama dosya oluşturur, **worker/PAPER başlatmaz**. Gerçek veriyle taramadan worker konfigürasyonu oluşturmaya kadar olan yol bu tur denendi. Ayrıca yalnız BTC-USDT-SWAP için OKX enstrüman, public derinlik, tahmini funding, son mum ve 1267 kesintisiz kapanmış bir dakikalık UTC geçmiş mumu alınıp doğrulandı. PAPER worker ve ileriye dönük PAPER **denenmedi**. Konfigürasyon fiyatlar değiştiğinde bayatlar, gerçek dolum garantilemez ve manuel inceleme gerektirir. Worker ileride ayrıca açık `--confirm-public-paper` ister; enstrüman sorgusunda OKX kripto sınıfı `instCategory=1` ve normal işlem kuralını da yeniden ister, her seçilen piyasa için kapanmış sürekli geçmiş/derinlik/funding/portföy risk kapılarını denetler. Mevcut worker yalnız OKX için ve bir defada **en çok 4 seçili simge** içindir; 289/1000 sembolde eşzamanlı mum-sinyal hesaplaması veya otomatik pozisyon açma yapılmaz. Binance PAPER bağlantısı, gerçek funding settlement ve borsa paritesi tamamlanmamıştır.

## Teknik kaynaklar

- [OKX public instruments ve ticker](https://www.okx.com/docs-v5/en/): toplu SWAP metadatası, ticker ve `instCategory` sınıflandırması.
- [Binance USD-M exchange information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information) ve [24 saat ticker](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics).
- [Binance 1m mumlar](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data), [derinlik](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Order-Book), [mark/premium](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price).

OKX detay denemesinde ilk kitap isteğinde tazelik saati HTTP yanıtından önce alındığından sunucu zamanı yanlışlıkla gelecek sayıldı. Gerçek isteklerde saat yanıt sonrası ölçülerek düzeltildi; kitap, funding ve mum yeniden başarılı kontrol edildi. Bu tek simgeli anlık kontrol uzun süreli ağ dayanıklılığı veya tüm 289 simgenin ayrıntılı verisini doğrulamaz.

Güncel OKX çalışma adımları ve yeni varsayılanlar `OKX_SON_SURUM_KILAVUZ.md` içindedir.
