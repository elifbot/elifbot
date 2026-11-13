# ACARBOT FINAL v1.9 — "Şüpheli hacim" seli ve teminat açıklaması

Tarih: 7 Kasım 2026 · Mod: **PAPER ONLY** · Test: **298/298 geçti**
Önceki sürüm: v1.8 (281 test) — 25 USDT hedef net risk davranışı **aynen korundu**.

---

## 1. Şikâyet

> "Şüpheli hacimler devam ediyor, sürekli olay akışında var."

v1.8 oturumunda (11:28–12:12 UTC) logda **2.788+** `RVOL ŞÜPHELİ` satırı,
**352 tekil sembol**, bunların **2.785'i OKX / 3'ü Binance**. Panelin olay akışı
bu satırlarla doluyor, gerçek olaylar (giriş/çıkış/stop) görünmüyordu.

## 2. Kök neden — canlı borsa verisiyle kanıt

### 2.1 Birim hatası DEĞİL (v1.6 düzeltmesi sağlam)

OKX `tickers` + `public/instruments` karşılaştırması:

| Enstrüman | `volCcy24h / vol24h` | `ctVal` (kontrat büyüklüğü) | Sonuç |
|---|---|---|---|
| NOK-USDT-SWAP | 1 | 1 | ✔ eşleşiyor |
| COAI-USDT-SWAP | 0.1 | 0.1 | ✔ |
| ZRX-USDT-SWAP | 10 | 10 | ✔ |
| SHIB-USDT-SWAP | 1.000.000 | 1.000.000 | ✔ |
| BTC-USDT-SWAP | 0.01 | 0.01 | ✔ |

Yani baz hacim dönüşümü doğru. Sorun başka yerde.

### 2.2 Sorun: taban hacmi ~0 olan (likiditesiz) enstrümanlar

20 saniye boyunca 1 Hz örnekleme (15 örnek), 24s baz hacim değişimi:

| Enstrüman | Hacmi değişen örnek | Yorum |
|---|---|---|
| NOK-USDT-SWAP | **0 / 15** | hiç işlem yok |
| COAI-USDT-SWAP | **0 / 15** | hiç işlem yok |
| ZRX-USDT-SWAP | **0 / 15** | hiç işlem yok |
| SHIB-USDT-SWAP | **0 / 15** | hiç işlem yok |
| BTC-USDT-SWAP | 9 / 15 | normal, likit |

OKX 1 dakikalık mumlar (son 100 dk):

| Enstrüman | İşlemsiz dakika | 100 dk ort. baz hacim |
|---|---|---|
| NOK-USDT-SWAP | **78 / 100** | 1,51 |
| ZRX-USDT-SWAP | 55 / 100 | — |
| BTC-USDT-SWAP | 0 / 100 | — |

**Matematik:** RVOL = (pencere hacmi / pencere sn) / (taban hacmi / sn).
Taban saniyede ~0,001 baz ise, **tek bir normal işlem** RVOL'u
100–10.000 kat gösterir. `sanity_cap=100` bunu "veri hatası" sanıyordu.

Logdaki sembol listesi teşhisi doğruluyor: NOK, EWY, KR200, NAVER, SONY,
HYUNDAI, SMCI, RKLB, AMGN, KIOXIA… OKX'in **tokenize hisse/endeks swap'ları**
ve düşük kapsamlı coinler. Bu enstrümanlar Binance vadeli tarafında yok
(352 sembolün 350'si OKX) — asimetri buradan geliyor.

### 2.3 Üç ayrı kod kusuru

| # | Kusur | Etki |
|---|---|---|
| A | `suspect = rvol > 100` — likidite kontrolü yok | likiditesiz coin "veri hatalı" damgası yiyor |
| B | `_last_spike` yalnız **aynı saniyede** tekilleştiriyor | 3 sn pencere boyunca **aynı patlama 3 kez** loglanıyor (CELO 1654.7 → 1654.7 → 1658.9) |
| C | `spike=None` → `tick_volume=0`; geçerliyse `tick_volume = 3 sn TOPLAMI` | filtre varsa maker emir **dolmuyor**; varsa hacim **mükerrer** sayılıyor |

## 3. Yapılan düzeltmeler

### `core/config.py`
```python
spike_min_baseline_notional_per_second: float = 5.0   # likidite tabanı (USDT/sn)
rvol_log_interval_seconds: float = 60.0               # sembol başına log aralığı
```

### `core/spike.py`
- `SpikeEvent`'e `illiquid: bool` ve `baseline_notional_per_second: float`.
- Sınıflandırma:
  ```python
  baseline_notional = baseline_per_second * price
  illiquid = baseline_notional < min_baseline_notional_per_second
  suspect  = rvol > sanity_cap and not illiquid
  ```
  → Likiditesizlik **veri hatası sayılmaz**. `sanity_cap` **yükseltilmedi**;
  gerçek birim hataları hâlâ yakalanıyor.
- Patlama tekilleştirme: aynı saniye yerine **cooldown = pencere süresi (3 sn)**.
- Geriye dönük uyum: `min_baseline_notional_per_second=0` verilirse eski davranış.

### `app/executor.py`
- **Dolum modeli artık her tick gerçek ölçülen baz hacim deltasıyla besleniyor**
  (`tick_volume = base_volume`), filtre sinyali iptal etse bile.
  Hem "emir açlığı" hem 3 sn toplamının mükerrer sayımı bitti.
- Yeni `_log_volume_filter()`: sembol başına 60 sn'de tek satır; aradaki
  tekrarlar sayılıp `(+N tekrar bastırıldı)` olarak ekleniyor.
- Etiket ve seviye ayrıldı:
  - `LİKİDİTE DÜŞÜK` → **INFO** (beklenen piyasa durumu)
  - `RVOL ŞÜPHELİ` → **WARNING** (likit tabanda gerçek sapma)
  - **ERROR seviyesi kaldırıldı** — bunlar sistem hatası değil.
- Sayaçlar: `low_liquidity_count`, `rvol_suspect_count` → oturum raporuna
  `volume_filter` alanı olarak yazılıyor.

### `app/main.py`
- Açılış logu: `HACİM FİLTRESİ v1.9: likidite tabanı 5.00 USDT/sn | …`
- Oturum raporuna `volume_filter` bloğu.

### Panel (`/home/user/panel/server.py`)
- Hacim filtresi kayıtları **olay akışına yazılmıyor**; toplu sayaç +
  "En Çok Takılan Coinler" dağılımı olarak gösteriliyor.
- Yeni KPI: **Hacim Filtresi** (likidite düşük / şüpheli ayrı) ve
  **Teminat Yetmedi** (INSUFFICIENT_FUNDS sayısı).
- `errors` sayacı yalnız gerçek sistem hatalarını sayıyor.

## 4. Testler

`tests/test_rvol_liquidity.py` — **17 yeni test**:
likidite sınıflandırması (3), geriye dönük uyum, geçersiz eşik,
patlama cooldown'u (2), dolum modeli gerçek hacim (4),
log kısıtlama ve seviyeler (4), config bağlantıları (2), sayaçlar.

```
python3 -m pytest -q   →   298 passed
```

## 5. "Teminatı aşmadan" ne demek?

Hedef net risk sabit: **25 USDT**. Formül (v1.8'den değişmedi):

```
per_unit = stop_mesafesi_oranı + 0.0016      (komisyon + funding tamponu)
notional = 25 / per_unit
teminat  = notional / kaldıraç(10x)
```

| Stop mesafesi | Notional | 10x teminat | 1.000 USDT hesapta |
|---|---|---|---|
| %0,30 (dar) | 5.434,78 | **543,48** | tek pozisyon hesabın yarısı |
| %0,77 | 2.688,17 | 268,82 | ~3 pozisyon |
| %2,50 (geniş) | 939,85 | 93,99 | ~10 pozisyon |

Dar stop → 25 USDT zararı tutturmak için **büyük notional** gerekir →
büyük teminat. v1.8 canlı oturumunda iki pozisyon (OL + PROS)
**737,48 USDT** teminat kilitledi, boş teminat ~261 USDT kaldı ve
sonraki 9 sinyal `INSUFFICIENT_FUNDS` ile reddedildi.

Yani "teminatı aşmadan taşımak" = her yeni pozisyonun gereken teminatı
**boş teminattan küçükse** açılır; değilse açılmaz. Sabit pozisyon sayısı
sınırı yok (APEX), sınır tamamen **matematiksel**. Kaldıracı artırmak
teminatı düşürür ama likidasyon mesafesini kısaltır — bu yüzden 10x korundu.

## 6. Sürüm notu

Bu sürüm **merge'e uygun** tutuldu: `SpikeDetector`'ın yeni parametreleri
opsiyonel ve varsayılanları eski davranışı koruyor; `SpikeEvent`'in yeni
alanları default'lu. Başka bir bot sürümüyle birleştirirken yalnız
`core/spike.py`, `core/config.py`, `app/executor.py` yüzeylerine bakmak yeterli.
