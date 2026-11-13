# KRİPTO FUTURES BOTU REHBERİ ↔ KRIPTO-BOT v7.8 Karşılaştırması

**Tarih:** 26 Ekim 2026  
**İncelenen belge:** `kripto_futures_bot_rehberi.pdf` — 8 sayfa  
**İncelenen bot:** `/home/user/kripto/kripto-bot-v7.8`

## 1. Kısa sonuç

PDF’de botumuzda bulunmayan “sihirli” bir indikatör yok. Aksine bot; EMA, RSI, ATR, ADX, Bollinger, VWAP, hacim, OI, funding, emir defteri, CVD, likidasyon, çoklu zaman dilimi, haber, makine öğrenmesi, failover ve mutabakat bakımından rehberdeki ilk prototipten daha geniştir.

Asıl eksikler **yeni indikatör değil**, şu mühendislik ve ölçüm kapılarıdır:

1. Baseline stratejide kapanmış mum/fiyat/emir-defteri yaşını tek yerde doğrulayan **sert veri tazeliği kapısı** tam değildir.
2. Komisyon + spread + kayma + funding toplamını beklenen hareketle karşılaştıran açık bir **maliyet-sonrası avantaj kapısı** yoktur.
3. ATR/swing stopuna göre yüzde-riskli boyutlandırma kodu vardır ama mevcut ana profilde kapalıdır; ana profil **sabit 50 USDT marj / 10x / yaklaşık 40 USDT stop riski** kullanır.
4. Gerçek korelasyon hesabı vardır fakat baseline giriş kapısı değil, **Shadow Lab varyantıdır**.
5. Backtest komisyon, sabit kayma ve funding’i modeller; fakat **dinamik spread, gecikme, gap, stop kayması ve gerçek kısmi dolum stres matrisi** eksiktir.
6. Nihai oturum raporu net K/Z ve profit factor üretir; fakat **maksimum kayıp serisi, ortalama kazanç/kayıp, Sharpe, Sortino ve rejim/coin tutarlılığını** tek kabul raporunda tamamlamaz.
7. Bot ilk prototip için oldukça karmaşıktır: teknik + order-flow + haber + ML + türev istihbaratı aynı baseline kararında birleşir. Bu, PDF’nin “az sayıda, mantığı açık kural” uyarısına göre **overfitting ve atıf belirsizliği** yaratabilir.

**Karar:** Strateji eşiklerini gevşetmek veya işlem zorlamak doğru değildir. Önce bildirim, kalıcı çalışma, veri tazeliği ve gözlemlenebilirlik kanıtlanmalıdır.

---

## 2. Madde madde karşılaştırma

| PDF önerisi | Botta durum | Kanıt / yorum |
|---|---|---|
| Katmanlı mimari: veri → özellik → rejim → strateji → risk → yürütme → izleme | **Mevcut** | `market_data.py`, `indicators.py`, `strategy.py`, `risk.py`, `executor.py`, `health.py`, `state_store.py` ayrı modüllerdir. |
| EMA 50/200, RSI 14, ATR 14, ADX 14 | **Mevcut** | `indicators.py` içinde hesaplanır; EMA 9/21/50/200 snapshot’ı da vardır. |
| Bollinger sıkışması/genişlemesi | **Mevcut** | Bollinger bandwidth ve minimum volatilite kapısı vardır. |
| VWAP | **Mevcut, daha geniş** | Kümülatif, UTC günlük/haftalık session VWAP ve anchored VWAP vardır. |
| Hacim z-skoru / olağan dışı hacim | **Mevcut** | Breakout hacim z-skoru ve para-akışı hacim kontrolleri vardır. |
| OI + fiyatı birlikte yorumlama | **Mevcut** | `moneyflow.py` OI/fiyat matrisi; `strategy.py` çelişen OI sinyalini breakout’ta veto eder. |
| Funding’i bağlam ve maliyet olarak izleme | **Mevcut ama giriş maliyet kapısı kısmi** | Funding göstergede skorlanır ve paper K/Z’ye zaman ağırlıklı işlenir; fakat beklenen avantajla açık parasal karşılaştırması yoktur. |
| Spread, derinlik ve kayma kontrolü | **Kısmen mevcut** | 20 kademe derinlik, maker emir ve `%0,30` kayma tavanı vardır. Ayrı “beklenen getirinin yüzde kaçı maliyet” kapısı yoktur. |
| Likidasyon akışını tek başına dönüş sinyali yapmama | **Mevcut** | Likidasyon/squeeze bağlamı ve mıknatıs koruması vardır; tek başına otomatik ters işlem değildir. |
| Kapanmamış mumdan sinyal üretmeme | **Mevcut** | `ohlcv_to_df()` yalnız kapanmış mumları bırakır; göstergeler yalnız yeni kapanmış mumda güncellenir. |
| 4h ana trend + 1h rejim + 15m tetik | **Yakın ama aynı değil** | Bot 1h/4h MTF filtresi + 5m ana sinyal kullanır. Daha hızlı ve gürültüye daha hassastır. |
| Trend/yatay/yüksek volatilite rejimi | **Mevcut** | TREND/RANGE/SIKIŞMA/BREAKOUT sınıflandırması ve rejim bazlı aktif bileşenler vardır. |
| Yatay piyasada trend girişini engelleme | **Mevcut** | `yatay_akis_engeli_aktif`, ADX/ATR/Bollinger ve rejim kapıları bulunur. |
| Haber/spread bozulduğunda işlem yapmama | **Kısmen mevcut** | Haber veto sistemi vardır. Spread/kayma yürütmede korunur; baseline veri tazeliği ve maliyet/avantaj kapısı tamamlanmalıdır. |
| Stop mesafesinden pozisyon boyutu | **Kod var, ana profilde kapalı** | ATR+swing stop ve risk bazlı boyutlandırma `islem_plani` içinde vardır; `aktif: false`. Ana profil sabit 50 USDT marjdır. |
| Günlük zarar limiti | **Mevcut, eşik rehberden gevşek** | Bot `%5`; PDF başlangıç örneği `%1–1,5`. Evrensel doğru değildir ama live öncesi ayrıca test edilmelidir. |
| Martingale/zarara ekleme kapalı | **Mevcut** | `sinirsiz_ekleme: false`, `max_kademe: 1`, `capraz_kurtarma: false`. |
| Korelasyonlu pozisyonları birlikte ölçme | **Kısmi** | Hard max ve aynı-yön max vardır; gerçek Pearson korelasyon guard’ı yalnız Shadow Lab varyantında çalışır. |
| Kill switch, veri/bağlantı hatası | **Mevcut** | Circuit breaker, WS kopma, auth/emir hatası, flash crash, Telegram `/kill`, panel kill switch vardır. |
| Idempotency ve belirsiz emir sonucu | **Mevcut** | Binance/OKX client order ID ve belirsiz emir sonucu korumaları vardır. |
| Kısmi dolum, iptal, yeniden deneme | **Mevcut** | Maker timeout, gerçekleşen miktar, kısmi dolum ve chase/market yolları vardır. |
| Pozisyon/borsa mutabakatı | **Mevcut** | Periyodik exchange reconciliation ve SQLite pozisyon kurtarma vardır. |
| Komisyon, kayma, funding içeren backtest | **Mevcut** | Olay güdümlü backtest bunları içerir. Spread ve gecikme sabit/dinamik stres olarak tam modellenmez. |
| Lookahead kontrolü | **Mevcut** | Gelecek mumlar değiştirilerek skor değişmezliği testi vardır. |
| Out-of-sample | **Mevcut** | `%70/%30` OOS ve walk-forward altyapısı vardır. |
| Stres testi | **Eksik/kısmi** | Maliyet katsayısı, gecikme, gap, order-book incelmesi ve stop kayması kombinasyonlarını sistematik koşturan kabul testi yoktur. |
| Performans metrikleri | **Kısmi** | Net K/Z, win rate, profit factor, drawdown bazı modüllerde vardır; tek nihai raporda uzun kayıp serisi, ortalama win/loss, Sharpe/Sortino ve rejim tutarlılığı eksiktir. |
| API sır güvenliği | **Mevcut** | `.env` izolasyonu, secret masking, live confirmation ve rehberde para çekme yetkisini kapatma talimatı vardır. |

---

## 3. Öncelikli gerçek eksikler

### P0 — Bir saatlik testten önce zorunlu

#### 3.1 Bildirim teslimatı

Mevcut `.env` içinde Telegram ve WhatsApp kimlik bilgileri bulunmuyor. Kod düzeltildi: `REQUIRE_NOTIFICATIONS=1` ile eksik kanal varsa bot artık işlem açmıyor; gerçek açılış mesajı teslim edilemezse de fail-closed davranıyor.

**Kalan dış gereksinim:** Gerçek token/chat ID ve desteklenen WhatsApp sağlayıcı bilgileri.

#### 3.2 Kalıcı gözetmen

Önceki iki süreçte Python traceback ve kontrollü çıkış kaydı yoktu. Bu, dış runtime sonlandırmasını kuvvetle gösterir. Kod artık SIGTERM/SIGINT’i kaydeder, checkpoint üretir ve paper pozisyonları kapatır; ancak SIGKILL yakalanamaz.

**Seçilen çalışma modeli:** Arena’nın uzun yaşayan `start_process` gözetmeni altında bot child-process watchdog’u; ayrıca proje içinde systemd paketi. Çocuk bot çökerse watchdog yeniden başlatır, planlı bir saat bitiminde yeniden başlatmaz. Gerçek çalıştırma bildirim bilgileri gelmeden başlatılmamalıdır.

#### 3.3 Sert veri tazeliği kapısı

Bot kapanmış mum kullanıyor ve WS kopmasını izliyor; fakat giriş anında tek bir baseline kapısı şu üç koşulu birlikte zorlamıyor:

- son kapanmış mumun beklenen zaman dilimine göre yaşı,
- son işlem/fiyat mesajının yaşı,
- emir defterinin yaşı ve yeterli derinliği.

`canli_akis_guveni_aktif: false`; aktif “hafif akış teyidi” yalnız kapsama, işlem sayısı ve hacmi kontrol ediyor. PDF sayfa 6’daki “veri gecikmiş, eksik veya tutarsızsa işlem açma” kuralı için bu eksik tamamlanmalıdır.

### P1 — Altyapı kanıtlandıktan sonra

#### 3.4 Maliyet-sonrası avantaj kapısı

Bot gerçekçi paper bid/ask, komisyon, funding ve kayma hesaplıyor; fakat giriş öncesi aşağıdaki gibi açık bir karar üretmiyor:

`beklenen_brüt_hareket - komisyon - spread - tahmini_kayma - beklenen_funding > minimum_net_edge`

Bu kapı önce **Shadow/Audit** modunda ölçülmeli; tek saatlik veriye göre baseline’a bağlanmamalıdır.

#### 3.5 Korelasyon portföy kapısı

Pearson korelasyon ölçümü ve guard kodu hazırdır; yalnız Shadow Lab’dedir. Baseline’da ikiz varlık koruması, altı pozisyon hard cap ve dört aynı-yön limiti vardır. PDF’nin korelasyon maddesine tam uyum için gerçek korelasyon guard’ı önce shadow’da etkinleştirilip yeterli örnekle karşılaştırılmalıdır.

#### 3.6 Riskin hesap büyüklüğüne bağlanması

Mevcut paper bakiye 100.000 USDT olduğunda 40 USDT stop riski işlem başına yaklaşık `%0,04` eder ve rehber örneğinden daha düşüktür. Fakat aynı sabit 40 USDT risk küçük bir live hesapta oransal olarak büyür.

Live/testnet için güvenli formül:

`izin_verilen_risk = min(sabit_stop_riski, özsermaye × risk_yüzdesi)`

ATR/swing modülü hazır olduğu için yeni motor yazmak yerine profil ve üst tavan testi gerekir.

### P2 — Yeterli işlem örneğinden sonra

#### 3.7 Backtest stres matrisi

Aşağıdaki senaryolar birlikte koşturulmalıdır:

- komisyon `1x / 1,5x / 2x`,
- kayma `2 / 5 / 10 / 20 bps`,
- spread normal / 2x / 4x,
- 250–2000 ms emir gecikmesi,
- kısmi dolum `%25/%50/%75`,
- stop sırasında gap ve kötü gerçekleşme,
- funding işaret/değer değişimi,
- WS kesintisi ve yeniden bağlanma.

#### 3.8 Nihai metrik seti

Birleştirilmesi gerekenler:

- net K/Z ve profit factor,
- maksimum drawdown,
- ortalama kazanç / ortalama kayıp,
- en uzun kayıp serisi,
- Sharpe / Sortino / Calmar,
- sembol, yön, rejim, zaman dilimi ve çıkış nedeni kohortları,
- beklenen / gerçekleşen spread-kayma-funding farkı,
- reddedilen sinyal nedenleri ve sayıları.

---

## 4. Ayar farkları: doğrudan kopyalanmamalı

| Konu | PDF örneği | Mevcut bot | Değerlendirme |
|---|---:|---:|---|
| Kaldıraç | İlk testlerde 2x–3x | 10x | PDF değeri başlangıç hipotezidir. Kaldıraç tek başına risk değildir; stop ve nominal büyüklükle birlikte değerlendirilir. Live öncesi 3x/5x/10x OOS ve stres karşılaştırması gerekir. |
| İşlem riski | `%0,10–0,25` kısa vade; `%0,25–0,50` genel | Paper’da yaklaşık `%0,04`/işlem | Mevcut büyük paper bakiyede daha düşüktür. Küçük live hesapta sabit dolar riski için yüzde üst tavan gereklidir. |
| Günlük zarar | `%1–1,5` örneği | `%5` | Paper keşfinde ölçülebilir; live için gevşektir. Örnek eşik körlemesine kopyalanmamalı, stres sonuçlarıyla seçilmelidir. |
| Giriş zaman dilimi | 15m örnek | 5m | 5m daha fazla gürültü ve maliyet üretir. 5m ve 15m ayrı OOS/shadow kohortlarında karşılaştırılmalıdır. |
| Strateji sadeliği | Az kural | Teknik + akış + haber + ML + türev verisi | Yeni indikatör eklemek yerine bileşen atfı ve ablation testi gerekir. |

---

## 5. PDF’den alınmaması gereken yanlış yorumlar

- RSI 70 üstünde otomatik short veya 30 altında otomatik long yapılmamalı; bot zaten bunu yapmıyor.
- OI artışı tek başına yön sinyali değildir; bot OI’yi fiyat/akış bağlamında kullanıyor.
- Funding aşırılığında otomatik ters pozisyon açılmamalı.
- Likidasyon bölgesi kesin dönüş noktası sayılmamalı.
- Evrensel ADX, ATR veya kaldıraç eşiği kabul edilmemeli.
- İkinci kısa oturumda işlem çıkmadı diye sinyal eşikleri gevşetilmemeli.

---

## 6. Önerilen uygulama ve test sırası

1. **Telegram + WhatsApp kimlik bilgilerini gir.** Bağımsız testte iki gerçek mesajı gör.
2. **P0 veri tazeliği hard-gate ve ret sayaçlarını ekle.** Strateji eşiğini değiştirme.
3. **Arena `start_process` + child watchdog** altında `PAPER_SESSION_HOURS=1` çalıştır.
4. Bir saat sonunda açık paper pozisyonu `0`, nihai rapor mevcut, bildirim teslim edilmiş ve `last_exit.reason=scheduled_paper_session_complete` olmalı.
5. Ardından en az 24–48 saat veya anlamlı işlem örneğinde Shadow Lab’i aç: maliyet-edge ve korelasyon varyantlarını baseline’la eşleştir.
6. Sonuçlar yeterli örneğe ulaşmadan 5m/15m, kaldıraç, stop veya skor eşikleri değiştirilmemeli.

## 7. İkinci koşunun “0 işlem” sonucu

Bu PDF incelemesi, sıfır işlemin tek başına hata olduğunu göstermiyor. Botun filtresi PDF’deki “ne zaman işlem açmamalı” yaklaşımıyla uyumludur. İkinci süreç bir saati tamamlamadığı için:

- yeterli tarama turu oluşmadı,
- reddedilme nedenlerinin tam dağılımı çıkmadı,
- piyasa rejimi boyunca ölçüm yapılmadı.

Bu nedenle altyapı ve bildirim kanıtlanmadan eşik gevşetmek bilimsel olarak yanlış olur.

---

## Nihai hüküm

Botun **indikatör veya futures verisi eksiği yok denecek kadar azdır**. PDF’ye göre en değerli geliştirmeler:

1. fail-closed veri tazeliği,
2. maliyet-sonrası edge ölçümü,
3. hesap büyüklüğüne bağlı risk tavanı,
4. baseline öncesi shadow korelasyon testi,
5. stres testi ve tekleştirilmiş performans raporu,
6. sadeleştirme/ablation ile hangi bileşenin gerçekten katkı verdiğinin kanıtlanmasıdır.

Bunlar işlem sayısını zorla artırmaz; tersine botun yalnız ölçülebilir ve sağlıklı koşulda işlem açmasını sağlar.
