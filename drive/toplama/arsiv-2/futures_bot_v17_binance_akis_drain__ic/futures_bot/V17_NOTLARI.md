# v17 — Binance gerçek akışı ve doğal çıkış tamamlama

**Durum: paper-only araştırma sürümü; gerçek emir göndermez.** Ana baseline
stratejisi ve kalıcı TP/SL/risk parametreleri değiştirilmedi. `--akis-golge`
varsayılan olarak kapalıdır. Küçük örneklem sonucuna göre eşik optimizasyonu
yapılmadı; 300+ işlem öncesi kalıcı edge/parametre kararı verme kuralı korunur.

## 1. Bu sürümde tamamlananlar

### Binance gerçek taker akışı

v16'daki OKX-only sınırlaması kaldırıldı. `scanner/binance_flow.py` artık
Binance USDⓈ-M üretim combined-stream kanalını kullanır:

```text
wss://fstream.binance.com/market/stream?streams=<symbol>@aggTrade/...
```

- Semboller üretim `/fapi/v1/exchangeInfo` yanıtındaki `TRADING`, `PERPETUAL`,
  `USDT` kontratlarından alınır.
- 200 sembollük partiler kullanılır; REST aggTrade polling yapılmaz.
- `m=true` alıcının maker olduğunu gösterir; taker yönü `sell`, aksi durumda
  `buy` olarak kaydedilir.
- Miktar doğrudan base varlık miktarıdır; USD akış `price × quantity` ile bulunur.
- Sembol başına son aggregate trade ID tutulur; eski/yinelenen ID'ler iki kez
  işlenmez.
- `stream.binancefuture.com` kullanılmaz. Bu kanalın ID serisi üretim REST ile
  uyuşmadığı için elenmiştir.

OKX ve Binance işlemleri aynı `AkisDefteri` ve `FlowShadowEngine` içinde,
`(exchange, symbol)` anahtarıyla ayrı tutulur. Binance teknik başlangıcı için
yalnız tamamlanmış üretim 1m kline'lar kullanılır; desteklenmeyen `1s` kline
varsayılmaz.

### Çapraz-borsa aynı-varlık koruması

Gölge adayları ve pozisyonları base varlık üzerinden karşılaştırılır. Örneğin
`BTC-USDT-SWAP` ile `BTCUSDT` aynı varlık sayılır. Aynı base için bir aday veya
pozisyon varken diğer borsadan gelen sinyal reddedilir. Farklı varlıklar için
yapay toplam pozisyon limiti eklenmez.

### Süre sonunda doğal çıkış bekleme (drain)

Yeni isteğe bağlı bayrak:

```bash
python3 ws_bot.py --sure-dk 15 --cikis-tamamlama-dk 10 --akis-golge
```

- `cikis-tamamlama-dk=0`: eski davranış; tarama süresi bitince kalanlar
  `session_end` ile kapanır.
- Değer sıfırdan büyükse tarama bitince yeni ana ve gölge girişleri durur,
  bekleyen limitler ve gölge adayları iptal edilir.
- Açık pozisyonlar kendi TP/SL/timeout veya gölge 2×ATR/3×ATR çıkışlarına
  bırakılır. Hepsi doğal kapanırsa oturum beklemeden biter.
- Ek bekleme üst sınırı da dolarsa yalnız kalanlar `drain_end` ile kapatılır.
- Durum JSON'unda aşama, kalan drain süresi ve reddedilen yeni sinyal sayısı
  bulunur.

Negatif drain süresi reddedilir. Süresiz (`--sure-dk 0`) oturumda drain yalnızca
bir tarama süresi tanımlanırsa devreye girer.

### Genişletilmiş gölge kapanış telemetrisi

`logs/ws_akis_golge_kapanis.csv` alanlarına şunlar eklendi:

- `close_ret_pct`: yön düzeltilmiş kapanış getirisi;
- `giveback_pct`: `max(0, MFE - kapanış getirisi)`;
- `initial_stop`: 2×ATR başlangıç felaket stopu;
- `stop_price`: kapanış andaki takip eden stop;
- `atr_at_exit`: kapanış andaki ATR.

Böylece yalnız net PnL değil, kazancın ne kadarının geri verildiği ve çıkışın
stop/ATR bağlamı da incelenebilir.

## 2. Regresyon doğrulaması

- v16 tabanı ve yeni iki-borsa/drain testleri birlikte çalıştırıldı.
- **235 test geçti, hata yok.**
- Yeni testler: Binance taker yönü, aggregate-ID tekilleştirme, base/USD akışı,
  borsa ayrımı, aynı-base aday/pozisyon koruması, aday iptali, doğal stop,
  `drain_end`, kapanış telemetrisi, tamamlanmış Binance mumları, bot giriş
  engeli, CSV nedenleri ve negatif süre kontrolü.
- Dört değiştirilen modül `py_compile` kontrolünden geçti; yeni CLI bayrakları
  `--help` çıktısında doğrulandı.

Testlerin geçmesi stratejinin kârlı olduğunu göstermez.

## 3. Gerçek public-veri smoke testi

Çalışma: `/home/user/bot_runs/v17_smoke_20261028/futures_bot`

Komut:

```bash
python3 -u ws_bot.py --sure-dk 2 --cikis-tamamlama-dk 1 --akis-golge
```

- **182 saniye, exit 0**
- 13 sinyal; ana 13 açılış, 13/13 CSV kapanışı; açık ana pozisyon 0
- Gölge 3 açılış, 3/3 kapanış; açık gölge pozisyon 0
- Toplam **224.989** gerçek trade: Binance **155.191**, OKX **69.798**
- Binance `/market/` aggTrade: 3 bağlantı; bağlantı, callback, veri, mum, gölge
  ve CSV hata sayaçları **0**
- Drain sırasında 12 yeni sinyal reddedildi

| Seri | İşlem | Kazanç | Net USDT | Kapanış nedenleri |
|---|---:|---:|---:|---|
| Ana baseline | 13 | 6 | +3,3999889364 | 2 `take_profit`, 11 `drain_end` |
| Binance akış gölgesi | 3 | 0 | −2,8094724249 | 3 `drain_end` |

Bu turda üç gölge pozisyonu da Binance'de açıldı; dolayısıyla Binance gerçek
trade → CVD/VWAP onayı → gölge açılış → telemetrili kapanış yolu canlı veriyle
doğrulandı. İki ana pozisyon drain sırasında doğal `take_profit` ile kapandı.
Gölgede bu kısa turda doğal ATR çıkışı oluşmadı; doğal stop ve drain ayrıca
birim testlerle doğrulandı.

Makine özeti: `reports/v17_smoke_summary.json`.

**Bu 2+1 dakikalık tur performans/edge testi değildir.** Üç gölge işlemin
negatif sonucu küçük örneklemde yeni parametre aramak için gerekçe yapılmadı.
Ana baseline'ın pozitif sonucu da genelleştirilmemelidir.

## 4. Bilinen sınırlar

- Funding, gerçek emir kayması, order-book kuyruğu ve likidite etkisi yoktur.
- Paper gölge giriş/çıkışı gerçek public trade fiyatıyla, iki taraf `%0,05`
  taker ücreti varsayımıyla hesaplanır.
- Kesin tepe/dip önceden bilinmez; CVD/VWAP onayı dönüşün bir kısmını kaçırabilir.
- Uzun vadeli performans ve OKX/Binance karşılaştırması için daha uzun,
  bağımsız ve 300+ işlemli paper örneklem gerekir.
- Bu sürümde strateji eşiği veya kalıcı TP/SL değişikliği yapılmamıştır.
