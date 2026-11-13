# 3 PDF İndikatör & Veri Mimarisi — Tam Karşılaştırma ve Hazırlık Paketi

Bu doküman, paylaşılan üç referans PDF'in tüm maddelerini botumuzun mevcut mimarisiyle birebir karşılaştırır ve **eksik kalan tüm katmanlar için hazırlanan tak-çalıştır modülleri** (`src/pdf_v3_prep.py` + `src/derivatives_intel.py`) özetler:

1. **PDF-1:** *Kripto Futures Bot İndikatör Mimarisi* (6 Katmanlı Mimari + Risk Motoru)
2. **PDF-2:** *Kripto Futures Botları İçin Birleşik İndikatör Listesi* (Trend, Momentum, Volatilite/Rejim, Hacim/Emir Akışı, Türev, Piyasa Yapısı, Çıkış/ML)
3. **PDF-3:** *Profesyonel Kripto Futures Botu: Veriler, İndikatörler ve Kaynaklar* (15 Bölümlük Uçtan Uca Profesyonel Yığın)

> **Not:** Çalışmakta olan 1 saatlik canlı veri testi (`run 40174169361`) bozulmasın diye aktif karar motoruna (`src/main.py`, `src/indicators.py`, `src/executor.py`, `config.yaml`) dokunulmamıştır. Tüm yeni hazırlıklar izole modüller halinde yazılmış ve birim testlerle (`tests/test_pdf_v3_prep.py`) doğrulanmıştır.

---

## 1. Kategori Bazlı Tam Karşılaştırma Matrisi

### A. Trend & Hareketli Ortalamalar
| PDF Maddesi | Durum | Bottaki Konumu |
|---|---|---|
| EMA (9 / 20 / 21 / 50 / 200) & MTF 5m/15m/1h/4h | **Baseline Aktif** | `src/indicators.py` |
| SMA, Supertrend, Donchian Channel | **Baseline Aktif** | `src/indicators.py` |
| Session / Weekly / Cumulative / Anchored VWAP | **Baseline Aktif** | `src/indicators.py` |
| KAMA, HMA, DEMA, TEMA, TRIX | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| Ichimoku Cloud, Parabolic SAR, Alligator, LinReg Channel | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| ADX (+DI / -DI) | **Baseline Aktif** | `src/indicators.py` |
| ADXR, DX, Vortex (`VI+` / `VI-`) | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| **T3 (Tillson), FRAMA, VIDYA, JMA (Jurik uyumlu), Wilder RMA** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **EMA Ribbon (8/13/21/34/55/89 dizilim + sıkışma skoru)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |

### B. Momentum, Osilatörler & Uyumsuzluklar
| PDF Maddesi | Durum | Bottaki Konumu |
|---|---|---|
| RSI (14), StochRSI, MACD + Histogram, CCI, MFI, Williams %R | **Baseline Aktif** | `src/indicators.py` |
| WaveTrend (`WT1`/`WT2`), Fisher Transform, TSI, ROC, Awesome Osc | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| Otomatik RSI & MACD Regular/Hidden Divergence | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| **Klasik Fast / Slow Stochastic (`%K`, `%D`)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **EMA-Yumuşatılmış RSI / MFI / CCI (Gürültü azaltıcı türevler)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |

### C. Volatilite, Rejim Filtresi & Çıkış Mekanizmaları
| PDF Maddesi | Durum | Bottaki Konumu |
|---|---|---|
| ATR, Bollinger Bands + Width, Keltner Channel + Squeeze | **Baseline Aktif** | `src/indicators.py` |
| Sabit Zarar Kes (`$40`), Trailing / Breakeven, Likidasyon Tamponu | **Baseline Aktif** | `src/risk.py`, `src/executor.py` |
| Choppiness Index (CHOP), Hurst Exponent (`H`) | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| Realized Vol, Parkinson Vol, Garman–Klass Vol, Bollinger `%B` | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| Chandelier Exit (`Long` / `Short`) | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| **Elder SafeZone Stop (`Long` / `Short` gürültü-dirençli stop)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **Minimal ROI (Zamana bağlı azalan kâr-al eşiği — sadece Shadow)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **İstatistiksel Rejim Sınıflandırıcı (K-Means + Markov geçiş olasılığı)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |

### D. Hacim, Emir Defteri (L2) & Mikro-Yapı (Order Flow)
| PDF Maddesi | Durum | Bottaki Konumu |
|---|---|---|
| OBV, Hacim Z-Skoru / RVOL, VPVR (`POC`, `VAH`, `VAL`) | **Baseline Aktif** | `src/indicators.py` |
| Gerçek Taker CVD + Eğim + Uyumsuzluk | **Baseline Aktif** | `src/moneyflow.py` |
| 20 Kademe L2 OBI, Alış/Satış Duvarları, Emilim (Absorption) | **Baseline Aktif** | `src/moneyflow.py` |
| Balina İşlem Akışı (`$100K+` agresif emirler) | **Baseline Aktif** | `src/moneyflow.py` |
| CMF (Chaikin Money Flow), Accumulation/Distribution (A/D) | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| **Volume Profile HVN (Yüksek Hacim Düğümü) & LVN (Boşluk/Vakum)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **Spoofing (İptal edilen büyük duvar) & Iceberg Aday Takipçisi** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |

### E. Futures Türev & Opsiyon Verileri (Kriptoya Özgü Katman)
| PDF Maddesi | Durum | Bottaki Konumu |
|---|---|---|
| Funding Rate & Funding Extreme Filtresi | **Baseline Aktif** | `src/moneyflow.py`, `src/exchanges.py` |
| Open Interest (OI) + Fiyat × OI 4'lü Yorum Matrisi | **Baseline Aktif** | `src/moneyflow.py` |
| Gerçek Zamanlı Likidasyon Akışı & Long/Short Squeeze Tespiti | **Baseline Aktif** | `src/moneyflow.py` |
| **Basis & Mark–Index Fiyat Primi (`%`) (Binance + OKX)** | **PDF v3 Hazırlandı** | `src/derivatives_intel.py` |
| **Cross-Exchange Funding Farkı (`bps`) & Mark Fiyat Spread (`%`)** | **PDF v3 Hazırlandı** | `src/derivatives_intel.py` |
| **Global Long/Short Hesap Oranı & Top Trader L/S Pozisyon Oranı** | **PDF v3 Hazırlandı** | `src/derivatives_intel.py` |
| **Borsa Periyodik Taker Buy/Sell Oranı (Binance + OKX)** | **PDF v3 Hazırlandı** | `src/derivatives_intel.py` |
| **Deribit Opsiyon `DVOL` (Beklenen Volatilite) & `Put/Call` Oranı** | **PDF v3 Hazırlandı** | `src/derivatives_intel.py` |
| **Tahmini Kaldıraç (`10x/25x/50x`) Likidasyon Kümesi Haritası** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |

### F. Piyasa Yapısı (SMC / Price Action), Çapraz Varlık, Haber & Doğrulama
| PDF Maddesi | Durum | Bottaki Konumu |
|---|---|---|
| Swing High/Low, BOS, CHoCH, Liquidity Sweep, FVG, Order Block | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| Klasik Pivotlar (`P/R1/R2/S1/S2`), Fibonacci (`38.2/50/61.8`), Pin/Engulfing | **PDF v2 / Shadow Aktif** | `src/pdf_indicators.py` |
| RSS + CryptoPanic Haber Akışı + Fear & Greed Endeksi | **Baseline Aktif** | `src/news.py` |
| Walk-Forward + Embargo ML (`HistGB` / `XGBoost` / `LightGBM`) | **Baseline Aktif** | `src/ml_predictor.py` |
| Komisyon + Kayma (Slippage) + Funding Düşülmüş Net Muhasebe | **Baseline Aktif** | `src/executor.py`, `paper-lab/` |
| **BTC Rejim Filtresi + Altcoin–BTC Korelasyonu, Beta ve Göreli Güç** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **Kripto-VADER Duyarlılık Skoru + Contrarian (Tersine) Aşırılık Sinyali** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **Makro & Token Kilit Açılımı Takvim Kalkanı (`FOMC/CPI/NFP` dondurma)** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **Sharpe, Sortino, Calmar, Profit Factor, Expectancy & Monte Carlo DD** | **PDF v3 Hazırlandı** | `src/pdf_v3_prep.py` |
| **On-Chain (`MVRV/SOPR/Netflow`) & Kurumsal (`DXY/US10Y/ETF`) Şeması** | **Şema Hazır (Fail-Safe)** | `src/derivatives_intel.py` |

---

## 2. 1 Saatlik Test Sonrası Önerilen Entegrasyon Sırası

 PDF-1 ve PDF-3'teki *"Her indikatörü aynı anda karara bağlamak sinyal çelişkisi ve overfitting yaratır; her katmandan 1-2 temsilci seçin"* uyarısına sadık kalarak, 1 saatlik test (`run 40174169361`) tamamlanıp sonuçları incelendikten sonra şu sırayla devreye alınması planlanmıştır:

1. **Adım 1 — Türev & BTC Rejim Gölge Varyantı (`deriv-btc-guard`):**
   - `DerivativesIntelEngine` üzerinden **Top Trader vs. Perakende L/S ayrışması**, **Basis aşırı primi** ve `btc_regime_and_correlation` ile BTC ters rejim filtresini Shadow Lab'a 8. varyant olarak bağlamak.
2. **Adım 2 — İstatistiksel Rejim + HVN/LVN + SafeZone Çıkış Deneyi (`regime-safezone`):**
   - `classify_statistical_regime` (`YÜKSEK_VOL_ŞOK` durumunda giriş freni), `volume_profile_nodes` (`LVN` boşluk bölgesinde hızlı hedef, `HVN` önünde temkin) ve `elder_safezone_stop` iz süren çıkışını test etmek.
3. **Adım 3 — Makro Takvim Kalkanı & Raporlama Metrikleri:**
   - `MacroCalendarGuard` ile yüksek etkili ABD verisi (`CPI`, `FOMC`, `NFP`) pencerelerinde otomatik giriş dondurma ve oturum sonu raporuna `advanced_performance_metrics` + `monte_carlo_drawdown` tablolarını eklemek.
