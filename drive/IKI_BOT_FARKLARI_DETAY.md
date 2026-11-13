# 🔍 İKİ BOT ARASINDAKİ FARKLAR — Detaylı Mühendislik Karşılaştırması

**Bot 1:** `ACARBOT56 v3.1` — Canlı çalışan Tüm-Futures motoru (`turbo_engine.py` + `dashboard.py`)
**Bot 2:** `ACARBOT OMEGA v1.0` — Sıfırdan inşa edilen kurumsal motor (`acarbot_omega/` + `omega_bot.py`)
Tarih: 2026-11-13 · Branch: `arena/3904724a-acarbot56`

---

## 0. Tek Cümlelik Özet

> **Bot 1 = hız ve kapsama odaklı "avcı".** Tek dosyada, saliselik hacim şokunu yakalar, sınırsız pozisyon açar, otonom kâr alır.
> **Bot 2 = muhasebe ve hayatta kalma odaklı "kurumsal motor".** Kontrat matematiği, sürtünme maliyeti, likidasyon güvenliği ve çökme-korumalı defterle aynı sinyali *kanıtlanabilir* biçimde işler.

---

## 1. Mimari ve Kod Yapısı

| Konu | Bot 1 (`ACARBOT56 v3.1`) | Bot 2 (`ACARBOT OMEGA v1.0`) |
|---|---|---|
| Yapı | Monolitik: `turbo_engine.py` (~1.000 satır) + `dashboard.py` (tek dosya HTML/JS terminal) | 9 bağımsız modül: `config`, `contracts`, `microstructure`, `ai_council`, `profit_engine`, `ledger`, `backtest_intrabar`, `engine`, `__init__` |
| Bağımlılık | Tarayıcı terminali + aiohttp + opsiyonel ccxt | Sadece stdlib + aiohttp (CCXT yalnız canlı emirde) |
| Test | `tests/test_all_bots.py` içinde turbo motoru testleri | `tests/test_omega_bot.py` — 8 ayrı test (kontrat, stop çözücü, veto, marjin, defter, backtest) |
| Durum saklama | Bellek içi (`deque`), süreç ölünce sıfırlanır | SQLite **WAL + `PENDING → COMMIT`** atomik defter, yeniden başlatmada kaldığı yerden |
| Tek komut doğrulama | `pytest` | `python omega_bot.py --self-test` → 1.260 kontrat, ~110 ms, `ledger_integrity_ok=true` |

---

## 2. Kontrat Matematiği — **en büyük yapısal fark**

| Konu | Bot 1 | Bot 2 |
|---|---|---|
| Lineer (`USDT`/`USDC`) | ✅ | ✅ `Decimal` ile `lot_step` / `tick_size` kuantizasyonu |
| **Ters (Inverse) kontrat** | ⚠️ `baseVol × px` yaklaşımı; COIN-M'de kontrat adedi ile USD büyüklük karışabiliyor | ✅ `face` değeri (BTC = $100, altcoin = $10), `qty = notional / face` |
| Inverse PnL formülü | Yaklaşık | ✅ **Kesin**: `side × (1 − entry/exit) × notional` |
| Aynalama hatası koruması | `dashboard.py` içinde `s.includes('USD_')` filtresi (JS tarafı) | ✅ `normalize_exchange_and_symbol()` — sunucu tarafı, her veri yolunda zorunlu |
| Vade/teslimat kontratları | Sadece sembol olarak izlenir | ✅ `is_delivery`, `delivery_code` ayrıştırılır (`_261225` gibi) |

**Neden önemli:** COIN-M (inverse) bir kontratta yanlış miktar = yanlış teminat = yanlış `-$20` stop. Bot 1'de bu risk kısmen açık, Bot 2'de `Decimal` ile kapatıldı.

---

## 3. `-$20` Zarar Kes — aynı hedef, farklı kesinlik

| Konu | Bot 1 | Bot 2 |
|---|---|---|
| Yöntem | `notional × stop_pct` + tahmini komisyon payı | **Kapalı form çözücü**: `bütçe = 20 − giriş_kom − çıkış_kom − çıkış_kayma`, sonra lineer/inverse için fiyata geri çözülür |
| Komisyon + kayma | Kısmen dahil | ✅ Giriş, çıkış, spread, kayma, fonlama rezervi ayrı ayrı modellenir |
| Doğrulama | Canlı sonuçlara bakılır | ✅ Testte 4 segment × 2 yön = 8 senaryoda net zararın `[-20.15, -19.70]` aralığında kaldığı **kanıtlanır** |
| Likidasyon tamponu | Kontrol edilir (yaklaşık) | ✅ `verify_stop_before_liquidation()` — stop, tahmini likidasyondan en az `%1.5` uzakta değilse giriş reddedilir |
| Sert tavan | `-$20`'da kapatır | ✅ Aynı + aşım durumunda `max(net, -20)` ile **muhasebe tavanı** uygulanır |

---

## 4. Giriş Mantığı — "hacim patlaması/çöküşü"nün iki yorumu

| Konu | Bot 1 | Bot 2 |
|---|---|---|
| Tetik | Hacim hızı çarpanı + fiyat ivmesi + alıcı/satıcı baskısı | Aynı üçlü **+ 60 saniyelik fitil konumu + Choppiness (testere) filtresi + VWAP kopma limiti** |
| Hacim çöküşü | Zirve sonrası hacim kuruması + ters dönüş | Aynı + `peak_burst_move_60s` hafızası (tükenişin yönünü unutmaz) |
| **Maliyet kapısı** | ❌ Yok (her sinyal değerlendirilir) | ✅ **`Edge-vs-Cost ≥ 2.4x`** — beklenen brüt hareket, gidiş-dönüş sürtünmesinin 2.4 katı değilse giriş **kesin veto** |
| Tuzak filtresi | Fitil tuzağı (temel) | ✅ 60 sn tepe/dip üzerinden `BULL_TRAP` / `BEAR_TRAP` vetosu |
| Mükerrer giriş | Sembol bazlı | ✅ Sembol + **aynı saniyede aynı baz coin** (`SOLUSDT` + `SOLUSDC` + `SOL-USDT-SWAP`) tekilleştirme |
| Karar verici | Tek skor | ✅ **20 denetçili konsey**, 3 tur, üye bazlı sert veto + onay skoru eşiği |

**Kritik fark:** Bot 1 "gördüğü her şoku" işler; Bot 2 "işlemeye değer şoku" işler. 90 günlük arşiv raporundaki ders: zararın **%30,4'ü** tam olarak bu sürtünme kapısının yokluğundan geliyordu.

---

## 5. Kâr Alma (TP) — 4 kademe vs 5 kademe

| Kademe | Bot 1 | Bot 2 |
|---|---|---|
| 1 | BE (başabaş) kilidi | BE + **komisyon üstü** `+$0.95` net kilit |
| 2 | Dinamik ivme iz sürme | ✅ **Akışa duyarlı iki mod**: akış bizden yanaysa %28 geri ver (trendi boğma), zayıfsa %18'e sıkılaştır |
| 3 | Parabolik kilit | ✅ Aynı, `+$22` üstünde zirvenin **%86'sı** kilitli |
| 4 | Hacim tükenişi çıkışı | ✅ Aynı (`AI_TUKENIS_DUVARI_KAR_AL`) |
| 5 | ❌ Yok | ✅ **`AI_ZAMAN_SONUMLENME_KAR_HASADI`** — 15 dk+ yatay sönümlenen kârlı işlemi hasat eder (Bot 1'in 1 saatte 38 pozisyon açıp **0 kapatma** sorununun çözümü) |

---

## 6. Veri Evreni

| Kaynak | Bot 1 (canlı ölçüm) | Bot 2 |
|---|---|---|
| Binance `USDⓈ-M` | 838 | ✅ aynı akış + normalize |
| Binance `COIN-M` | 836 | ✅ aynı akış + normalize |
| OKX `SWAP` | 546 | ✅ aynı akış |
| OKX `FUTURES/DELIVERY` | 293 | ✅ aynı akış |
| **Toplam (canlı)** | **2.513** | Aynı 4 segment, testte 1.260 sembollük mimari doğrulaması |
| Ayna/anti-block | `binance.com/.info/.me/.vision` | ✅ aynı liste + OKX `coinall.ltd` yedeği |
| Sahte veri | Yok | Yok |

> İki botun veri evreni **aynı**; fark, veriyi nasıl *yorumladığı*.

---

## 7. Yapay Zeka Katmanı

| Konu | Bot 1 | Bot 2 |
|---|---|---|
| Ana yapı | `MultiModelRouter` (GitHub Models, NVIDIA, DeepSeek, OpenAI, …) + `AdaptiveQuantAI` (Hurst, KER) | ✅ Aynı router'a **opsiyonel** bağlanır + **20 kantitatif denetçi** (deterministik, anahtarsız, her zaman çalışır) |
| Karar garantisi | LLM anahtarı yoksa sinyal yine üretilir | ✅ Anahtar yoksa `RULE_BASED_QUANT_20` modu devreye girer — **fail-open değil, mod etiketli** |
| Öğrenme | Yok (sabit parametre) | ✅ **Online lojistik SGD**: her kapanan işlemden sonra faktör ağırlıkları güncellenir |
| Denetlenebilirlik | Skor | ✅ `auditor_votes_for/20`, `veto_reasons[]`, `edge_to_cost_ratio` her işlemde kayıtlı |

---

## 8. Operasyonel Risk — en önemli itiraf

| Konu | Bot 1 (şu an canlı) | Bot 2 |
|---|---|---|
| Pozisyon limiti | `max_positions = 0` (sınırsız, **hiç kapı yok**) | `max_positions = 0` **ama** gerçek **serbest marjin kapısı** var |
| Pratik sonuç | 1 saatlik testte **186 açık pozisyon**, kullanılan teminat ≈ `$9.300` > kasa `$1.000` → **gerçek borsada mümkün değil** | `$1.000` kasa + `$50` teminat = aynı anda **~19 pozisyon**; fazlası `MARJIN_YETERSIZ_VETO` |
| Açık risk toplamı | `186 × $20 = $3.720` (kasanın 3.7 katı) | `19 × $20 = $380` (kasanın %38'i) — hayatta kalınabilir |
| Çökme davranışı | Süreç ölürse tüm durum kaybolur | ✅ SQLite defterden tam mutabakat (`verify_integrity`) |

> **Bu bir "sınır koyma" değil, gerçeği söyleme farkıdır.** Borsa, teminatı olmayan emri reddeder. Bot 1 bunu hesaba katmadığı için panelde ulaşılamaz bir portföy gösteriyor.

---

## 9. Backtest ve Doğrulama

| Konu | Bot 1 | Bot 2 |
|---|---|---|
| Backtest | Rejim bazlı walk-forward (`main.py --mode backtest`) | ✅ **Mum içi yol yürüyücüsü**: kötümser (`adverse_first`) ve iyimser (`favorable_first`) sınır ayrı ayrı |
| Stop/TP çakışması | Mumun kapanışına göre | ✅ Aynı mumda ikisi de görülürse **iki uç senaryo** raporlanır (iyimserliğe sığınılmaz) |
| Test sayısı | 14 (repo geneli) | ✅ 22 (repo geneli: 14 + 8 yeni) |
| CI | Var | ✅ Var + `omega_paper_test.yml` (1 saatlik gerçek veri seansı) |

---

## 10. Canlı Test Karnesi (13 Kasım 2026, 68.5% anı)

| Metrik | Bot 1 (`ACARBOT56 v3.1`) |
|---|---|
| Canlı sembol | 2.513 |
| Tick | 608.868 |
| Kasa | **$847,96** |
| Realize | **+$112,34** |
| Açık (unrealized) | **−$264,38** |
| Açık / kapanan | 186 / 68 |
| Kazanma oranı | %70,6 |
| Profit factor | 1,53 |

**Yorum:** Gerçekleşen işlemler **kârlı** (68 işlemde +$112 = işlem başına ~$1,65 net), ama açık pozisyonların toplamı kasayı aşağı çekiyor. Bu tam olarak **"çok pozisyon + her pozisyonda ayrı −$20 risk"** sorunudur — Bot 2'nin marjin kapısı bu deliliği engeller.
Bot 2'nin 1 saatlik testi ayrıca çalıştırılacak (run `43392581249`).

---

## 11. Hangisi Ne Zaman Kullanılmalı?

| Senaryo | Öneri |
|---|---|
| Canlı piyasayı **hissetmek**, sinyal keşfi, gözle takip | **Bot 1** (terminal + hız) |
| Gerçek para, gerçek borsa, uzun süre ayakta kalma | **Bot 2** (maliyet kapısı + marjin kapısı + atomik defter) |
| COIN-M / inverse / vadeli kontrat işlemleri | **Sadece Bot 2** (kesin kontrat matematiği) |
| Aylık zarar atfı, "neye para kaybettik" analizi | **Bot 2** (`edge_to_cost_ratio`, `veto_counts`, `closed_trades` tablosu) |
| Baseline / kıyaslama referansı | **Bot 1** (aynı veri, farklı karar) |

---

## 12. Bot 2'ye Bot 1'den Taşınan ve Taşınmayan Özellikler

**Taşındı:** tüm-futures ayna akışı (4 segment), saliselik hacim şoku/çöküşü tespiti, sınırsız pozisyon felsefesi, `$1.000` / `$50×10x` / `cross` kuralları, 4 kademeli otonom kâr motoru, `MultiModelRouter` entegrasyonu, 1 saatlik seans takibi.

**Bilinçli olarak taşınmadı:** terminalin ham açık-pozisyon sayısı (marjin kapısı ile sınırlandı), `baseVol × px` yaklaşımı (yerine `Decimal` kontrat matematiği), süreç-bellek durumu (yerine SQLite WAL).

---

## 13. Sıradaki Adım (bittikten sonra yapılacak analiz)

1 saatlik iki test bittiğinde **aynı metriklerle** karşılaştıracağız:

| Karşılaştırma | Neden |
|---|---|
| Kâr getiren işlemlerin `trigger_type` dağılımı | Hangi şok tipi gerçekten para kazandırıyor |
| `exit_reason` dağılımı (BE / trailing / tükeniş / zaman) | Hangi çıkış kuralı işe yarıyor |
| **Sürtünme oranı**: `Σ(komisyon+slippage) / Σ(brüt kâr)` | Gerçek maliyet yükü |
| `edge_to_cost_ratio` vs sonuç | Maliyet kapısı eşiği doğru mu (2.4x mi, 1.8x mi) |
| Maks. eşzamanlı açık risk / kasa | Hayatta kalma testi |
| Saatlik dilim bazında PnL | Belirli saatlerde mi kaybediyoruz |
