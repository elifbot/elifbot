# v16 — Gerçek para-akışı ve dinamik çıkış araştırması

**Durum: araştırma sürümü; üretim/canlı işlem için hazır değil.** Ana v15 baseline
stratejisi ve risk parametreleri değiştirilmedi. Bütün yeni davranışlar opt-in ve
paper-only'dir. Canlı emir gönderen kod yoktur.

## 1. Amaç ve kullanıcı kabul ölçütleri

Küçük sabit TP'nin ücret sonrası kazancı kesmesi yerine:

- LONG'da gerçek agresif alış/para girişini ve fiyat onayını ölçmek;
- SHORT'ta agresif satış/para çıkışını ve düşüşün tükenmesini izlemek;
- anlık tek-tik giriş yerine onay beklemek;
- sabit küçük TP yerine ATR/piyasa yapısıyla kazancı taşımayı araştırmak;
- tepe/dip önceden biliniyormuş gibi davranmamak;
- bütün karşılaştırmaları iki taraf ücreti sonrası net PnL ile yapmak;
- ana baseline'ı değiştirmeden ayrı gölge modda çalışmak;
- 300+ işlem öncesi kalıcı edge/parametre iddiasında bulunmamak.

## 2. Gerçek veri kanalı

### OKX

`scanner/money_flow.py` ve `scanner/ws_scanner.py` artık opt-in OKX public
`trades` kanalını destekliyor. Her gerçek işlemde:

- `side` taker yönü olarak kullanılır;
- SWAP `sz` kontrat olduğundan base miktar `sz × ctVal × ctMult` ile bulunur;
- USD akış `base miktar × px` ile hesaplanır;
- 5/15/30/60 saniyelik alış USD, satış USD, CVD, alış oranı, toplam USD,
  işlem sayısı ve akış VWAP'ı üretilir.

MFI/OBV veya mum hacmi CVD diye etiketlenmez. Eksik kontrat çarpanı olan veri
akışa yazılmaz ve hata sayacına eklenir.

Canlı doğrulamada BTC-USDT-SWAP için `ctVal=0.01`, `ctMult=1` okundu ve gerçek
`trades` mesajları alındı.

### Binance

Binance USDⓈ-M `/fapi/v1/klines` canlı probunda `interval=1s` isteği
**HTTP 400 / Invalid interval** döndürdü. Bu nedenle Binance için gerçekmiş gibi
CVD üretilmedi. Binance sinyal satırlarında akış alanları boş ve `hazir=0` olur.
Yeni gölge motoru bu sürümde yalnız OKX'tir.

Resmî kaynaklar:

- OKX API v5: https://www.okx.com/docs-v5/en/
- Binance USDⓈ-M kline: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data

## 3. Yeni modlar

### Yalnız ölçüm

```bash
python3 ws_bot.py --sure-dk 10 --akis-olcum
```

Ana işlem kararlarını değiştirmez. Şunları üretir:

- `logs/ws_akis_sinyal.csv`: sinyal anındaki 5/15/30/60 sn akış;
- `logs/ws_akis_kapanis.csv`: ana işlemin giriş/çıkış akışı ve net sonucu.

### Ayrı dinamik akış gölgesi — araştırma, varsayılan kapalı

```bash
python3 ws_bot.py --sure-dk 10 --akis-golge
```

Bu bayrak akış ölçümünü de açar. Ana baseline yine aynı şekilde çalışır; ayrı
`FlowShadowEngine` şu kuralları paper olarak uygular:

1. OKX sinyalinden sonra en fazla 60 saniye aday bekler.
2. LONG için 15 sn CVD > 0 ve fiyat > 60 sn akış VWAP'ı;
   SHORT için 15 sn CVD < 0 ve fiyat < 60 sn akış VWAP'ı gerekir.
3. Onay kesintisiz en az 1 saniye sürmelidir; tek tikle giriş yoktur.
4. Giriş ve çıkış fiyatı aynı gerçek OKX `trades` kanalından gelir.
5. **Sabit TP yoktur.**
6. 2×ATR başlangıç felaket stopu ve 3×ATR chandelier takip vardır.
7. ATR/Supertrend durumu 100 adet 1 dakikalık REST mumuyla başlatılır; yalnız
   `confirm=1` mumlar kullanılır. Yeni trade OHLC'si ancak dakika kapandığında
   göstergeye eklenir; gelecek mum kullanılmaz.
8. Aynı gölge sembolde ikinci aday/pozisyon açılmaz; toplam yapay pozisyon
   limiti eklenmez. Gölge yalnız OKX olduğundan çapraz-borsa mükerrerliği yoktur.

Çıktılar:

- `logs/ws_akis_golge_olay.csv`
- `logs/ws_akis_golge_kapanis.csv`
- `logs/ws_durum.json` içindeki `akis_golge_*` sayaçları

**Bu modun ilk tam canlı paper sonucu negatiftir; üretime taşınmamalıdır.**

## 4. Testler

- v15 tabanı: 211 test
- Gerçek akış/kontrat/CSV testleri: +7
- Giriş onayı, LONG/SHORT, 1 sn süreklilik, 60 sn aday süresi, 2×ATR,
  chandelier, nedensel mum ve ana/gölge izolasyonu: +7
- **Toplam: 225 test geçti.**
- `py_compile` ve CLI bayrak kontrolleri geçti.

Testlerin geçmesi stratejinin kârlı olduğunu göstermez; yalnız kod davranışını
doğrular.

## 5. Birinci tam ölçüm turu

Çalışma: `/home/user/bot_runs/v16_10dk_akis_20261028/futures_bot`

- Süre: 603 saniye; exit 0
- 44 sinyal, 33 ana açılış, 33/33 ana kapanış; açık pozisyon 0
- 66.074 gerçek OKX trade; akış veri/kayıt hatası 0
- 14 sonuçlanmış OKX işleminin tamamında giriş akışı hazırdı
- OKX baseline net: **−7,8129 USDT**
- 15 sn CVD pozisyon yönüyle yalnız 1/14 işlemde uyumluydu
- 60 sn VWAP'a göre dönüş fiyat onayı 0/14 idi

Bu, mevcut fade'in çoğunlukla dönüş onayından önce girdiğini gösterdi. Basit
anlık CVD filtresi yerine onay bekleyen aday modeli kuruldu.

Çıkış akışı ile MFE geri verme arasındaki ilişki nedensel kanıt sayılmadı;
ters akış ve kayıp aynı fiyat hareketinin sonucu olabilir.

## 6. Ham trade replay araştırması

Çalışma: `/home/user/bot_runs/v16_10dk_akis_20261028`

- 12 sembol, 31.200 gerçek geçmiş OKX trade
- 12/12 sembolde sinyalden en az 90 saniye önce kapsama
- ATR/Supertrend yalnız tamamlanmış 1m mumlardan
- 25 USDT marj, 10x, iki taraf `%0,05` taker ücreti
- Küçük örneklem; optimizasyon değil, önceden belirlenen hipotez karşılaştırması

Seçilmiş replay sonuçları:

| Giriş / çıkış | İşlem | Net USDT |
|---|---:|---:|
| Canlı OKX baseline (gerçek sonuç) | 14 | −7,8129 |
| Ham-trade replay, anında giriş / sabit TP-SL | 14 | −9,3161 |
| Anında giriş / ATR takip | 13 | +0,6629 |
| Anında giriş / Supertrend + akış | 14 | −5,9399 |
| Anında giriş / akış + ATR geri-verme | 13 | −1,6473 |
| CVD15+VWAP60 / sabit TP-SL | 9 | +1,9486 |
| CVD15+VWAP60 / ATR takip | 9 | +1,9486 |
| CVD15+VWAP60 / Supertrend + akış | 10 | −3,0609 |

Tam tablo: `reports/v16_okx_replay_summary.json`.

Yeni bir `--akis-olcum` turundan sonra aynı araştırma şu komutlarla tekrarlanabilir
(ham dosyalar `reports/okx_replay_raw/` altına iner):

```bash
python3 scripts/okx_replay/fetch_okx_replay.py
python3 scripts/okx_replay/replay_flow.py
```

### Replay sınırlaması

Replay baseline ile canlı baseline arasındaki yaklaşık 1,50 USDT fark nedeniyle
replay, canlı botun birebir tekrarı değildir. Replay her gerçek trade fiyatını
görür; mevcut canlı baseline `tickers` ve 100 ms çıkış turunu kullanır. Örneğin
bir stop ham trade'de session-end'den 91 ms önce görülürken canlı tur onu
yakalayamadı. Yeni gölge bu yüzden giriş/çıkışta doğrudan `trades` kullanır.

Replay'deki ATR avantajının önemli kısmı kazananı daha uzun taşımaktan değil,
bazı kayıpların 2×ATR ile daha erken kesilmesinden geldi. Bu nedenle sonuç
“kazancı maksimuma taşıma kanıtı” sayılmadı.

## 7. Yeni gölgenin bağımsız canlı paper turu — başarısız aday

Çalışma: `/home/user/bot_runs/v16_10dk_akis_golge_20261028/futures_bot`

- Süre: 606 saniye; **exit 0**
- 70 sinyal; ana 43 açılış; 43/43 kapanış; açık pozisyon 0
- 126.849 gerçek OKX trade
- Ana kayıt, telemetri, akış veri, gölge ve ATR mum hatası: **0**

| Seri | İşlem | Kazanç | Net USDT | Ücret USDT |
|---|---:|---:|---:|---:|
| Ana baseline — tüm borsalar | 43 | 21 | −4,9837 | 10,7614 |
| Ana baseline — yalnız OKX | 20 | 8 | −14,8394 | 5,0036 |
| Yeni akış gölgesi | 15 | 3 | **−17,3061** | 3,7541 |

Gölge kapanış nedenleri:

- 6 `disaster_2atr`
- 1 `chandelier_3atr`
- 8 `session_end`

Ortalama giriş bekleme 34,66 saniye; ortalama MFE `%0,341`, MAE `%0,617`.
Aynı sinyal zamanıyla eşleşen 13 işlemde baseline **−1,4684 USDT**, gölge
**−14,0674 USDT** verdi. Diğer iki gölge işlemin baseline açılışı yoktu;
bunlar ayrı stratejinin bağımsız adaylarıdır ve zorla eşleştirilmedi.

Makine özeti: `reports/v16_canli_akis_golge_ozeti.json`.

## 8. Karar

- Bu aday **üretime alınmadı** ve “en iyi strateji” olarak sunulmuyor.
- `--akis-golge` varsayılan kapalıdır; yalnız araştırma içindir.
- Ana TP `%1,25`, SL `%2`, pozisyon limitleri ve diğer baseline parametreleri
  değiştirilmedi.
- Tek replay ve tek 15 işlemlik canlı gölge örneğiyle kalıcı edge iddiası yok.
- Aynı veri üzerinde 2×ATR'yi 2,5/3 yapmak, 60 saniyeyi kısaltmak veya CVD
  eşiği tarayarak “en iyi” sonucu seçmek yapılmadı; bu küçük örneklemde
  aşırı uyum olurdu.
- İlk canlı sonuç, replay hipotezini doğrulamadı. Özellikle geç onay ve sıkı
  2×ATR başlangıç stopu ayrı hipotezler olarak incelenmeli; ana stratejiye
  kalıcı parametre değişikliği yapılmamalı.

## 9. Bilinen sınırlar

- Gerçek akış yalnız OKX; Binance akışı yok.
- Order-book/likidite kuyruğu, funding ve gerçek emir kayması modellenmez.
- Paper fiyatı gerçek trade fiyatıdır; iki taraf taker ücreti uygulanır.
- Gölge sinyalleri ana baseline'ın açılış reddinden bağımsız değerlendirir;
  kendi aynı-sembol koruması vardır.
- Funding/OI beslemeleri bu canlı yol için hâlâ strateji girdisi değildir.
- Kesin tepe/dip önceden bilinmez; dönüş onayı getirinin bir kısmını bırakır.
- 15 gölge işlem strateji seçmek için yeterli örneklem değildir; fakat mevcut
  sonuç bu adayı varsayılan açmamak için yeterli bir risktir.
