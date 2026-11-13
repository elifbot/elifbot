# ACARBOT v6.0 — AŞAMA 2: GELİŞTİRME PLANI

**Temel:** v5.5 (denetim düzeltmeleri uygulanmış v5.4)
**İlke:** mevcut çalışan kod korunur, üzerine inşa edilir. Sıfırdan
yeniden yazma YOK.

---

## 0. DÜRÜST ÇERÇEVE

Brief 6 fazlı bir program tarif ediyor. Bu **tek oturumluk iş değil**.
Gerçekçi büyüklük:

| Faz | Tahmini iş | Bu turda durumu |
|---|---|---|
| Faz 0 — Ölçüm dürüstlüğü | 6 kusur düzeltmesi | ✅ **YAPILDI (v5.5)** |
| Faz 1 — Örneklem altyapısı | 1 yıl × 30–50 sembol | ⬜ Başlanmadı |
| Faz 2 — Giriş kenarı araştırması | Yeni stratejiler + kalibrasyon | ⬜ Başlanmadı |
| Faz 3 — Risk motoru | Portföy/likidasyon/stres | ⬜ Kısmi temel var |
| Faz 4 — Emir motoru | Tick dolum, markout, testnet | ⬜ Kısmi temel var |
| Faz 5 — Adaptif/AI | Gölge model, kalibrasyon | ⬜ Yok |
| Faz 6 — Panel | Web arayüzü | ⬜ Yok (sıfırdan) |

**Sıra değişikliği önerisi:** Brief Faz 1'i "kârlı giriş sistemi" diye
adlandırıyor. Ama 6 sembol × 90 günde **hiçbir** yeni strateji
yeterli örnekleme ulaşamaz (1h'de 105 aday). Bu yüzden önce örneklem
altyapısı kurulmalı. Aksi hâlde yeni stratejiler de aynı
`YETERSIZ_ORNEKLEM` hükmünü alır ve iş boşa gider.

---

## FAZ 0 — ÖLÇÜM DÜRÜSTLÜĞÜ ✅ TAMAMLANDI (v5.5)

| Dosya | Değişiklik |
|---|---|
| `backtest/candidate_scan.py` | **YENİ** — portföyden bağımsız aday taraması |
| `backtest/robust_stats.py` | **YENİ** — küme tekilleştirme, gün küme bootstrap, Bonferroni, 4 durumlu hüküm |
| `tools/entry_edge.py` | `--legacy-probe`, `--cluster-bars`, `--min-n`, `--tests-m`, `--bootstrap`; `stopped_horizon()`; brüt/net ayrımı |
| `core/portfolio.py` | `configure_peak()`, `_track_peak()`, `peak_resets` |
| `core/config.py` | `drawdown_peak_mode`, `drawdown_peak_window_days` |
| `backtest/engine.py` | Tepe penceresi bağlantısı, `result.drawdown_peak` |
| `tests/test_v55_audit.py` | **YENİ** — 29 regresyon testi |

---

## FAZ 1 — ÖRNEKLEM ALTYAPISI (öncelik 1)

**Hedef:** 1 yıl × 30–50 likit sözleşme, gerçek borsa verisi.

| İş | Dosya | Kabul kriteri |
|---|---|---|
| 1.1 Uzun geçmiş indirici | `infra/market_data/` genişletme | 365 gün, kesintisiz, eksik mum raporu |
| 1.2 Eksik mum tespiti + tamamlama | `infra/feed.py` | Boşluk listesi, yeniden çekme, doğrulama |
| 1.3 Sembol evreni seçici | `core/symbols.py` genişletme | Likidite eşiğiyle 30–50 sözleşme |
| 1.4 Funding geçmişi indirici | `infra/exchanges/` | 8 saatlik funding, sembol bazlı arşiv |
| 1.5 Funding'i backtest'e bağla | `tools/validate_strategy.py` | ✅ v5.6'da YAPILDI: funding bir kez yüklenip tüm bloklara iletilir (veri dosyası yoksa durum raporlanır) |
| 1.6 Binance maliyet ölçümü | `tools/measure_costs.py` | binance: VARSAYIM → ÖLÇÜLDÜ |

**Not (v5.6.2):** 1.5 tamamlandı; kalan engel koda değil VERİYE bağlı —
tarihsel funding CSV'leri indirilmeden kapsama testi geçmez.

**Risk:** 1 yıl × 50 sembol × 5m ≈ 5,25 milyon mum. İndirme ve
depolama bütçesi gerekir. Önbellek formatı sıkıştırılmalı.
Bütçe (v5.6.2, çevrimdışı): `python -m tools.data_budget --symbols 50 --months 12 --intervals 5m`
→ 5.256.000 mum, ~52.560 istek, ~85 MB gzip (tahmin; varsayımlar çıktıda).

---

## FAZ 2 — GİRİŞ KENARI ARAŞTIRMASI (öncelik 2)

**Ön koşul:** Faz 1 bitmeden başlanmaz.

### 2.1 Strateji iskeleti

Mevcut `core/strategies_extra.py` ve `core/pipeline.py` genişletilir.
Yeni modüller **aynı arayüzü** uygular (`evaluate(ctx) -> Signal`):

| Strateji | Yeni dosya | Not |
|---|---|---|
| Trend devam | `core/strategies/trend_follow.py` | EMA/ADX/HH-HL; yön ve güç ayrı |
| Breakout + retest | `core/strategies/breakout_retest.py` | Gövde gücü + retest doğrulaması |
| Likidite süpürme | `core/strategies/liquidity_sweep.py` | `core/sweep_guard.py` temel alınır |
| SMC (OB/FVG/BOS/CHoCH) | `core/strategies/smart_money.py` | Ölçülebilir çıktı, çizim değil |
| VWAP/hacim profili | `core/strategies/vwap_volume.py` | POC/VAH/VAL |
| Momentum uyumsuzluk | `core/strategies/divergence.py` | RSI/MACD/CVD |

### 2.2 Her strateji için ZORUNLU test protokolü

```
1. Bağımsız tarama (candidate_scan) — portföy yok
2. Küme tekilleştirme + gün küme bootstrap
3. Stopsuz ufuk DEĞİL, 1R stoplu zaman stopu
4. Önceden yazılmış TEK birincil hipotez
5. Son %25 holdout — hiç dokunulmaz
6. Bonferroni: test edilen toplam hipotez sayısı
7. Hüküm: n≥300 ve GA alt >0 ve düzeltilmiş p<0.05
```

**Kabul edilmeyen:** "15 hipotezden biri p=0,03 verdi" → düzeltilmiş
p=0,45 → kenar değil.

### 2.3 Skor kalibrasyonu

`core/scoring.py` genişletilir:
- Dilim bazlı (70–79, 80–89, 90–100) gerçekleşen kazanma oranı
- Her dilimde ortalama R, maliyet sonrası beklenti, **n**
- Dilim monotonluğu testi
- **Kalibrasyon yalnız OOS veride** — in-sample kalibrasyon sızıntıdır

### 2.4 Rejim → strateji eşlemesi

`core/regime.py` zaten 9 rejim üretiyor. Eşleme tablosu **veriyle**
seçilir, elle atanmaz. Her rejim × strateji hücresi için ayrı n ve GA.

---

## FAZ 3 — RİSK MOTORU (öncelik 3)

| İş | Dosya | Kabul |
|---|---|---|
| 3.1 Sınırsız pozisyon + sıkı portföy tavanı | `core/risk.py`, `core/portfolio_risk.py` | `max_positions=0` iken Σrisk ≤ cap |
| 3.2 Likidasyon mesafesi giriş kontrolü | `core/risk.py` | Giriş öncesi mesafe ≥ eşik |
| 3.3 Haftalık/aylık zarar denetimi | `core/risk.py` | Günlükle aynı arayüz |
| 3.4 Volatiliteye bağlı boyut | `core/risk_scaling.py` | ATR sıçramasında boyut küçülür |
| 3.5 Dolumda gerçek risk yeniden hesabı | `exec/orders.py` | Kısmi dolumda risk güncellenir |
| 3.6 Sembol/borsa risk bütçesi | `core/portfolio_risk.py` | Ayrı sayaçlar |
| 3.7 Portföy stres testi | `backtest/` | Korelasyon şoku senaryosu |

**Uyarı:** 3.1 (sınırsız pozisyon) **en tehlikeli** maddedir.
3.2–3.7 bitmeden açılmamalı. Bugün `max_positions=6` bir güvenlik
özelliiğidir, keyfi kısıt değil.

---

## FAZ 4 — EMİR MOTORU (öncelik 4)

| İş | Dosya | Kabul |
|---|---|---|
| 4.1 Tick/aggTrade dolum modeli | `backtest/path.py` | 45 sn TTL tam çözülür |
| 4.2 Kuyruk pozisyonu tahmini | `backtest/fill_model.py` **YENİ** | Maker dolum olasılığı |
| 4.3 Markout analizi (1/5/15 dk) | `backtest/markout.py` **YENİ** | Dolum sonrası sürüklenme |
| 4.4 Order book derinliği | `infra/exchanges/` | Gerçek derinlik, varsayım değil |
| 4.5 WebSocket + yeniden senkron | `live/clients.py` | Kopma sonrası durum eşleme |
| 4.6 Testnet uçtan uca | `live/sync.py` | Emir/iptal/kısmi/stop/TP/kopma |

**4.6 kabul listesi (brief §13):** emir gönderme, iptal, kısmi dolum,
pozisyon açma/kapama, stop, TP, bağlantı kopması, yeniden bağlantı,
pozisyon senkronizasyonu. **Hepsi koşulacak ve kayda geçecek.**

---

## FAZ 5 — ADAPTİF / AI (öncelik 5)

**İlke:** gösteriş için değil, ölçülebilir tahmin için.

- Hedef değişken: dolum olasılığı, kısa ufuk yön, volatilite
- Eğitim/test **tarih** bazlı ayrılır (rastgele değil — sızıntı olur)
- Gölge mod: yeni model canlıda karar vermez, yalnız tahmin kaydedilir
- Terfi kriteri: gölge dönemde mevcut modeli OOS'ta yenmeli
- Tahmin "kesin kazanç olasılığı" olarak gösterilmez

**Ön koşul:** Faz 2'de kenar bulunmadan AI eklemek anlamsızdır.
Kenarsız sinyali ML ile kalibre etmek kenar üretmez.

---

## FAZ 6 — PANEL (öncelik 6)

Mevcut web arayüzü **yok**. Sıfırdan:
- Backend: mevcut `monitor/dashboard.py` veri toplayıcısı API'ye bağlanır
- Frontend: koyu tema, 20 ekran (brief §15)
- **Mod ayrımı görsel olarak net:** backtest / paper / testnet / canlı
- Canlı mod varsayılan **KAPALI**

---

## DEĞİŞMEYECEK İŞLEM KURALLARI (brief §2)

| Parametre | Değer | Mevcut durum |
|---|---|---|
| Başlangıç bakiye | 1.000 USDT | ✅ |
| İşlem marjı | 50 USDT | ⚠️ Doğrulanacak |
| Kaldıraç | 10x | ✅ |
| İşlem başı planlanan risk | 25 USDT | ✅ `target_net_risk` |
| Emir tipi | Maker öncelikli | ✅ `post_only` |
| Pozisyon adedi | Sabit üst sınır yok | ⚠️ Şu an 6 — Faz 3.1 |
| Yön | Long + Short | ✅ |
| Borsa | Binance USD-M | ⚠️ Adaptör var, maliyet ölçülmedi |

**25 USDT garantisi:** brief doğru bir uyarı yapıyor — boşluk, ani
hareket ve kesintide gerçekleşen zarar 25 USDT'yi **aşabilir**.
Bu yüzden borsada koruyucu stop + acil durdurma şart. Kodda
`place_protective_stop` var; **ancak testnet'te doğrulanmadı.**

---

## TESLİMAT TAKVİMİ (gerçekçi)

Bu turda teslim edilen: **v5.5** (Faz 0) + bu iki belge.

Sonraki turlarda sırayla Faz 1 → Faz 6. Her faz sonunda:
- Test çıktısı repoya
- Başarısız testler **gizlenmeden** rapora
- ZIP + manifest + sha256

**v6.0 etiketi ancak Faz 1–4 kabul kriterleri geçtiğinde verilir.**
Bugün v6.0 diye paketlemek, yapılmamış işi yapılmış göstermek olur.
