# ACARBOT v6.0 — DEĞİŞİKLİK BELGESİ

**Durum:** v6.0 **tamamlanmadı**. Bu turda **Faz 0** (ölçüm
dürüstlüğü) bitirildi ve **v5.5** olarak teslim edildi.

Bu belge, v6.0 programının neresinde olunduğunu ve neyin
yapılıp neyin yapılmadığını tek yerde toplar.

---

## 1. NEDEN v6.0 DEĞİL, v5.5?

Brief §19'da 18 kabul kriteri var. Bugünkü durum:

- **8'i tam karşılanıyor**
- **6'sı kısmi** (kod var, gerçek ortamda doğrulanmadı)
- **4'ü karşılanmıyor** (testnet, funding, sınırsız pozisyon, örneklem)

Bu hâlde paketi "v6.0" diye etiketlemek, brief'in kendi kuralını
ihlal ederdi: *"Test edilmemiş özellikleri çalışıyor gibi gösterme."*

Sürüm bu yüzden **5.5-final**. v6.0 etiketi Faz 1–4 kabul
kriterleri geçtiğinde verilecek.

---

## 2. BU TURDA YAPILANLAR ✅

### 2.1 Yeni modüller

| Dosya | Satır | İşlev |
|---|---:|---|
| `backtest/candidate_scan.py` | 163 | Portföyden bağımsız aday taraması |
| `backtest/robust_stats.py` | 250 | Küme tekilleştirme, gün küme bootstrap, Bonferroni, 4 durumlu hüküm |
| `tests/test_v55_audit.py` | 300 | 29 regresyon testi |

### 2.2 Değişen modüller

| Dosya | Değişiklik |
|---|---|
| `tools/entry_edge.py` | `stopped_horizon()`; brüt/net ayrımı; 5 yeni CLI bayrağı; küme GA; 4 durumlu hüküm |
| `core/portfolio.py` | `configure_peak()`, `_track_peak()`, `peak_resets` |
| `core/config.py` | `drawdown_peak_mode`, `drawdown_peak_window_days` |
| `backtest/engine.py` | Tepe penceresi bağlantısı; `result.drawdown_peak` |
| `tools/validate_strategy.py` | `--drawdown-peak-mode`, `--drawdown-peak-days` |
| `app/__init__.py` | `5.4-final` → `5.5-final` |

### 2.3 Yeni belgeler

- `V6_ANALIZ_RAPORU.md` — Aşama 1: mimari, çalışan/bozuk/eksik
- `V6_GELISTIRME_PLANI.md` — Aşama 2: faz faz plan
- `V6_TEST_RAPORU.md` — gerçek test çıktıları, başarısız hipotezler
- `V6_KURULUM_REHBERI.md`
- `V6_KULLANIM_KILAVUZU.md`
- `DEGISIKLIKLER_FINAL_v5.5.md`
- `docs/test_ciktisi_v5.5.txt` — ham pytest çıktısı

### 2.4 Yeni ölçümler

- `docs/giris_kenari_v55_5m.json`
- `docs/giris_kenari_v55_15m.json`
- `docs/giris_kenari_v55_1h.json`
- `docs/dogrulama_v55_rolling.json`
- `docs/dogrulama_v55_daily.json`

---

## 3. ÖLÇÜM SONUÇLARI — ÖZET

| TF | Bağımsız n | Net R | Net GA | Hüküm |
|---|---:|---:|---|---|
| 5m | 818 | −0,5601 | [−0,673, −0,515] | **KENAR ELENDİ** |
| 15m | 302 | −0,2570 | [−0,435, −0,174] | **KENAR ELENDİ** |
| 1h | 67 | −0,1088 | [−0,338, +0,160] | **YETERSİZ ÖRNEKLEM** |

**Başarısız hipotez (gizlenmiyor):** v5.4'ün "uzun ufukta işaret"
gözlemi çürüdü. 15m 48 bar stopsuz +0,106R → stoplu **−0,111R**;
adayların %75'i stopa takılıyor. Bonferroni sonrası p 0,028 → 0,419.

---

## 4. BU TURDA YAPILMAYANLAR ❌

Brief'in istediği ama **yapılmayan** işler:

| Faz | İş | Neden yapılmadı |
|---|---|---|
| 1 | 1 yıl × 30–50 sembol veri | İndirme + depolama altyapısı gerekiyor; tek oturumluk değil |
| 1 | Funding backtest bağlantısı | Sonraki adım; araç 0 satır funding içeriyor |
| 2 | 6 yeni strateji (trend/breakout/sweep/SMC/VWAP/momentum) | Örneklem olmadan test edilemez |
| 2 | Skor kalibrasyonu | OOS örneklem gerekiyor |
| 3 | Sınırsız pozisyon + portföy tavanları | Likidasyon/stres testi ön koşul |
| 3 | Haftalık/aylık zarar denetimi | Yapılmadı |
| 4 | Tick dolum modeli, markout | Yapılmadı |
| 4 | **Testnet uçtan uca** | API anahtarı yok; koşulmadı |
| 5 | AI/adaptif öğrenme | Kenar bulunmadan anlamsız |
| 6 | Web panel | Sıfırdan iş; kod yok |

**Bu liste eksiksizdir.** Yapılmamış hiçbir iş yapılmış gibi
sunulmadı.

---

## 5. GERİYE DÖNÜK UYUMLULUK

- `drawdown_peak_mode` varsayılanı `all_time` = v5.4 davranışı
- `entry_edge` varsayılanı artık bağımsız tarama; eski davranış
  `--legacy-probe` ile alınabilir
- **819 eski test + 29 yeni test = 862 passed**
- Mevcut çalışan özellikler (borsa adaptörleri, koruyucu stop,
  kill switch, durum kalıcılığı) **dokunulmadan korundu**

Brief kuralı *"Çalışan mevcut özellikleri sebepsiz yere kaldırma"*
uygulandı.

---

## 6. SONRAKİ TUR İÇİN ÖNERİLEN SIRA

1. **Faz 1.5** — funding'i `validate_strategy`'ye bağla (küçük iş,
   büyük dürüstlük kazancı)
2. **Faz 1.1–1.3** — 1 yıl × 30–50 sembol indirici
3. **Faz 1.6** — Binance maliyet ölçümü (451 kısıtı çözülürse)
4. **Faz 4.6** — testnet uçtan uca (anahtar gerektirir)
5. **Faz 2** — ancak yukarıdakiler bitince yeni strateji araştırması

Detay: `V6_GELISTIRME_PLANI.md`
