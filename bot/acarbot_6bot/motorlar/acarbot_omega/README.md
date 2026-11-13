# 🚀 ACARBOT OMEGA v1.0 (`acarbot_omega/` & `omega_bot.py`)

**ACARBOT OMEGA v1.0**, mevcut çalışan `turbo_engine.py` botundan **tamamen bağımsız (`BUNUN DIŞINDA`)** olarak sıfırdan, en ince ayrıntısına kadar inşa edilmiş kurumsal vadeli işlemler (All-Futures) mimarisidir.

Gmail ve Google Drive arşivindeki **16 bot paketinin** ve **90 günlük kantitatif zarar analizi raporlarının** (`ZARAR_ANALIZI_v5.5.md`, `ANALIZ_KAPI_ATFI.md`, `ACARBOT_V20_1SAATLIK_TEST_RAPORU.md`) tüm mühendislik derslerini `turbo_engine.py`'nin en güçlü canlı özellikleriyle tek bir çatı altında birleştirir.

---

## Neden Daha Üstün? (10 Temel Mühendislik Farkı)

1. **Kesin `Decimal` Kontrat Matematiği (`contracts.py` — *ACARBOT-V10 + APEX mirası*):**
   - **4 Vadeli İşlem Segmentinin tamamını** (`Binance USDⓈ-M`, `Binance COIN-M`, `OKX SWAP`, `OKX FUTURES` -> **1.200+ kontrat**) hem **Linear** (`USDT`/`USDC`) hem **Inverse** (`BTC=$100`, `Altcoin=$10` kontrat büyüklüğü) olarak kayan nokta hatası olmadan çözer.
   - Yanlış yönlendirilmiş (`CNAME`) akışlardan gelen pariteleri (`binance_coinm` içindeki `USDT` kontratı gibi) sunucu tarafında otomatik algılayıp doğru segmente (`BINANCE_USDM`) sınıflandırır.
2. **Komisyon + Çıkış Ücreti + Kayma Dahil Kesin `-$20.00` Net Stop Çözücü (`solve_exact_net_stop_price` — *PHOENIX V4 mirası*):**
   - Stop fiyatını ham fiyata göre değil; **giriş komisyonu + çıkış komisyonu + stop kayma (slippage) rezervi** düşüldükten sonra bile toplam net kayıp **asla `-$20.00`'ı aşmayacak** şekilde `tick_size` hassasiyetiyle çözer ve tahmini likidasyon fiyatından en az `%1.5` uzakta olduğunu matematiksel olarak doğrular.
3. **`Edge-vs-Cost` Gerçek Sürtünme Kapısı (`CostModel` — *v5.5 Zarar Analizi Raporu Dersi*):**
   - Geçmiş 90 günlük kayıpların %30,4'üne yol açan düşük marjlı mikro-işlemleri engellemek için; beklenen brüt hareket toplam gidiş-dönüş maliyetinin (`komisyon + spread + giriş/çıkış kayması + fonlama rezervi`) en az **`2.4x` katı** değilse giriş **kesin veto (`EDGE_VS_COST_VETO`)** edilir.
4. **Saliselik Mikro-Tape + 10-Oylu Konfluans + Adil Türev Skoru (`microstructure.py`):**
   - O(1) bellekli `OmegaSymbolTape`, saliselik **Hacim Patlaması (`Volume Explosion`)** ve **Hacim Çöküşü (`Volume Collapse`)** sinyallerini 1 dakikalık `VWAP`, `EMA9/21`, `RSI(14)`, `ATR%`, `OBV`, `Choppiness Index` (testere filtresi) ile birleştirir.
   - Opsiyonel türev verileri (`OI`, `Funding`, `Spread`, `Book Imbalance`) eksik olduğunda `0` sayıp sinyali sulandırmaz; ağırlığını paydadan düşerek adil skor üretir.
5. **20-Denetçili Yapay Zeka & Kantitatif Çapraz Teftiş Konseyi + Online SGD Öğrenme (`ai_council.py` — *AI-OmniStudio + AI-Hub + MultiModelRouter mirası*):**
   - 20 bağımsız kantitatif denetçi (Maliyet, CVD Akışı, Fitil Tuzağı, Testere, VWAP Kopması, Türev Dengesi ve **Online Lojistik SGD Öğrenici**) 3 turda oylama yapar; her kapanan işlemden gerçek zamanlı öğrenir (`learn_from_closed_trade`).
6. **5 Kademeli Otonom AI Kâr Motoru (`profit_engine.py`):**
   - `Kademe 1`: Başabaş + komisyon üstü kâr kilidi (`+$0.95` net)
   - `Kademe 2`: Akış bizden yanayken geniş (`%28`), akış zayıfladığında sıkı (`%18`) dinamik AI trailing
   - `Kademe 3`: Parabolik rallilerde (`+$22+`) zirvenin `%86`'sını kilitleyen mandal
   - `Kademe 4`: Karşı yönde hacim ve CVD duvarı çarptığında tepede anında çıkış (`AI_TUKENIS_DUVARI_KAR_AL`)
   - `Kademe 5`: 15dk+ yatay sönümlenen kârlı işlemleri hasat eden zaman kilidi (*ACARBOT V20 1 saatlik rapor dersi*)
7. **Çökme-Korumalı İki Aşamalı SQLite WAL Defteri (`ledger.py` — *KRIPTO-BOT v9.5.3 mirası*):**
   - Her açılış ve kapanışı `PENDING -> COMMITTED` olarak SQLite WAL modunda kaydeder; `verify_integrity()` ile `Başlangıç Kasası ($1,000) + ∑(Kapanan Net PnL) == Kayıtlı Kasa` eşitliğini kuruşu kuruşuna kanıtlar.
8. **Aynı Saniye Baz-Varlık Tekilleştirmesi + Sınırsız Pozisyon (`max_positions = 0`):**
   - Yapay bir adet sınırı **yoktur**: sırayla sınırsız işlem açılır. Aynı anda taşınabilecek pozisyon sayısını `max_positions` değil, **borsanın gerçek serbest marjin (`free margin`) yeterliliği** belirler (`$1,000` kasa + `$50` teminat = aynı anda ~19 pozisyon); serbest teminat bitince emir borsada reddedileceği için motor bunu `MARJIN_YETERSIZ_VETO` ile önden engeller.
   - Aynı saniyede aynı baz coine (`SOLUSDT` + `SOLUSDC` + `SOL-USDT-SWAP`) mükerrer üçlü giriş yapılmasını da engeller.
9. **Gerçek Mum İçi Yol (`IntrabarBacktester` — *ACARBOT v6.2 mirası*):**
   - Hem kötümser (`adverse_first`) hem iyimser (`favorable_first`) mum içi yol sınırlarını ve çok katmanlı `Walk-Forward` doğrulamasını raporlar.

---

## Hızlı Çalıştırma

```bash
# 1.260 kontratlık tam mimari, hız ve SQLite defter bütünlük testi
python omega_bot.py --self-test

# %100 gerçek borsa verisiyle 1 saatlik (3600 sn) Paper mod çalıştırma
python omega_bot.py --mode paper --preset balanced --duration 3600

# SQLite WAL atomik işlem defteri bütünlük denetimi
python omega_bot.py --mode audit-ledger --db omega_ledger.sqlite3

# Gerçek Çapraz Marjin (CROSS, $50×10x) canlı emir modu (emniyet kilidi zorunlu)
I_UNDERSTAND_RISK=YES python omega_bot.py --mode live --preset balanced
```
