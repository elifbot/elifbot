# ACARBOT v6.2 — paper ve araştırma

v6.2, v6.1 üzerine kurulu **paper odaklı güvenlik güncellemesidir**. Gerçek para için kanıtlanmış kenar yoktur. `live.enabled=False`, izinli canlı zaman dilimleri boş ve kenar kanıtı kapısı açıktır. Bunlar üretim güvenliğinin tek başına garantisi değildir. Testnet/demo özellikleri kaynak sürümdeki bayraklar ve kimlik bilgileriyle ayrıca açılabilir; otomatik açılmaz.


## v6.2 güvenlik güncellemesi ve önemli sınırlar

- Mirror yeni giriş ve DCA artık eksik/kapalı config, kapalı zaman dilimi/kenar kapısı veya yüklenemeyen/kaydedilemeyen kalıcı mirror durumu karşısında reddedilir. DCA ayrıca borsada aynı yönlü pozisyonu ve kayıtlı stop kimliğini arar. Çıkış ve stop güncellemesi bu giriş kapısına bağlanmadı.
- Girişte Binance Futures veya OKX SWAP uçlarından ilgili sembolün **taze** tick/lot/minimum ve OKX kontrat bilgileri denetlenir. Eksik, sıfır, sonlu olmayan, hizasız değerler reddedilir; miktar/stop kullanıcı için sessizce daha riskli yuvarlanmaz. Kontrol sonrası doğrulanmış kurallar emir adaptörünün önbelleğine aktarılır. Düşük seviyeli broker metotlarına doğrudan erişim bu mirror kapısını atlar; bunlar güvenli bir bağımsız işlem API'si değildir.
- Borsaların tüm filtreleri kapsanmış değildir: piyasa emrinde gerçek dolum fiyatı önceden bilinmez, tüm notional/maksimum/fiyat sınırları, bakiyeler, kısmi dolum ve borsa kural değişiklikleri burada tam garanti edilmez. Borsa reddi, kayma ve doğrulama/gerçek emir arasındaki değişim mümkündür. `MARKET_LOT_SIZE` varsa sıfır/eksik değer konservatif olarak reddedilebilir.
- SQLite açılış ve yedekleri `quick_check` ile sınanır; bozuk mirror JSON boş durum diye yutulmaz. Yedek hatasında demo/testnet başlamaz, paper ise uyarıyla devam eder. Yedek üzerine yazılmaz; eski yedekler bu kontrol yüzünden silinmez. **Bu, yanlış ama bütünlüğü sağlam eski yedeği veya ani kapanmada borsada oluşup henüz kaydedilmeyen emri tespit etmez.** Yeniden başlamadan önce borsa ile manuel mutabakat şarttır.
- Konsol/dosya handler'larında bilinen gizli değerler ve yaygın imza/token kalıpları maskelenir; `_FILE` ile okunan değerler de kayda alınır. Maskeleme her formatı/üçüncü taraf handler'ı kapsamaz; şifreleme değildir. `.env` paylaşmayın; gizli dosyaları ve çalışma/log klasörünü işletim sistemi izinleriyle koruyun. Log dosyası ve SQLite dosyası mümkün olduğunda 0600 yapılır.
- Açık emir sorgusu veya iptal hatası artık dolum kabul edilip otomatik MARKET tekrarına dönmez; yeni girişler durdurulur. **Ancak** post-only emir kaybolduğunda gerçek dolumun teyidi, iptal-dolum yarışı, kısmi dolum ve gönderim hatasında otomatik fallback tamamen çözülmüş değildir. Ağ kopmasında açık/korumasız pozisyon kalabilir; borsa ekranından elle kontrol gerektirir. Gerçek hesapta kullanmayın.
- Testler sahte borsa yanıtlarıyla ve ağ/anahtar kullanılmadan yapılır; testnet, gerçek borsa davranışı, strateji kârlılığı veya gerçek para güvenliği doğrulanmış değildir. Varsayılan canlı giriş kapalıdır; açılması tavsiye edilmez.

Ayrıntılı güncelleme notu: `DEGISIKLIKLER_FINAL_v6.2.md`.

## Kurulum

Python 3.11+:

```bash
python -m pip install -r requirements.txt
python -m app.main --help
python -m app.main --paper --exchange okx --symbols BTC-USDT-SWAP --profile kasa1000
```

Son komut internete bağlanır, Ctrl+C ile durdurulur. Oturum çıktıları çalıştırılan dizinde oluşabilir. Paket geçmiş mum verisi, gerçek funding, ölçülmüş maliyet dosyası ve kullanıcı `.env` içermez. Gerçek para kullanmayın.

## v6.1 değişiklikleri

- Doğrulamada funding: `BTC-USDT-SWAP_funding.csv` kaynak anahtarı `okx:BTC-USDT-SWAP` motor anahtarıyla tam enstrüman adı üzerinden eşleştirilir. Eksik semboller `EKSIK_KAPSAMA` veya `UYGULANMADI`; sahte tam kapsama yok. 8 saatlik dönem varsayımı farklı funding aralıklarında ayrıca doğrulanmalı.
- Hedefli 1m önbellek: aralıklı kayıtların arasındaki boşluklar artık kapsanmış sayılmaz.
- `validate_strategy --require-cost-coverage`: belirtilen sembollerin her biri için spread, giriş ve çıkış kayması ölçüm kayıtları yoksa testi reddeder. Bu kontrol verinin güvenilirliğini, örnekleme tazeliğini, gerçek ücretleri veya gecikmeyi tek başına garanti etmez.
- Yeni `tools/momentum_research.py`: 15m pullback, yalnız kapanmış 1h/4h EMA trend filtresi, sonraki mum açılışında giriş, 1R simetrik çıkış, aynı mumda önce stop, kötü stop gap açılışı, açık maliyet varsayımı, kronolojik %75/%25 bölme ve gün kümeli bootstrap. Üretim motoruna veya canlı giriş kapısına bağlanmadı.
- v6.1 yeni raporu `docs/momentum_v6.1.json` (ham mum verisi yok). Önceki raporlar ve kullanıcı verileri yeni paketten çıkarıldı; orijinal Drive dosyası değiştirilmedi.

## Yeni hipotezin sonucu — araştırma, kârlılık kanıtı değil

Çalışma alanındaki mevcut 6 sembolün yaklaşık 90 günlük 5m verisi 15m/1h/4h'ye toplandı. İndikatör süreleri optimize edilmedi. Varsayım: her bacak 5 bps komisyon + 2 bps kayma; **funding uygulanmadı**, 1m/tick dolumu ve portföy limitleri modellenmedi. Sonuçlar varsayımlara bağımlıdır:

| Dönem | İşlem | Ortalama brüt R | Ortalama R, ücret/kayma sonrası, funding hariç | Gün kümeli %95 GA |
|---|---:|---:|---:|---|
| İlk %75 | 1.016 | −0,021 | **−0,288** | [−0,379; −0,200] |
| Son %25 | 446 | +0,038 | **−0,275** | [−0,383; −0,165] |

Son %25 kronolojik olarak ayrılmıştır; veri daha önce başka araştırmalarda görüldüğü için bunun tamamen dokunulmamış kör OOS olduğu iddia edilmez. İşlemler bağımsız örnekler değildir; bootstrap gün bazında kümelenir, bu da tüm zaman bağımlılığını ortadan kaldırmaz. Toplam gözlem, değişken sembol likiditesi ve piyasaların tüm dönemlerini temsil etmez. Hüküm: **kenar kanıtlanmadı, gerçek para yasak.**

Kendi CSV'lerinizle (timestamp ms, open, high, low, close, volume; 5m):

```bash
python -m tools.momentum_research --csv data/BTC_5m.csv data/ETH_5m.csv --out docs/arastirma.json
```

## Yapılmayanlar ve sınırlamalar

- `app.main` ve `tools.validate_strategy` ana motoru hâlâ **5m** temel dilimdedir. Kullanıcının istediği 1h üretim doğrulaması; MTF, 1m kapsama ve BTC bağlamı doğru uyarlanıp karşılaştırmalı test edilmeden yapılmış sayılmaz.
- 365 gün / 30–50 sembol, yeni funding geçmişi, gerçek hesap komisyonları, canlı orderbook/kayma ölçümleri, maker markout, testnet ve bağımsız nihai OOS henüz **yapılmadı**.
- `tools.package_release` eski doğrulama referansını gerektirir. Bu paket eski kanıtları taşımadığından referans kapısı kırmızıdır; yeni geçerli kanıt üretilmeden yeşil gösterilmemelidir.
- `tests/` korunur. Temiz paketteki tarihsel sürüm belge kontrolleri ve referans dosyasına bağlı testler eksik geçmiş kaynaklardan dolayı açıkça atlanır veya raporlanır; bunların atlanması alım-satım doğrulaması değildir.
- Mevcut 15m/1h giriş-kenarı araştırma aracının TF uyarlaması ayrıca denetlenmelidir. Bu yeni araştırma aracı üretim doğrulaması yerine geçmez.

## Test

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python -m ruff check .
```

Ayrıntılar `DEGISIKLIKLER_FINAL_v6.1.md` dosyasındadır.

## Paylaşılan tarihsel analiz raporu hakkında v6.1 notu

- Raporun maliyet kapısı, RVOL ablasyonu ve v5.2 walk-forward sayıları arşivdeki raporlarla uyumludur; bunlar **eski koşulara** aittir. 90 reddedilmiş adayın −1.485,74 USDT karşı-olgusal sonucu, hepsinin gerçek portföyde aynı anda ve aynı fiyatla açılabileceğini kanıtlamaz.
- %74 backtest dolumu (19 emir) ve %17 canlı gözlem (12 emir) farklı ve küçük örneklerdir; kesin dolum oranı veya doğrudan nedensel kıyas değildir. Tarihsel TTL kusuru ayrıca incelenmiştir.
- Çıkış önceliği önerisi, daha sonra yapılan simetrik çıkış / giriş kenarı analiziyle zayıflamıştır. Düşük ödül/risk, değiştirildiğinde stratejinin kârlı olacağını kanıtlamaz. Araştırma ile risk kontrolleri ayrı konulardır.
- v5.2 walk-forward toplam −390,61 USDT ile birincil dönem −80,48 USDT farklı kapsamlardır; biri diğerinin iyileştirme sonucu değildir. 5m/15m giriş ölçümleri varsayım ve veri sınırları içinde negatiftir; 1h örneklemi yetersizdir.
- %60 maliyet/R kapısı bir **reddetme eşiğidir**; gerçekleşmiş maliyet payının %60'a düşürüldüğü anlamına gelmez. %99,9 Monte Carlo değeri kullanılan modele ve örnekleme bağlı tahmindir.
- Rapordaki 2,5–5 USDT işlem başı risk önerisi uygulanmış bir emir veya kârlılık kanıtı değildir; mevcut profile bu tavsiye otomatik atanmadı.
