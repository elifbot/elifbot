# 100.000 USDT Paper Test Oturumu

**Son güncelleme:** 2026-10-24 09:13 (Europe/Istanbul)
**Son paper oturumu:** `44af949` — [Run 40065026239](https://github.com/omeracar56/kripto-bot/actions/runs/40065026239) (`completed / success`)
**PR:** https://github.com/omeracar56/kripto-bot/pull/1 (açık, merge edilmedi)

Bu dosya, kullanıcının istediği çalışma hafızasının GitHub'daki kalıcı karşılığıdır. Testin başlatılması, doğrulamalar ve günlük sonuçlar burada güncellenir. Telegram token'ı, chat ID, API anahtarı veya başka bir sır bu dosyaya yazılmaz.

## Güncel durum

- **1 saatlik kontrol oturumu tamamlandı:** [Run 40065026239](https://github.com/omeracar56/kripto-bot/actions/runs/40065026239) `44af949` koduyla **60 dakika**, temiz **100.000 USDT** sanal kasa ve canlı borsa verisiyle `completed / success` oldu; gerçek emir gönderilmedi. 78 giriş, 4 bağımsız kapanış, oturum sonunda 74 açık paper pozisyon ve **0 duplicate kapanış** doğrulandı. Brüt kapanış K/Z **+9,07 USDT**, nakit kasa **100.000,25 USDT**; açık K/Z ayrı raporlanmadan toplam net özsermaye iddiası yapılmaz. Ayrıntı: `analysis/run_40065026239/GENEL_ANALIZ.md`.
- **Fiili borsa kapsamı:** Binance katalog/metaveri isteği yeniden **HTTP 451** verdi; fiyat akışı **507/507 OKX paritesiydi**. Sonuç OKX-only olarak kaydedildi, Binance+OKX birleşik başarı testi olarak sunulmuyor.
- **Önceki 6 saatlik oturum tamamlandı:** [Run 39969507314](https://github.com/omeracar56/kripto-bot/actions/runs/39969507314) artık aktif değil. Ayrıntılı dedup analizi `analysis/run_39969507314/GENEL_ANALIZ.md` dosyasındadır; 160 bağımsız kapanış ve 872 duplicate kayıt birbirinden ayrılmıştır.
- **Bu düzeltme paketi:** Sembol bazlı kapanış kilidi, çapraz kurtarma için tek sıra + güncel durumla yeniden hesaplama, PaperBroker reduce-only pozisyon doğrulaması ve pozisyon kimliğiyle giriş bileşeni kaydı eklendi. Kontrol run'ında `capraz_kurtarma: false`; trailing + order-flow çıkışı korunmuştur.
- **XBI stop incelemesi:** Başlangıç stopu formülü doğru; erken trailing stop daralması ve K/Z işaretine göre yanlış kapanış-nedeni etiketi `5450e92` ile düzeltildi. Ayrıntı ve regresyon kapsamı aşağıdadır.
- **Çalışma ortamındaki ağ sınırlaması:** Sandbox'tan Binance/OKX public API istekleri `ExchangeNotAvailable` verdi; bu başarısız deneme gerçek-veri başarısı olarak kaydedilmedi. Canlı-veri testi GitHub runner'da yapılacaktır.
- **Gerçek para/emir:** Yok. Bütün test `MODE=paper` ve sanal kasa ile yürütülür. Yeni run başlamadan önce mevcut başka paper run olup olmadığı tekrar kontrol edilecektir.

## XBI stop matematiği ve düzeltmesi

- 50 USDT marj × 10x = 500 USDT notional; marjın %80'i = 40 USDT ve 40 / 500 = %8 fiyat mesafesidir. SHORT başlangıç stopu `giriş × 1,08`, LONG başlangıç stopu `giriş × 0,92` olur.
- Bildirilen −2,32 USDT brüt fiyat K/Z, 40 USDT başlangıç stopuyla uyuşmaz. Kod incelemesinde `initial_stop()` ve `margin_stop_pct()` doğru bulundu; sorun ilk %8 stop formülü değildi.
- Eski `RiskManager.update()` herhangi bir fiyat kârında trailing stopu daraltabiliyor; aday stop hâlâ zarar bölgesindeyken bile başlangıç stopunu yaklaştırabiliyordu. Fiyat tersine dönüp K/Z negatif olduğunda kapanış nedeni K/Z işaretine göre yanlışlıkla “STOP-LOSS (marjın %80)” seçilebiliyordu. Supertrend trailing yolunda da benzer erken daralma mümkündü.
- `5450e92` ile LONG/SHORT trailing ve Supertrend adayının başabaş/kâr bölgesine ulaşmadan başlangıç stopunu daraltması engellendi. Kapanış nedeni artık başlangıç, trailing/başabaş ve kâr kilidi stopunu stopun konumuna göre ayırır; gap/kayma nedeniyle gerçekleşme K/Z'si negatif olsa da gerçek trailing stop “marjın %80'i” diye etiketlenmez.
- Temsilî XBI regresyonunda 149 girişli SHORT'un ilk stopu 160,92'dir. 142,52'de oluşan 149,646 trailing adayı girişin üstünde kaldığı için uygulanmaz; fiyat 149,66'ya döndüğünde pozisyon açık kalır ve ilk stop 160,92'de korunur. İlk stopa gidilirse brüt fiyat K/Z yaklaşık −40 USDT'dir. Ayrıca başabaş üstü trailing, LONG simetrisi, Supertrend ve gap altında doğru neden etiketi test edilir.
- Gerçek XBI işleminin giriş/peak/stop geçmişi bulunmadığından o işlemin kesin fiyat yolu iddia edilmez; yukarıdaki senaryo kodda bulunan hatayı üreten temsilî regresyondur. Eski `09e2ee6` run'ından gelen bildirimler düzeltilmiş kodun sonucu değildir.

## Değişmez test protokolü

| Ayar | Değer |
|---|---|
| Başlangıç kasası | 100.000 USDT sanal para |
| Piyasa | Binance + OKX aktif USDT marjlı perpetual Futures |
| Kapsam dışı | Spot ve tarihli vadeli kontratlar |
| İşlem başına marj | 50 USDT |
| Kaldıraç | Sabit 10x |
| Teknik notional | 500 USDT (50 × 10) |
| Başlangıç stopu | Yaklaşık −40 USDT fiyat K/Z'si |
| Kademe ekleme | Kapalı |
| Sabit/kısmî TP | Kapalı |
| Kâr çıkışı | Trailing/kâr kilidi + doğrulanmış order-flow dönüşü |
| Arbitraj | Kapalı; ayrı 1.000 USDT modeli testi etkilemez |
| Balina bildirimi | Kapalı; veri arka planda stratejide kullanılır |
| Paper pozisyon üst tavanı | 1.000 |
| Toplam marj tavanı | Kasanın %60'ı |
| Live/testnet pozisyon limitleri | Normal/mutlak/aynı-yön: 3/6/4 |

“Sınırsız test”, gerçek para riski olmayan paper deneyi anlamındadır; pozisyon ve marj risk limitleri kaldırılmamıştır. 10x desteklemeyen perpetual kontratlar analiz edilir ancak sabit 10x kuralıyla işlem açılmaz. Stop hedefi komisyon, funding ve kayma nedeniyle tam −40 USDT net zarar garantisi değildir.

## Uygulanan iş paketinin özeti

- Paper bakiye 100.000 USDT'ye çıkarıldı.
- Paper ve live/testnet pozisyon limitleri ayrıldı; toplam marj ve zarar kontrolleri korundu.
- Binance/OKX market kataloglarından aktif USDT perpetual union listesi çıkarıldı.
- Sembol → destekleyen borsa yönlendirmesi OHLCV, fiyat, funding, open-interest ve emir simülasyonuna bağlandı.
- WebSocket abonelikleri 50 sembollük gruplara ayrıldı; geniş evrende Binance derinlik akışı 500 ms'ye ayarlandı.
- REST taraması dört eşzamanlı istekle sınırlandı; emir/risk kararları kilit arkasında sıralandı.
- Geniş evrende order-flow geçmiş kuyrukları bellek sınırlı compact mode'a alındı.
- `/gunluk`, uzun Telegram raporlarını parçalama, oturum sayaçları ve SQLite oturum metaverisi eklendi.
- 24. saatte otomatik rapor, `reports/gunluk_*.txt` kaydı ve planlı kapanış eklendi.
- `start_paper_24h.py` ile ayrı `paper_24h_state.db`, `--fresh` yedekleme ve yeniden başlatma desteği eklendi.
- Süresi dolmuş ancak raporlanmamış oturumun yeniden başlatmada kaybolması engellendi.
- Açılan işlem sayacı oturum metaverisinde kalıcı hale getirildi.

## Doğrulama kaydı

- **79/79 pytest (2026-10-24):** başarılı; 100 eşzamanlı kapamada tek dolgu/ücret/işlem, PaperBroker reduce-only reddi, eşzamanlı pair-rescue ve giriş bağlamı kalıcılığı regresyonları dahil.
- **27/27 bağımsız paper senaryosu (2026-10-24):** başarılı.
- **101/101 hızlı senaryo (2026-10-24):** başarılı.
- **Ruff, compileall, `git diff --check` (2026-10-24):** başarılı.
- **Run 40065026239 bağımsız log analizi:** 78 giriş / 4 kapanış / 74 açık pozisyon, duplicate=0, brüt K/Z=+9,07 USDT ve kasa mutabakatı assert'leri geçti.
- **Post-run gözlenebilirlik düzeltmesi:** son paper mutabakat logu ve günlük rapor artifact yolu eklendikten sonra 79/79 pytest, 101/101 hızlı senaryo, 27/27 v7, Ruff/compileall/diff-check yeniden başarılı.
- **Önceki doğrulama:** 75/75 pytest; XBI benzeri SHORT, LONG trailing, Supertrend başabaş sınırı ve gap/kayma altında doğru kapanış nedeni regresyonları dahil.
- **Süre sonu entegrasyon testi:** Gerçek `main()` akışının rapor yazıp `report_sent=true` kaydettiği ve planlı kapandığı doğrulandı; dış servisler yalnız bu testte sahteydi.
- **Uzak CI:** [Run 40069426451](https://github.com/omeracar56/kripto-bot/actions/runs/40069426451) — `f57684f` sonrası Ruff, byte-compile, regresyon, 101 hızlı senaryo ve 27 bağımsız senaryo başarılı.
- **Gerçek 15 saatlik piyasa sonucu:** Henüz yok; çalışma tamamlanmadan kâr/zarar iddiası yapılmaz.

## Yerel 15 saatlik ana testi başlatma

Bağımlılıklar ve yerel `.env` hazırsa:

```bash
python start_paper_15h.py --fresh
```

Aynı kasa, açık pozisyonlar ve kalan oturum süresiyle devam etmek için:

```bash
python start_paper_15h.py
```

Bağımlılıklar eksikse önce `python -m pip install -r requirements.txt` çalıştırılır. Bilgisayar açık, uyanık ve internete bağlı kalmalıdır. **Aktif GitHub run 39969507314 bitmeden/iptal edilmeden bu yerel oturumu başlatmayın.** Yerel oturum ayrı `paper_15h_state.db` kullanır. `--fresh` eski oturumu silmek yerine `reports/session_backups/` altına taşır. 15. saatte yeni girişler duraklatılır ve rapor gönderilir; açık pozisyonlar zorla kapatılmaz ve açık K/Z rapora dahil edilir.

## Güncel Telegram kısa yolları

Komutlar yalnız `.env` içindeki yetkili `TELEGRAM_CHAT_ID` sohbetinden çalışır.

| Komut | İşlev |
|---|---|
| `/durum` | Kasa, gerçekleşen/açık KZ ve açık pozisyonlar |
| `/guncel` veya `/pozisyonlar` | Yalnız açık pozisyonlar ve güncel fiyatlar |
| `/karzar` veya `/pnl` | Gerçekleşen/açık KZ, komisyon, funding, net paper KZ |
| `/gunluk` | Oturumun ayrıntılı günlük sonuç raporu |
| `/rapor` | Kompakt genel durum raporu |
| `/piyasa` veya `/analiz` | Teknik göstergeler, order-flow, funding ve haberler |
| `/durdur` | Yeni girişleri duraklatır; açık pozisyonları yönetmeye devam eder |
| `/baslat` | Duraklatılan yeni girişleri devam ettirir |
| `/sigorta` | Circuit Breaker sigortasını sıfırlar |
| `/kill` veya `/acil` | Tüm açık pozisyonları kapatmayı dener ve botu kilitler |
| `/yardim` | Telegram komut menüsü |

Otomatik genel durum raporu varsayılan olarak beş dakikada bir gönderilir. Uzun `/gunluk` raporları Telegram sınırını aşmamak için numaralı mesajlara bölünür. Pozisyon kapanış mesajı sembol, yön, kapanış fiyatı, fiyat PnL'i, ROE, USDT **brüt fiyat K/Z** ve kapanış nedenini içerir. Komisyon/funding dahil net toplam `/pnl` ve `/gunluk` raporundaki net paper/oturum K/Z satırından izlenir.

## Çalışma günlüğü

| Zaman (Europe/Istanbul) | İşlem | Sonuç |
|---|---|---|
| 2026-10-23 16:56 | Test protokolü, Telegram komutları ve önceki doğrulamalar bu dosyaya kaydedildi | Kalıcı GitHub kaydı hazırlandı |
| 2026-10-23 16:56 | Doğrudan workflow dispatch denemesi | Entegrasyon yetkisi HTTP 403 verdi; secret/token istenmedi |
| 2026-10-23 16:57 | Geçici push tetikleyicisiyle 55 dakikalık gerçek-veri paper ön testi | [Run 39965501365](https://github.com/omeracar56/kripto-bot/actions/runs/39965501365) başladı; güvenlik kontrolleri geçti, paper adımı aktif. Geçici tetikleyici `5ea02af` ile kaldırıldı |
| 2026-10-23 17:02 | Kapanış bildirimi ve süre davranışı netleştirildi | Kapanışta Telegram'a brüt fiyat K/Z gönderilir; net toplam `/pnl` ve `/gunluk` ile alınır. 55 dakikadan 24 saate otomatik geçiş yoktur |
| 2026-10-23 17:06 | Kullanıcı ana testi 15 saat/sabaha kadar modele çevirdi | `start_paper_15h.py` ve ayrı `paper_15h_state.db` hazırlandı. GitHub run'ı 15 saate uzatılamaz; yerel başlatma gerekli |
| 2026-10-23 17:07 | 55 dakikalık run iptal edilmek istendi | Entegrasyon HTTP 403 verdi; run hâlâ aktif. Telegram çakışmasını önlemek için manuel iptal veya sürenin dolması beklenecek |
| 2026-10-23 17:13 | XBI stop matematiği ve kapanış nedeni incelendi | İlk %8 stop doğru; erken trailing ve yanlış neden etiketi `5450e92` ile düzeltildi. 75/75 pytest, 27/27 bağımsız senaryo, Ruff/compileall/diff-check geçti. Eski run hâlâ aktif ve düzeltmeyi içermiyor |
| 2026-10-23 17:20 | Kullanıcı eski run'ı GitHub arayüzünden manuel iptal etti | Run 39965501365 `completed / cancelled` doğrulandı; aktif başka `paper-live` run'ı yok. Güncel `f93f8ad` koduyla yerel 15 saatlik oturumun Telegram çakışması engeli kalktı; yerel başlatma komutu bekleniyor |
| 2026-10-23 17:25 | Kullanıcı yerel kurulum yerine 6 saatlik GitHub oturumu istedi | `de4f137` ile [run 39969507314](https://github.com/omeracar56/kripto-bot/actions/runs/39969507314) oluşturuldu. 355 dakikalık iç oturum sayacı otomatik rapor gönderecek; dış timeout 358 dakika, GitHub iş üst sınırı 360 dakika. Telegram ve sabit paper güvenlik kontrolleri geçti; temiz 100.000 USDT paper adımı aktif |
| 2026-10-24 08:06 | Duplicate-close, pair-rescue, reduce-only ve giriş ölçümü düzeltmeleri tamamlandı | 79/79 pytest, 101/101 hızlı senaryo, 27/27 v7, Ruff/compileall/diff-check geçti. 60 dakikalık workflow seçeneği eklendi; çapraz kurtarma kontrol run'ında kapalı |
| 2026-10-24 08:08 | 60 dakikalık kontrol paper oturumu başlatıldı | [Run 40065026239](https://github.com/omeracar56/kripto-bot/actions/runs/40065026239), commit `44af949`; geçici push tetikleyicisi `94824d2` ile kaldırıldı |
| 2026-10-24 09:08 | 60 dakikalık paper oturumu tamamlandı ve log kurtarıldı | `completed / success`; 78 giriş, 4 bağımsız kapanış, 74 açık pozisyon, 0 duplicate. Brüt +9,07 USDT; kasa 100.000,25 USDT; OKX=507, Binance 451 |
| 2026-10-24 09:13 | Sonuç analizi ve gözlenebilirlik düzeltmesi | UUID/kasa/ücret mutabakatı kalıcı rapora yazıldı; açık K/Z sınırlaması açıklandı. Sonraki run'larda günlük rapor artifact'a eklenecek |

## 1 saatlik kontrol oturumu sonucu

[Run 40065026239](https://github.com/omeracar56/kripto-bot/actions/runs/40065026239) **başarıyla tamamlandı**; kalıcı ham log `analysis/run_40065026239/paper-session.txt`, tekrar üretilebilir analiz `analysis/run_40065026239/analyze.py`, ayrıntılı rapor `analysis/run_40065026239/GENEL_ANALIZ.md` dosyalarındadır.

| Ölçüm | Sonuç |
|---|---:|
| Bağımsız giriş / kapanış | 78 / 4 |
| Oturum sonunda açık paper pozisyon | 74 |
| Duplicate kapanış | **0** |
| Kapanan işlem sonucu | 3 kâr / 1 zarar |
| Gerçekleşen brüt fiyat K/Z | **+9,07 USDT** |
| Başlangıç → bitiş nakit kasa | 100.000,00 → **100.000,25 USDT** |
| Funding | −0,0172295 USDT |
| Kasadan türetilen toplam komisyon | 8,8027705 USDT |
| Çapraz kurtarma / chase / kademe | 0 / 0 / 0 |
| Fiili veri evreni | **507/507 OKX**; Binance HTTP 451 |

**Önemli yorum:** +0,25 USDT nakit değişimi toplam net özsermaye K/Z'si değildir. 74 açık pozisyonun gerçekleşmemiş K/Z'si bu run'ın kurtarılan log gövdesinde yok; günlük rapor Telegram'a gönderildi fakat rapor dosyası artifact'a eklenmemişti. Bu nedenle kesin net özsermaye değeri uydurulmadı. Sonraki oturumlar için `src/main.py` son mutabakat logu ve workflow'a `reports/gunluk_*.txt` artifact yolu eklendi.

Kapanan dört işlemin tamamı SHORT'tur: CRO +2,98, LRCX −0,15, A +2,91 ve FARTCOIN +3,33 USDT brüt. Üç order-flow çıkışı toplam +9,22, tek trailing çıkışı −0,15 USDT'dir; n=4 olduğu için skor/kaldıraç/eşik optimizasyonu yapılmadı.

## 15. saat sonucu

Bekleniyor. Gerçek 15 saatlik oturum tamamlandığında başlangıç/bitiş özsermayesi, net/brüt gerçekleşen/açık KZ, işlem sayıları, kazanma oranı, komisyon, funding ve açık pozisyonlar bu bölüme işlenecek.
