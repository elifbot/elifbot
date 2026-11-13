# Kripto Bot — Kalıcı Proje Hafızası ve Devralma Kaydı

**Güncelleme:** 2026-10-24
**Ana kaynak:** https://github.com/omeracar56/kripto-bot
**Çalışma dalı:** `arena/787d4de8-kripto-bot`
**Bu dosyanın amacı:** Yeni geliştirmeler başlamadan önce bütün deney, karar, kanıt ve güvenlik bağlamını tek yerde korumak.

> Bu dosya kalıcı proje/devralma hafızasıdır. Kesin sayıların kaynağı ilgili run klasöründeki ham artifact ve JSON dosyalarıdır. Yeni bir sonuç eski sonucu geçmişe dönük olarak değiştirmez; yeni kanıt olarak eklenir.

## 1. Kullanıcının ana hedefi ve değişmez kurallar

- Binance ve OKX canlı Futures verisi birlikte kullanılacak; OKX-only sonuç çift-borsa sonucu sayılmayacak.
- Paper modda hayali kasa ve gerçekçi sanal dolgular kullanılacak; gerçek emir gönderilmeyecek.
- Normal deney işlem büyüklüğü **50 USDT marj, sabit 10x**; 500 USDT yalnız teknik notional'dır.
- Kademe ekleme ve sabit TP yok; kâr çıkışı trailing + order-flow dönüşüyle, koruyucu stop likidasyondan önce olacak.
- 40 USDT fiyat K/Z hedefi, ücret/funding/kayma sonrası net zarar garantisi değildir.
- Balina olayları arka planda izlenir; Telegram'da balina alarmı istenmez. İşlem, K/Z, pozisyon ve genel durum bildirimleri korunur.
- Kullanıcı GitHub üzerinden ilerlemek istiyor; yerel runner önerilmeyecek. Secret/token/chat ID hiçbir rapora yazılmayacak, `.env` commit edilmeyecek.
- Tek run, kısa kesit veya Shadow sonucu zararsızlık/kâr garantisi değildir; otomatik canlı kural veya parametre optimizasyonu yapılmayacak.
- Botun doğal kapattığı işlemler ile manuel, erken, sigorta ve süre-sonu kapanışları ayrı kohortlarda incelenecek.
- Yeni fikirler önce izole Shadow/paper ölçümüne gidecek; baseline sonuçları geçmiş referans olarak korunacak.

## 2. Mimari ve tamamlanan geliştirmeler

- `src/shadow_lab.py`: aynı baseline girişleri üzerinde varsayılan altı izole varyant:
  `net-exit`, `flow-confidence`, `volatility-gate`, `range-confirmation`,
  `technical-harmony`, `portfolio-guard`; PDF v2 profili opt-in yedinci `pdf-confluence`
  varyantını açar.
- `src/pdf_indicators.py`: üç PDF'den seçilen eksik teknikleri kapalı OHLCV'den hesaplar;
  `src/trade_quality.py::pdf_confluence` altı yön ailesinden en az dört uyumu Shadow'da
  ölçer. Harici on-chain/opsiyon/makro/sosyal veri uydurulmaz; envanter:
  `paper-lab/PDF_INDIKATOR_ANALIZI.md`.
- `src/trade_quality.py`: akış veri-hazır-olma, güven ayarlı akış girişi, teknik çelişki,
  volatilite/maliyet alanı, range akış onayı ve portföy guard ölçümleri.
- `src/shadow_review.py`: baseline ve varyantlarda bot-kapanış kohortu, eşleştirilmiş pozisyon
  karşılaştırması, ret adaylarının MFE/MAE/stop/maliyet sonuçları, median net, drawdown,
  borsa/rejim ve ilk-iki-işlem yoğunlaşması.
- `src/risk.py`, `src/exit_rules.py`, `src/executor.py`: gerçek giriş/çıkış ücreti, funding,
  MFE/MAE, maliyet sonrası net çıkış ve observer bağlantıları.
- `src/main.py`: Shadow observer entegrasyonu, süre-sonu kontrollü kapanış, periyodik
  `partial_*` checkpoint dosyaları. Checkpoint nihai closeout yerine geçmez.
- `src/circuit_breaker.py`: flash-crash alarmı ilk tetiklemeden sonra idempotent; reset'te
  eski fiyat çiftleri temizlenir. Koruma eşiği kaldırılmadı.
- `.github/workflows/paper-live.yml`: iki-borsa preflight, masked artifact/dal kaydı,
  otomatik cohort/shadow-review ve partial artifact desteği.
- `.github/workflows/paper-control.yml`: sayısal run ID doğrulamalı kontrollü iptal isteği.
- `tests/test_executor_shadow.py`: gerçek Executor açılış → observer → kapanış → closeout/rapor
  zinciri. `tests/test_pdf_indicators.py`: PDF paketi ve opt-in varyant testleri. Son tam
  doğrulama: **111 pytest**, Ruff ve compileall PASS; ayrı v7 **27/27** önceki doğrulamadır.

## 3. Deney kayıtları

### A. Ana üçlü — karşılaştırma kapsamı

| Run | Profil | Süre / durum | Ana sonuç ve sınır |
|---|---|---|---|
| [39969507314](https://github.com/omeracar56/kripto-bot/actions/runs/39969507314) | 100.000 USDT, 50 marj/10x, çapraz kurtarma açık | 5,9167 saat; success | Eski kod `de4f137`; 160 primary açılış/kapanışa karşı 1.032 kapanış kaydı, 872 duplicate. Raporlanan kasa K/Z **−796,20 USDT**. Duplicate etkisini çıkaran hassasiyet hesabı yaklaşık **−113,36 USDT**; temiz backtest değildir. Fiili evren OKX-only. |
| [40077757773](https://github.com/omeracar56/kripto-bot/actions/runs/40077757773) | 100.000 USDT, çapraz kurtarma kapalı | 2 saat; success, planlı closeout | 85 giriş/85 kapanış, açık 0. Genel net **+43,3096 USDT**. Botun doğal kapattığı 30 işlemde net **+95,60 USDT**, PF **36,07**; 55 süre-sonu kapanışı ayrı. Binance+OKX kanıtlı. |
| [40090692312](https://github.com/omeracar56/kripto-bot/actions/runs/40090692312) | 1.000 USDT paper + her Shadow varyantında 1.000 USDT | 60 dakika; `completed/success` | Kod `1804883`; Binance+OKX preflight PASS. 9 giriş/9 kapanış, açık 0, brüt +0,1027, ücret 3,1505, net **−3,0478 USDT**, PF 0,26. 9/9 kapanış `FLASH CRASH SİGORTASI`; doğal trailing/order-flow kohortu yok. |
| [40095304624](https://github.com/omeracar56/kripto-bot/actions/runs/40095304624) | PDF v2 + `pdf-confluence`; 1.000 USDT, 50 marj/10x | 120 dakika; `in_progress` | Kod `a5b8d0e`; profil çözümü, iki-borsa preflight ve 120 dakika/v2 güvenlik assertleri PASS. Nihai sonuç bekleniyor. |

### B. Yardımcı ve ara kanıtlar — ana üçlüye karıştırılmaz

- **40065026239:** 100.000 USDT, 1 saat, çapraz kurtarma kapalı; 78 giriş, 4 kapanış,
  74 açık pozisyon. Nakit kasa +0,25 USDT görünse de açık K/Z olmadan net özsermaye sonucu
  çıkarılamaz. OKX-only. Rapor: `analysis/run_40065026239/GENEL_ANALIZ.md`.
- **40090692312 Shadow özeti:** `flow-confidence` 0/9 kabul (9 ret), `technical-harmony`
  8/9 kabul (1 ret), diğer dört varyant 9/9 kabul. Flow varyantı işlem açmadığı için
  performans kanıtı değildir; technical-harmony bu küçük kesitte baseline'dan daha kötü
  −3,33 USDT verdi. Ayrıntı: `analysis/run_40090692312/shadow-report.md` ve `shadow-review.md`.
- **40088524013:** 100.000 USDT, 60 dakika planlanan Shadow run'ı; kullanıcı isteğiyle erken
  durduruldu. 6 giriş/6 kapanış, brüt +0,47, ücret 2,0999, net **−1,62 USDT**; altısı da
  flash-crash sigortası. Nihai Shadow dosyası yok. Rapor:
  `analysis/run_40088524013/20-dakika-inceleme.md`.
- **40072602176 / 40073001452:** OKX-only erken bağlantı/test kanıtları; çift-borsa sonucu sayılmaz.
- **40074826206 / 40074944318 / 40077659706:** bağlantı/preflight düzeltmeleri ve başarısız
  başlangıç kanıtları; performans kohortu değildir.
- **40076764827 / 40077601451:** eski self-hosted/concurrency kuyrukları; tamamlanmış paper
  performansı olarak kullanılmaz.

## 4. Kullanıcının üç-deneme değerlendirme çerçevesi

Kullanıcının 2026-10-24 notu: ilk 100.000 USDT denemesi çapraz kurtarma nedeniyle kötü,
iki saatlik ikinci deneme genel olarak iyi ama sorunlu, 1.000 USDT üçüncü deneme ise yeterli
işlem ve kazanç üretmedi. Bu not araştırma çerçevesidir; üçüncü run için nihai sayılar artifact
ile doğrulanır, ilk run'da duplicate-close etkisi çapraz kurtarmadan ayrı tutulur.

## 5. Ana üçlüden önceki kritik bulgular

### 4.1 İlk 100.000 USDT denemesi

- En büyük teknik sorun yalnız strateji değil, **kapama yarışı ve mükerrer paper muhasebesiydi**.
- Çapraz kurtarma 119 primary pozisyonda **−75,67 USDT brüt**, yaklaşık ücret sonrası
  **−117,32 USDT** ile en zayıf modüldü. Artı bacak tek başına okunmamalı; iki bacak birlikte
  değerlendirilmelidir.
- Order-flow/CVD kâr çıkışı 7/7 pozitif, +49,29 USDT brüt; fakat IRYS tek başına +29,69 USDT
  ve örneklem küçüktür. Bu giriş indikatörü başarısı değil, çıkış modülü gözlemidir.
- RSI/MACD/ADX/MA/Supertrend/MTF/ML için eski run'da pozisyon bazlı giriş snapshot'ı yoktu;
  kazanan/kaybeden indikatör sıralaması yapılmadı.

### 4.2 İki saatlik kontrollü deneme

- Planlı closeout ve işlem bazlı maliyet muhasebesi çalıştı; 85/85 UUID, açık 0, maliyet
  özdeşliği doğrulandı.
- Genel net +43,31 USDT olmakla birlikte 55 erken/süre-sonu kapanışı performans kohortundan
  ayrıldı. Bot kohortundaki +95,60 USDT ile genel kasa sonucu birbirinin yerine kullanılmaz.
- Order-flow kâr-koşusu çıkışları 20 işlemde +98,01 USDT net; trailing 10 işlemde −2,41 USDT
  net. İki ORDER/USDT işlemi bot netinin yaklaşık %50,3'üydü; yoğunlaşma riski var.
- Kazananlar 19 TREND + 3 BREAKOUT; kaybedenler 5 TREND + 2 RANGE + 1 BREAKOUT.
  Karşıt teknik bileşen 9/22 kazanan ve 7/8 kaybedende görüldü; tek başına bir indikatörü
  suçlamak için yeterli değil.
- 30/30 giriş `raw_signal=BEKLE` iken para-akışı tetikiydi. Taker/CVD büyüklüğü tek başına
  kazananı ayırmadı; veri kapsamı, teknik uyum ve maliyet sonrası çıkış birlikte incelenmeli.

### 4.3 Erken 20 dakikalık kesit

- Altı giriş de `BEKLE` + para-akışı tetikiydi; 3. dakika civarında JCT/USDT %8,06 şok sonrası
  6 pozisyon toplu kapandı ve bot kilitlendi.
- İki sembolde defter yok, birinde 62 saniye bayat defter, birinde yalnız 2 trade vardı.
  Bu, Flow Confidence/Data Readiness varyantının ölçülmesini motive etti.
- Bu kesitten normal çıkış PF'si, Net Exit, kaçırılan kazanan veya MFE/MAE sonucu çıkarılmadı.

## 6. Commit kilometre taşları

- `4090fcf`, `fc29556`, `76fdfb7`, `f57684f`, `d669361`: erken paper/rapor paketleri.
- `1d7099b`: ticker bid/ask fallback düzeltmesi; `868ef29`: varsayılanları geri yükleme.
- `805a40d`, `8b95ad3`: kohort raporlayıcı ve maskeli kanıtlar.
- `bec3b86`: ana Shadow Lab paketi.
- `69c467a`: süreden bağımsız iki-borsa zorunluluğu.
- `6d0b281`: 60 dakikalık Shadow run isteği.
- `5c7d4c4`: nonfinite Shadow JSON temizliği.
- `d70dfd4`: eşleştirilmiş kohort incelemesi ve baseline trade kaydı.
- `3e004ae`: Executor observer entegrasyon testi, 104 test ve otomatik inceleme.
- `d00a936`: erken durdurma kontrol isteği.
- `fe8b1a1`: 40088524013 maskeli log/preflight kanıtı.
- `1804883`: partial checkpoint, flash-crash idempotansiyonu, 1.000 USDT profili,
  20 dakikalık rapor ve 105 test güncellemesi.
- `d824b72`: bağlantı kanıtı kaydı.

Tam commit listesi Git history'de; bu dosya özet indeksidir.

## 7. Sonraki araştırma sırası

1. PDF v2 teknik paketini ve `controlled-v2-1000-no-cross-rescue` profilini GitHub'a kaydet;
   120 dakikalık 1.000 USDT Binance+OKX paper run'ını başlat ve run ID/artifact'ı arşivle.
2. Yeni fikirleri baseline'ı sessizce değiştirmeden izole Shadow varyantları olarak ölç.
3. Öncelik: giriş veri kalitesi, teknik/order-flow uyumu, ücret sonrası minimum beklenen
   avantaj, doğal çıkışların kalitesi ve portföy/yön yoğunlaşması.
4. İşlem sayısını artırmak için eşiği körlemesine düşürme; kaçırılan kazanan ve elenen zarar
   birlikte raporlanmadan kabul/ret kuralı seçme.
5. Çapraz kurtarma ancak aynı hataya karşı korumalı motorla, ayrı ve kontrollü A/B ölçümüyle
   yeniden değerlendirilebilir; mevcut kontrollü baseline'da kapalı.
6. Canlı kullanım kararı için çoklu dönem, yeterli bağımsız örnek, walk-forward/OOS ve
   maliyet/funding/kayma dayanıklılığı gerekir.

## 8. Dosya ve komut indeksi

- Üç-deneme genel raporu: `analysis/UC_DENEME_GENEL_ANALIZ.md` (nihai üç-run artifact'larıyla güncellendi).
- Ana raporlar: `analysis/run_39969507314/`, `analysis/run_40077757773/`,
  `analysis/run_40090692312/`.
- Erken kesit: `analysis/run_40088524013/20-dakika-inceleme.md` ve `.json`.
- Test: `PYTHONPATH=. .venv/bin/pytest -q tests`
- Bağımsız v7: `PYTHONPATH=. .venv/bin/python test_bot_v7.py`
- Shadow inceleme: `PYTHONPATH=. .venv/bin/python -m src.shadow_review <shadow.json> --output-prefix <prefix>`
- Bu dalda PR #1 açık; kullanıcı istemeden merge edilmez.

**Gizlilik:** Telegram tokenı, chat ID, runner registration token, API secret veya canlı emir
kimlik bilgisi bu hafızaya ve arşive yazılmaz.
