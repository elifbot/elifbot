# V5.6 — FUNDING DOĞRULAMASI

**Sürüm:** 5.6-final · **Tarih:** 2026-11-08

> **Bulunan kusur:** Backtest funding'i **hiç hesaplamıyordu**, ama
> rapor "Funding: −0,03" yazıyordu. Bu "funding yok" değil,
> "funding hesaplanmadı" idi.
> **Düzeltme:** bağlandı. **Kalan eksik:** tarihsel funding verisi yok.

---

## 1. KUSUR — SESSİZ SIFIR

### 1.1 Tespit

`BacktestEngine.run()` **`funding_rates` parametresini kabul ediyordu**:

```python
def run(self, candles, ..., funding_rates: dict[str, list[tuple[int,float]]] | None = None)
```

Ve motor içinde uygulanıyordu:

```python
if funding_rates and symbol in funding_rates:
    rate = self._funding_rate_at(funding_rates[symbol], ts_ms)
```

**Ama `tools/validate_strategy.py` bu parametreyi HİÇ geçmiyordu.**

| Yol | Funding besleniyor muydu? |
|---|---|
| Canlı (`app/main.py`) | **EVET** — `*_funding.csv` yükleniyordu |
| Walk-forward (`backtest/walkforward.py`) | Parametre var, çağıran geçmiyordu |
| **Doğrulama (`tools/validate_strategy.py`)** | **HAYIR** |

### 1.2 Sonuç

Doğrulama raporlarındaki `Funding: -0.03` gibi değerler, motorun
**pozisyon süresi varsayılanı**ndan gelen artıklardı — gerçek tarihsel
funding ödemesi değildi. Rapor bunu "0'a yakın funding" gibi gösteriyordu.

**Bu, şartnamenin "ölçülmeyeni sıfır gösterme" maddesinin ihlaliydi.**

---

## 2. DÜZELTME

### 2.1 Yeni modül — `backtest/funding.py`

| Fonksiyon | İş |
|---|---|
| `load_funding_csv(path)` | `<SYM>_funding.csv` → zaman sıralı `[(ts_ms, rate)]` |
| `load_funding_dir(dir, start, end)` | Tüm semboller + **kapsama denetimi** |
| `funding_status(rates, coverage)` | Rapor için durum — **asla sahte sıfır yok** |

### 2.2 Kapsama denetimi

Standart funding dönemi **8 saat** (00:00 / 08:00 / 16:00 UTC).
Bazı sembollerde 4 saate düşebilir; bu yüzden dönem sayısı
**veriden sayılır**, varsayılmaz.

```
beklenen_dönem = (pencere_süresi / 8 saat) + 1
kapsama_oranı  = kapsanan_dönem / beklenen_dönem
tam            = kapsama_oranı ≥ 0,99
```

### 2.3 Bağlama

`tools/validate_strategy.py` içinde funding **bir kez** yüklenir ve
**4 bloğun hepsine** geçirilir (birincil, maliyetsiz, sınır, WF):

```python
funding_rates, _fcov = load_funding_dir(data_dir, start_ts, end_ts)
funding_info = funding_status(funding_rates, _fcov)
logger.info("Funding: %s — %s", funding_info["durum"], funding_info["neden"])
...
_run_block(..., funding_rates=funding_rates, funding_info=funding_info)
```

Ve rapor JSON'una yeni alan:

```json
"funding": { "durum": "...", "neden": "...", "kapsama": {...} }
```

---

## 3. DURUM ETİKETLERİ (üç ayrı durum, sıfır yok)

| Durum | Anlamı | Rapor metni |
|---|---|---|
| `UYGULANMADI` | Hiç tarihsel veri yüklenmedi | *"Backtest funding'i HESAPLAMADI; bu 'funding sıfır' anlamına GELMEZ."* |
| `EKSIK_KAPSAMA` | Veri var ama dönemler eksik | *"N sembolde dönem kapsaması tam değil."* + sembol listesi |
| `UYGULANDI` | Tüm sembollerde kapsama ≥ %99 | *"Tüm sembollerde dönem kapsaması tam."* |

**Şu andaki gerçek durum: `UYGULANMADI`** — depoda `*_funding.csv` yok.

---

## 4. YÖN KURALI (doğrulandı)

| Funding oranı | LONG | SHORT |
|---|---|---|
| Pozitif (+) | **öder** | **alır** |
| Negatif (−) | **alır** | **öder** |

İşaret broker tarafında uygulanır; yükleyici yalnız oranı taşır.

**Muhasebe yönü (v5.5'te düzeltilmişti, korundu):**
`gross_pnl` hesabında `funding_paid` brüte **GERİ EKLENİR (+)**,
çünkü net PnL'den düşülmüş bir kesintidir. Bu, zarar atfı
modülünde test edilmiştir.

---

## 5. ÖDEME ZAMANLAMASI

`BacktestEngine._funding_rate_at(rates, ts_ms)` — verilen ana kadar
geçerli olan **son** oranı döndürür (ileriye bakmaz).

**Sınır (dürüstlük):** Ödeme, her 8 saatlik sınırda bir kez uygulanmalı.
Motor bunu mum yönetimi içinde çağırıyor; **mum aralığı 8 saatten
büyükse** (örn. 1d grafik) bir mumda birden çok ödeme dönemi olabilir
ve tek oran uygulanır. Mevcut testler 5m/1h/4h kullandığı için bu
senaryo oluşmadı, ama **1d ve üstünde doğrulanmadı.**

---

## 6. POZİSYON SÜRESİNCE BİRİKİM

Funding, pozisyon açık kaldığı sürece her ödeme döneminde uygulanır.
Risk planlamasında da tampon olarak yer alır:

```python
estimated_funding_buffer = notional * funding_rate
net_risk_at_stop = notional * (stop_fraction + cost_rate) + notional * funding_rate
```

Yani funding, **stop riskinin içine** dahildir — şartnamenin
"komisyon + slippage + funding dahil" maddesi karşılanıyor.

---

## 7. EKSİK OLAN — VERİ

| İhtiyaç | Durum |
|---|---|
| Tarihsel funding CSV'leri | **YOK** |
| Binance USD-M funding geçmişi | indirilmedi |
| OKX swap funding geçmişi | indirilmedi |
| 12 aylık kapsama | **YOK** (90 gün mum verisi var) |

### Nasıl toplanır?

```bash
# Beklenen biçim: data/validation/<SYMBOL>_funding.csv
# timestamp,rate
# 1704067200000,0.0001
```

Binance USD-M: `GET /fapi/v1/fundingRate?symbol=...&startTime=...&limit=1000`
OKX: `GET /api/v5/public/funding-rate-history?instId=...`

**Bu indirme bu turda YAPILMADI.** Ağ erişimi kısıtlı ve 12 aylık
mum verisi de olmadığı için funding tek başına indirilse bile
kapsama testi anlamlı olmazdı.

---

## 8. TESTLER

`tests/test_v56_funding.py` — **7 test, hepsi geçti:**

- Veri yok → `UYGULANMADI`, metinde "HESAPLAMADI" ve "sıfır" geçiyor
- CSV okuma + zaman sıralaması
- Tam kapsama → `UYGULANDI`
- Kısmi kapsama → `EKSIK_KAPSAMA` + sembol listesi
- Boş dizin → uydurma veri yok
- Motor `funding_rates` parametresini kabul ediyor (imza denetimi)
- **Doğrulama aracı funding'i motora geçiriyor** (regresyon kilidi)

### Düzeltilen kendi hatam

İlk sürümde kapsama kontrolü `if end_ts_ms > start_ts_ms > 0` idi.
`start_ts_ms == 0` geçerli bir sınır olmasına rağmen sentinel sayılmış,
bu yüzden kapsama hep 0 çıkmıştı. Test yakaladı, düzeltildi:
`if end_ts_ms > 0 and end_ts_ms > start_ts_ms`.

---

## 9. KANIT DOSYALARI

| Dosya | İçerik |
|---|---|
| `backtest/funding.py` | Yükleyici + kapsama denetimi |
| `tools/validate_strategy.py` | Bağlama (4 blok) + rapor alanı |
| `tests/test_v56_funding.py` | 7 test |
| `docs/dogrulama_v5.6_kasa1000.json` | Funding alanı içeren ilk koşu |