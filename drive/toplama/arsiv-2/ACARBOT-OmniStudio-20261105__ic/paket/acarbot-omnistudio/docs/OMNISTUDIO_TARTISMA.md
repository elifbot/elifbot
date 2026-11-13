# OmniStudio Konseyi — ACARBOT entegrasyonu üzerine tartışma

**Tarih:** 5 Kasım 2026 · **Katılımcılar:** OmniStudio'nun 20 denetçi profili
(`omnistudio/ai/council.py → _FOCUS`), yani Dengeli Tam-Görev, Brüt-Kenar/Komisyon,
Para Akışı/CVD, Trend-Yapı, Makas/Baz, Ters-Seçilim/Maker Kuyruğu, Çoklu Zaman
Dilimi, Testere/Tuzak, Dalga Sürdürülebilirlik ve Karşı-Tez Başdenetçisi +
sert varyantları.

> **Dürüstlük notu:** Bu bir insan toplantı tutanağı değildir. Aşağıdaki görüşler,
> koddaki 20 deterministik denetçi profilinin bakış açısıyla yazılmıştır. Anahtar
> olmadığı için **hiçbir dil modeli çağrılmadı** (`ai_generated=false`); bu metin
> "20 YZ onay verdi" diye sunulamaz. Gerçek LLM görüşü için `.env`'e sağlayıcı
> anahtarı girilip `LIVE_LLM` modunda çalıştırılmalıdır.

---

## 0. Maildeki durumun özeti (tarafsız)

| Konu | Maildeki iddia | Ölçülen / doğrulanan |
|---|---|---|
| Kapsam | "1.661 sözleşme keşfedildi" | ✅ doğru (genişletilmiş tarama: **2.880**; **2.112'si** PAPER uygun) |
| PAPER dışı | "614 sözleşmede otomatik PAPER yok" | ✅ doğru, ama nedeni **motor kısıtıydı**, ürün değil |
| Anlık mum akışı | 3.322 kapanmış mum, medyan 1,024 sn | ✅ doğru (yeniden ölçüldü: 120 mum, medyan ~890 ms; Binance+OKX) |
| Eski mum reddi | "1.402/2.735 eski" → sonra "0" | ⚠️ kök neden **ısınma turunun eski mumla karar üretmesiydi**; kapı eklenerek yamandı |
| Akış / genişlik / 15dk | "bilinmiyor, nötr varsayıldı" | ❌ konseyin 3/6 denetim boyutu **verisiz** çalışıyordu |
| Funding muhasebesi | "yok" | ❌ defterde hiç yoktu |
| Likidasyon | "HTML'deki marjin/likidasyon modeli taşınmadı" | ❌ hiç yoktu |
| Test kanıtı | "1.800 sentetik parite kontrolü" | ⚠️ JS=Python eşitliğini kanıtlar, **kenar** kanıtlamaz |
| Gerçek emir | 0 | ✅ doğru ve doğru kalmalı |

---

## 1. Eksik tamamlama — kim neyi buldu, kodda ne yapıldı

### 1.1 Dengeli Tam-Görev Denetçisi — "en büyük boşluk köprüydü"
> "Maildeki üç modül birbirine bağlı değildi: `contract_math.py` vardı ama motora
> bağlı değildi, `future_contract_audit.py` kendi uydurduğu `face/lot_step`
> değerleriyle '1.661 kayıt eşleşti' diyordu, `paper_eligible()` ise 614 sözleşmeyi
> sert şekilde dışlıyordu. Yani kanıt ile üretim arasında köprü yoktu."

**Yapıldı:** `acarbot/contracts.py` — gerçek `exchangeInfo` alanlarından
`Instrument → ContractSpec` üretimi. Uydurma yok; her sözleşmenin ret gerekçesi
tek tek yazılı. Sonuç: **PAPER kapsamı 1.047 → 1.070**, ve neden dışarıda kaldığı
artık sözleşme sözleşme açıklanabiliyor (X-PERP 259, TRADIFI 235, vadeli 42,
inverse 46, USD/USDC marj, SETTLING 137 ...).

### 1.2 Para Akışı ve CVD Denetçisi — "nötr sıfır, ölçüm değil"
> "`metrics={'flow': None}` yerine 0 yazmak, denetçiye 'akış yok' demek değil,
> 'akış dengeli' demektir. Bu iki şeyi karıştıran bir konsey, fail-closed değil
> **fail-neutral**'dır."

**Yapıldı:** `acarbot/flow.py` — Binance `aggTrades` (`m`), OKX `trades` (`side`),
Gate `futures.trades` (`size` işareti) üzerinden kayan pencerede gerçek CVD.
Kontrat→baz dönüşümü `face` ile yapılıyor (OKX `ctVal=0.01 BTC` gibi), böylece
farklı borsaların hacimleri karşılaştırılabilir. Veri yoksa `available=False` →
konsey o boyutu "ölçülmedi" olarak işaretliyor.

### 1.3 Çoklu Zaman Dilimi Uyum Denetçisi
> "Kodun hiçbir yerinde 15dk mumu YOKTU. 5dk mumlardan 15dk üretmek 3 mumu
> birleştirmekle olur ve bunu yapmamak bir eksiklik, tercih değil."

**Yapıldı:** `mtf_alignment()` — 5dk kapanmış mumlardan 3'lü kovalarla gerçek
15dk OHLC serisi, EMA20/EMA50 rejimi (`UP`/`DOWN`/`MIXED`) ve sinyal yönüyle uyum.

### 1.4 Makas ve Baz Denetçisi
> "Gate tarafında `spread_bps>8` kapısı vardı ama Binance/OKX tarafında makas
> HİÇ ölçülmüyordu; `futures_stream_paper.py` sadece `bid/ask` alıp geçiyordu."

**Yapıldı:** `marketdata.MarketSession.quotes()` altı pazarın hepsinde tek arayüz;
makas + 15 sn tazelik + `PRICE_MOVED_AWAY` kontrolü her borsada aynı.

### 1.5 Ters-Seçilim / Maker Kuyruk Denetçisi
> "Taker varsayımı doğru, ama funding'i hiç ödememek de bir varsayım."

**Yapıldı:** `PaperBook.apply_funding()` — LONG pozitif oranda öder, SHORT alır;
oran borsadan gelir, sabit 8 saat varsayılmaz; `minutes_to_funding<3` → giriş reddi;
`FUNDING_UNKNOWN` → giriş reddi (0 varsayıp bedava pozisyon taşımak yok).

### 1.6 Testere ve Tuzak Engelleyici
> "`extension_atr` ve `choppiness` ölçülüyordu ama geriye dönük test yoktu;
> 1.800 sentetik kontrol bir stratejinin testere rejiminde nasıl davrandığını
> söylemez."

**Yapıldı:** `acarbot/backtest.py` — gerçek 5dk mumlarla, sinyalden **sonraki**
mumun açılışında giren, bar içinde stop/hedef çakışırsa **stop** varsayan,
lot adımı ve min notional uygulayan A/B/C/D/E katman karşılaştırması.

### 1.7 Karşı-Tez Başdenetçisi — "en tehlikeli cümle"
> "Raporda '148 ağsız test geçti' yazıyor. Bunların 1.800'ü sentetik parite.
> 'Test geçti' ile 'strateji kenarı var' arasındaki farkı okuyucuya bırakmak
> bir dürüstlük borcudur."

**Yapıldı:** Her rapora `## Dürüstlük sınırları` bölümü zorunlu; `SONUC.json`'da
`real_orders: 0`, `real_money_approved: false`; geriye dönük test sonucu
`limitler` dizisiyle birlikte yazılıyor.

---

## 2. Ölçüm sonuçları (bu entegrasyonla üretilen gerçek sayılar)

**A) Kapsam** — 6 pazar, tam evren taraması: **2.880 sözleşme / 2.112 PAPER uygun
(%73,3)**. Gate.io USDT 1.080 (tamamı uygun), Binance USD-M 942 (522), OKX SWAP 540
(510), Binance COIN-M 30 (0), OKX FUTURES 287 (0), Gate BTC 1 (0).
Retlerin tamamı gerekçeli: TRADIFI 234, SETTLING 137, USDC marj 38, X-PERP 259,
vadeli 42, inverse 46, kripto dışı dayanak 15.

**B) Geriye dönük test, 240 sembol × ~25 saat, aynı örneklem, 5 katman:**

| Katman | İşlem | Net (USDT) | PF | Kazanma | Maks. DD |
|---|--:|--:|--:|--:|--:|
| A · Temel (maildeki gibi) | 372 | −839,44 | 0,226 | %18,6 | — |
| B · A + gerçek funding | 372 | −842,05 | 0,224 | %18,6 | — |
| C · B + konsey (ölçülmüş bağlam) | 147 | −381,53 | 0,245 | %28,6 | — |
| D · C + portföy riski & 1R koruma | 21 | −31,90 | 0,174 | %28,6 | — |
| E · D + funding kaçışı | 21 | −31,90 | 0,174 | %28,6 | — |

Okunuşu (dürüstçe):
1. **Strateji kenarı yok** — trend takibi bu pencerede komisyon sonrası negatif.
   Bu, maildeki "kârlılık iddiası yoktur" hükmünü bağımsız olarak doğruluyor.
2. **Katmanların etkisi net:** konsey işlem sayısını %60 azaltıp kaybı yarıya
   indiriyor (zararı durdurmuyor), portföy riski kaybı 12 kat azaltıyor — çünkü
   pozisyon boyutunu küçültüyor. Bu bir "iyileşme" değil, **daha az kötü** olmak.
3. Funding katkısı küçük çıktı (−2,60 USDT / 372 işlem): oranlar bu pencerede çok
   düşüktü (±0,0001). Volatil funding dönemlerinde etkisi büyür.
5. Çıkış dağılımı konuşuyor: A katmanında 237 STOP_LOSS / 130 MAX_HOLD / 5 TAKE_PROFIT.
   Yani stop hedeften 2× yakın olduğu için yapı sistematik olarak stop'a yazıyor;
   TP/stop oranı ve ATR çarpanı **ayrı bir araştırma konusu** (P1/5).
4. Funding kaçışı hiç tetiklenmedi → o katman **ölçülmedi**, "yararsız" değil.

**C) Konsey: ölçüm var / yok karşılaştırması (canlı ölçüm dosyasından):**
Aynı adaylar için skorlar ölçülmüş bağlamla **daha yüksek** çıkıyor (örnek:
XTZUSDT SHORT — 44,5 → 50,8) çünkü 15dk uyumu gerçekten sağlanmıştı; ancak
maliyet kenarı kapısı ikisini de reddetti. Yani maildeki nötr varsayım adayı
**yanlışlıkla değil, şansla** reddediyordu; doğru girdi kararı gerekçelendiriyor.

**D) Anlık akış (15 dakikalık canlı PAPER, WS):** 40 sembol, Binance USD-M ve
OKX SWAP WS'ten **120 kapanmış mum** alındı; kapanıştan kayda medyan **~890 ms**,
en uzun 1,4–3,0 sn (maildeki 1,024 / 3,072 ile uyumlu). 102 mum değerlendirildi,
5 sinyal üretildi, **5'i de maliyet kenarı kapısında reddedildi** (11 bps beklenen
hareket < 14 bps maliyet) → 0 sanal pozisyon. Gate.io WS bu örnekte kapanmış mum
göndermedi (bağlantı ve güncelleme var, kapanmış mum yok) ve bu **sessizce
yutulmadı**, raporda `connections=1, closed=0` olarak yazıldı.

---

## 3. Üstüne ne eklenebilir — önceliklendirilmiş öneriler

### P0 — gerçek para konuşulmadan önce şart
1. **Emir defteri (L2) ve gerçek dolum modeli.** Şu an taker+makas+2bps kayma
   varsayımı. Derinlik olmadan 1.070 sözleşmenin çoğunda (ince likidite) sonuç
   iyimser. → WS `depth20@100ms` + kendi emrinin seviyeleri yemesini simüle et.
2. **Geçmiş CVD arşivi.** Geriye dönük testte akış boyutu nötr kaldı; bu yüzden
   konseyin en değerli iki denetçisi (CVD, ters-seçilim) testte etkisiz. →
   Collector'ı tick seviyesine indirip `trades` tablosu tut (şu an sadece mum var).
3. **PAPER ↔ gerçek hesap mutabakat testi (dry-run).** Emir GÖNDERMEDEN, borsanın
   `order` uç noktasını `testnet`/`dryRun` ile doğrulayıp reddedilen emir
   kodlarını (lot adımı, min notional, reduceOnly) toplamak. Bugün bu hatalar
   ancak gerçek parayla görülür.
4. **Bakım marjı kademeleri.** Likidasyon `1/lev − mmr` yaklaşımı; borsalar
   pozisyon büyüklüğüne göre kademeli marj uygular. → kademe tablosunu
   `exchangeInfo`/`riskLimits` uçlarından çek.

### P1 — kenar arayışı (ürün değeri)
5. **Rejim filtresi.** Ölçüm net: trend stratejisi testere rejiminde para
   kaybediyor. `choppiness` + 15dk rejim + genişlik ile "işlem yapma" kararını
   birinci sınıf çıktı yap (bugün sadece ret nedeni).
6. **Funding-arbitraj / baz taşıma stratejisi.** Zaten ölçtüğümüz funding +
   iki borsa fiyatı ile spot-perp veya borsalar arası basis izlenebilir. En
   düşük riskli, en ölçülebilir kenar burada.
7. **Korelasyon kümeleme.** 8 pozisyonun 8'i de BTC-beta olabilir; gross
   exposure limiti bunu görmez. → Aynı kümede net yön maruziyeti sınırı.
8. **Maker giriş modu.** Taker 5bps + 2bps kayma, 11 bps'lik maliyetin yarısı.
   `require_trade_through=True` ile maker dolum simülasyonu OmniStudio'da var;
   acarbot tarafına bağlanmalı.

### P2 — operasyon ve güven
9. **7/24 dayanıklılık.** Collector sandbox'ta; saat sıçraması, DNS, 429 ve
   borsa bakımı için ayrı "süreklilik" raporu (maildeki `DISCONTINUOUS` kavramı
   PAPER tarafına da taşınmalı).
10. **Olay tabanlı uyarı.** WS kopması / funding kaçışı / devre kesici →
    e-posta veya webhook. (Bu entegrasyon Gmail'e rapor gönderebilir.)
11. **Panel.** `omnistudio/web` salt-okunur panosu var; acarbot run klasörlerini
    (SONUC.json + RAPOR.md + kararlar.jsonl) okuyan tek ekran.
12. **Şema sürümleme + manifest.** `KONTROL-MANIFEST.json` var; her koşunun
    kod commit'i + SHA-256'sı raporda olmalı ki "hangi kodla üretildi" tartışması
    bitsin.

### Yapılmaması gerekenler (konsey kararı)
- ❌ Kaldıraç artırmak: likidasyon mesafesi kapısı zaten %12 altını reddediyor;
  maildeki −9 USDT'lik sonuç kaldıraçla düzeltilecek bir şey değil.
- ❌ Sadece işlem sayısını azaltıp "iyileşti" demek: D katmanı bunun örneği;
  PF 0,174 → kayıp küçüldü, kenar yok.
- ❌ "20 YZ onayladı" ifadesi: anahtar yoksa `RULE_BASED_QUANT`; raporda
  `ai_generated=false` yazıyor, bu değişmemeli.

---

## 4. Karar önerisi

1. Gerçek para **yok**, süre 3–5 gün kesintisiz PAPER'a çıkarılmalı; bu süre
   boyunca yukarıdaki P0 maddeleri (özellikle geçmiş tick arşivi ve derinlik)
   tamamlanmalı.
2. Trend stratejisi **varsayılan olarak kapalı** kalsın; ölçüm kenar göstermedi.
   Yerine funding/basis izleme + rejim filtresi araştırılsın.
3. Her rapor `real_orders=0`, `real_money_approved=false` ve katman tablosuyla
   yayınlanmaya devam etsin. Kenar bulunana kadar "kâr" kelimesi kullanılmasın.
