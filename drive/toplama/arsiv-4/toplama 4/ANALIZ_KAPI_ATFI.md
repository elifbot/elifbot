# Kapılar Bizi Kârdan mı Etti? — Karşı-Olgusal Analiz

**Tarih:** 2026-11-08 · **Sürüm:** 5.2-final · **Test:** 786 passed, lint temiz
**Veri:** OKX 6 sembol (BTC/ETH/SOL/XRP/DOGE/ADA), 90 gün, 155.520 × 5m bar, ölçülmüş maliyet

> **Kısa cevap: Hayır. Üç kapı da bizi kârdan etmedi — zarardan kurtardı.**
> Bunu üç bağımsız yöntemle ölçtüm. Asıl sorun giriş filtreleri değil, **çıkış geometrisi**.

---

## 0. Yöntem: neden iki farklı ölçüm gerekti

Kapılar iki sınıfa ayrılıyor ve aynı yöntemle ölçülemezler:

| Sınıf | Örnek | Yön/stop var mı? | Doğru yöntem |
|---|---|---|---|
| **A** — oluşmuş sinyalin reddi | maliyet kapısı, drawdown koruması, dolmayan limit | **Var** | Karşı-olgusal simülasyon |
| **B** — sinyal hiç oluşmadı | `dusuk_hacim`, `fake_breakout`, `trend_onayi_yok` | **Yok** | Ablasyon (eşiği değiştir, yeniden koş) |

`dusuk_hacim` sinyalden **önce** reddediyor — ortada yön yok, dolayısıyla "bu işlemi açsaydık ne olurdu?" sorusu tanımsız. Bunu atlasyıp "hacim kapısı şu kadar kârı engelledi" demek uydurma olurdu.

**Yeni araçlar:** `tools/gate_attribution.py` (A sınıfı), `tools/ablate_gates.py` (B sınıfı), motorda `gate_probe` kancası.

Karşı-olgusal simülasyonda her aday portföyden **bağımsız**, gerçek çıkış kuralları (stop/TP1/trailing/zaman stopu/acil net stop) ve ölçülmüş maliyetlerle, sabit 25 USDT net riskle sonuna kadar koşuldu. Giriş anında dolduruldu — böylece kapı sorusu dolum sorusundan ayrıldı. Dolumun **limit fiyatından** olduğu testle doğrulandı (tetik fiyatı avantaj sağlamıyor).

---

## 1. Maliyet kapısı — 13 canlı red bizi kârdan etti mi?

### Karşı-olgusal ölçüm (90 gün, 90 red)

| Ölçüt | Değer |
|---|---|
| Reddedilen aday | **90** |
| Açsaydık net | **−1.485,74 USDT** |
| Kazanan / kaybeden | 17 / 73 |
| **Kazanma oranı** | **%18,9** |
| Ortalama kazanç | +14,88 USDT |
| Ortalama kayıp | −23,82 USDT |
| Ödül/risk | 0,625 |
| Başabaş için gereken kazanma | **%61,5** |
| En iyi / en kötü tek işlem | +50,71 / −39,06 |

**Kapı doğru seçiyor.** Reddettiklerinin kazanma oranı %18,9 — kabul edilenlerin %28,6'sından **belirgin şekilde düşük**. Yani maliyet kapısı rastgele değil, kötü adayları eliyor.

### Ablasyon doğrulaması (kapıyı tamamen kapat)

| | Net | İşlem | Kazanma |
|---|---|---|---|
| TEMEL | −80,6453 | 14 | %28,6 |
| Maliyet kapısı **KAPALI** | **−80,6706** | 16 | **%25,0** ↓ |

Kapıyı kapatmak 2 işlem ekledi, kazanma oranını düşürdü ve neti **kötüleştirdi**. Farkın küçük (−0,03) olması kapının önemsiz olduğu anlamına gelmiyor: drawdown koruması örneklemi kestiği için portföy düzeyinde etki sınırlanıyor. Kapının gerçek etkisi karşı-olgusal ölçümde görünüyor: **−1.485,74 USDT engellendi.**

### Canlıdaki 13 red
PIPPIN, TRX, CRM gibi OKX sembolleri ölçümde yok → yedek varsayım 56 bps gidiş-dönüş. %0,35 stopla maliyet payı %61,6 → sert eşik %60 aşılıyor. Aynı popülasyonun backtestteki kazanma oranı %18,9. **Bu 13 red büyük olasılıkla bizi zarardan kurtardı.**

---

## 2. Hacim kapısı — "%85 red sistemi kilitliyor" doğru mu?

**Hayır. Bu bir yanılsamaydı.** Eşiği 1,5'ten 0,5'e çektim:

| Red nedeni | TEMEL | RVOL 0,5 | Değişim |
|---|---|---|---|
| `dusuk_hacim` | 126.455 | **43.452** | **−%66** |
| `fade_kosulu_yok` | 12.703 | **61.054** | **+%381** |
| `guclu_trend_fade_kapali` | 5.696 | **26.066** | **+%358** |
| `fake_breakout_or_suspect` | 3.624 | 7.540 | +%108 |
| `rejim_uyumsuz` | 2.476 | 7.476 | +%202 |

**Sonuç:**

| | Net | İşlem | Kazanma |
|---|---|---|---|
| TEMEL | −80,6453 | 14 | %28,6 |
| RVOL 0,5 | **−82,2538** | **14** | **%21,4** ↓ |

Hacim kapısından geçen sinyal sayısı 3 katına çıktı ama **işlem sayısı hiç artmadı (14 → 14)** ve net **kötüleşti**. Sebep: reddetmeler bir sonraki filtreye kaydı. `dusuk_hacim` zincirin **ilk** halkası, darboğaz değil.

**"%85 red sistemi fiilen kilitliyor" teşhisim yanlıştı.** Bunu düzeltiyorum: hacim kapısı tek başına belirleyici değil; kaldırınca FADE koşulu ve güçlü-trend filtresi aynı işi yapıyor.

---

## 3. Maker dolum oranı — %83 dolmuyor. Kâr mı kaçıyor?

### Karşı-olgusal: dolmayan 19 emir

| Ölçüt | Değer |
|---|---|
| Dolmayan aday | 19 |
| Dolsaydı net | **−201,74 USDT** |
| Kazanma oranı | %36,8 |
| Ödül/risk | 0,584 |
| Başabaş için gereken | %63,1 |

**Dolmamaları bizi zarardan kurtardı.**

### Ama burada gerçek bir backtest/canlı sapması buldum

| | Dolum oranı |
|---|---|
| Backtest (90 gün) | 19 emir → 14 dolum = **%74** |
| Canlı (2 × 15 dk) | 12 emir → 2 dolum = **%17** |

Kök neden `backtest/engine.py`:
```python
def _limit_ttl_ms(self) -> int:
    # Canlıdaki 45 sn TTL'in mum ölçeğinde karşılığı: bir mum boyunca geçerli.
    return self.base_config.data.timeframe_ms      # 300.000 ms = 5 dakika
```
Backtest emre **5 dakika** şans veriyor, canlı **45 saniye**. Yaklaşım kodda yorum olarak yazılı ama **büyüklüğü hiç ölçülmemiş**: pencere **6,7×** geniş.

**Kanıt:** TTL'i 45 → 300 sn yaptım, sonuç **birebir aynı** kaldı (−80,6453 / 14 işlem / %28,6). Bu, backtestte dolumu TTL'in değil mum aralığının belirlediğini doğruluyor.

Yeni ölçüm (`fill_optimism`, 30 gün): 39 dolumun **3'ü (%7,7)** 5 dakikalık TTL'den bile sonra gerçekleşti.

**Sonuç: canlıdaki %17 gerçekçi, backtestteki %74 iyimser.** Backtest işlem sayısını ve dolayısıyla sonuçlarını şişiriyor.

---

## 4. R:R asimetrisi — asıl sorun bu

90 günlük birincil koşudaki **14 işlemin tamamı**:

| Sembol | Çıkış nedeni | PnL | Hedef | **R** |
|---|---|---|---|---|
| ETH | position_loss_stop | −33,6577 | 25,0050 | **−1,346** |
| BTC | position_loss_stop | −25,4486 | 25,0050 | −1,018 |
| ADA | stop_loss | −1,1827 | 1,2680 | −0,933 |
| **XRP** | **trailing_stop** | **+0,6544** | 3,4575 | **+0,189** |
| SOL | stop_loss | −7,7552 | 8,4873 | −0,914 |
| ADA | stop_loss | −0,2955 | 0,3189 | −0,927 |
| **BTC** | **trailing_stop** | **+4,0365** | 5,1321 | **+0,787** |
| BTC | stop_loss | −5,7121 | 6,2512 | −0,914 |
| **ADA** | **trailing_stop** | **+0,2844** | 1,2455 | **+0,228** |
| XRP | stop_loss | −4,2293 | 4,6092 | −0,918 |
| XRP | stop_loss | −3,4180 | 3,7464 | −0,912 |
| **ETH** | **trailing_stop** | **+1,5401** | 2,7887 | **+0,552** |
| SOL | stop_loss | −2,7939 | 3,0624 | −0,912 |
| BTC | stop_loss | −2,4989 | 2,7390 | −0,912 |

### Bulgu: kazananların HİÇBİRİ 1R'ye ulaşmadı

| Çıkış nedeni | Adet | Ortalama R | Aralık |
|---|---|---|---|
| `trailing_stop` (kazananların tamamı) | 4 | **+0,439** | +0,189 … +0,787 |
| `stop_loss` | 8 | −0,918 | −0,933 … −0,912 |
| `position_loss_stop` | 2 | **−1,182** | −1,346 … −1,018 |

**`tp1_r_multiple = 1,0` olan TP1, 90 günde bir kez bile tetiklenmedi.**

### Mekanizma

| Ayar | Değer | Sorun |
|---|---|---|
| `trail_activation_r` | 0,75 | Trailing **0,75R'de** aktifleşiyor |
| `trail_atr_multiple` | 2,0 | Takip mesafesi **2 ATR** |
| `stop_atr_multiple` | 1,5 | İlk stop **1,5 ATR** |
| `tp1_r_multiple` | 1,0 | TP1 **1,0R'de** |
| `breakeven_activation_r` | 1,0 | Başa baş **1,0R'de** |

Takip mesafesi 2 ATR = **1,33R** (ilk stop 1,5 ATR = 1R). Yani trailing, tepenin **1,33R gerisinden** geliyor. 0,75R'de aktifleştiğinde stop hâlâ girişin altında. Kârı kilitlemek için tepenin 1,33R'yi aşması gerekiyor — ama normal bir geri çekilme daha önce trailing'i vuruyor. TP1 (1,0R) ve başa baş (1,0R) bu yüzden hiç devreye girmiyor.

### Aritmetik

| Ölçüt | Değer |
|---|---|
| Ortalama kazanç | **+0,439R** |
| Ortalama kayıp | **−0,971R** |
| **Ödül/risk** | **0,452** |
| Kazanma oranı | %28,6 |
| Beklenti | **−0,568R** |
| Başabaş için gereken kazanma | **%68,9** |
| Başabaş için gereken ödül/risk | **2,500** |
| **Mevcut oran ihtiyacın kaç katı küçük** | **5,53×** |

---

## 5. En güçlü kanıt: %49 kazanma bile yetmiyor

Drawdown korumasının reddettiği **1.012 adayı** simüle ettim:

| Ölçüt | Değer |
|---|---|
| Aday | 1.012 |
| Açsaydık net | **−5.539,83 USDT** |
| Kazanan / kaybeden | 497 / 515 |
| **Kazanma oranı** | **%49,1** |
| Ödül/risk | 0,614 |
| Başabaş için gereken | **%62,0** |

**Bu popülasyon neredeyse yazı-tura isabet ediyor — %49,1.** Sağlıklı bir ödül/risk ile bu kârlı olurdu. Ama mevcut çıkış geometrisi %62 kazanma istiyor, o yüzden **yine zarar ediyor.**

Üç reddedilen popülasyonun hepsi aynı desende:

| Kapı | Kazanma | Ödül/risk | Gereken kazanma | Net |
|---|---|---|---|---|
| Maliyet | %18,9 | 0,625 | %61,5 | −1.485,74 |
| Dolmayan limit | %36,8 | 0,584 | %63,1 | −201,74 |
| Drawdown | **%49,1** | 0,614 | %62,0 | −5.539,83 |

**Hiçbiri başabaş eşiğine yaklaşmıyor.** Sorun seçicilik değil — herkes kaybediyor çünkü ödül/risk her yerde ~0,6.

---

## 6. Çıkış geometrisini düzeltince ne oldu?

`RR_KOMBINE`: TP1 0,5R + trail aktivasyon 1,5R + trail mesafe 0,75 ATR + başa baş 0,4R.

| | TEMEL | RR_KOMBINE |
|---|---|---|
| Net | −80,6453 | **−81,3704** |
| İşlem | 14 | **40** |
| **Kazanma oranı** | %28,6 | **%62,5** |
| Ortalama kazanç | +1,546 | **+0,409** |
| Ortalama kayıp | −8,683 | −6,106 |
| Ödül/risk | 0,178 | **0,067** |
| Profit factor | 0,071 | **0,112** |
| Ücret | 12,77 | **18,05** |
| Kayma | 12,29 | **16,06** |

**Kazanma oranı ikiye katlandı (%28,6 → %62,5) ve işlem sayısı üçe katlandı.** Ama:
- Ortalama kazanç 1,546'dan **0,409**'a çöktü — erken kâr alma kazancı küçülttü.
- Ödül/risk 0,178'den **0,067**'ye düştü.
- 40 işlemde maliyet 34,11 USDT'ye çıktı (12,77+12,29 = 25,06'dan).
- Profit factor 0,071 → 0,112: **iyileşti ama hâlâ 1'in çok altında.**

**Ders: kazanma oranını yükseltmek tek başına çözüm değil.** Parametreler kazanma oranı ile ödül arasında takas yapıyor; beklenti negatif kalıyor. Bu bir düğme ayarı işi değil, **çıkış tasarımı** işi.

---

## 7. Senin hipotezinin cevabı

> "Kapılar işleme girmemizi engelledi, geçen pozisyonlar zararla kapattı — yani bu düşünce sistemimize uyum sağlamıyor."

**Üç ölçüm de aynı yönde:**

1. **Kapılar kâr engellemiyor.** Maliyet kapısı −1.485,74, drawdown koruması −5.539,83, dolmayan emirler −201,74 USDT'lik zararı engelledi. Hepsini gevşetmek neti kötüleştirdi.
2. **Geçen işlemler gerçekten zararla kapattı** — bu gözlemin doğru.
3. **Ama yanlış uyum giriş filtrelerinde değil, çıkışta.** %49,1 isabet eden bir popülasyon bile bu ödül/risk ile kaybediyor. Filtreleri değiştirmek bunu düzeltmez.

Yani: **sistem doğru adayları seçiyor, sonra kazananlarını 0,44R'de kesip kaybedenlerini 0,97R'ye bırakıyor.** Kâr fırsatı girişte değil, çıkışta kaybediliyor.

---

## 8. Bu analiz için yapılan kod değişiklikleri

| # | Değişiklik | Neden |
|---|---|---|
| 1 | `engine.gate_probe` kancası | Oluşmuş sinyallerin hangi kapıda reddedildiği kaydediliyor. Varsayılan kapalı, sonucu değiştirmiyor (test var) |
| 2 | `tools/gate_attribution.py` | Karşı-olgusal simülasyon — A sınıfı kapılar |
| 3 | `tools/ablate_gates.py` | 12 varyantlı ablasyon — B sınıfı kapılar |
| 4 | Gölge izleyici **stop-farkındalıklı** | Eski ölçüm "ufuklardan en iyi getiri > 0" diyordu → ileriye bakıp kiraz toplama. Yerine **ilk temas**: stop önce mi, hedef önce mi |
| 5 | Maliyet kapısı reddi gölgeye bağlandı | Canlıda bu redler hiç izlenmiyordu; bir daha cevaplayamaz hale gelmeyelim |
| 6 | `engine.fill_optimism` ölçümü | TTL dışı dolum sayısı artık görünür |

**Gölge izleyicideki düzeltme önemli:** eski `would_have_won` metriği, fiyat önce stopu vurup sonra yükselse bile "kazanırdı" sayıyordu. Yeni `first_exit` bunu doğru ayırıyor; test bu vakayı özellikle doğruluyor.

**Test:** 765 → **786 passed** (+21). Lint temiz.

---

## 9. Sıradaki iş — öncelik değişti

Eski listem yanlıştı. Ölçüme göre doğru sıralama:

| Öncelik | İş | Gerekçe |
|---|---|---|
| **1** | **Çıkış tasarımı** | Ödül/risk 0,452; gereken 2,5 → **5,53× açık**. Diğer her şey bunun yanında ikinci derece |
| **2** | **Backtest dolum modelini düzelt** | 5 dk pencere vs 45 sn gerçek → backtest %74, canlı %17 dolum. Tüm backtest sonuçları iyimser |
| 3 | Maliyet/canlı eşitliği | ✅ yapıldı |
| ~~4~~ | ~~Hacim kapısı kalibrasyonu~~ | **Ölçüm bunu öncelik olmaktan çıkardı** — kaldırınca redler aşağı kayıyor, işlem sayısı artmıyor |

### Çıkış tasarımı için somut yön
- Takip mesafesi (2 ATR = 1,33R) aktivasyon eşiğinden (0,75R) **büyük olmamalı**. Şu an kâr kilitlenemiyor.
- TP1 1,0R'de ama kazananların hiçbiri oraya ulaşmıyor → ya TP1 düşmeli ya trailing geç aktifleşmeli. İkisini birlikte yapmak (RR_KOMBINE) ödül/riski daha da bozdu.
- %62,5 kazanma elde edilebiliyor. Bu isabet oranıyla başabaş için ödül/risk ≥ 0,6 yeterli — yani **kazananları 0,409'da değil ~1,0R'de kapatmak** gerekiyor.
- Acil net stop (−1,35R) hedef riski aşıyor; ayrı bir sınır işi.

---

## 10. Açık sınırlar

- Karşı-olgusal simülasyon **portföy etkileşimini** (teminat, drawdown, eşzamanlı pozisyon) model dışı bırakır. Kapı etkisini izole eder; portföy sonucunu tahmin etmez.
- Giriş **anında doldu** varsayıldı. Bu, karşı-olgusal sonuç için iyimserdir — yani gerçek zarar daha da büyük olabilirdi.
- Karşı-olgusal yol **5m** (1m doğrulaması yok). Ablasyonların hepsi aynı yolu kullandı, karşılaştırma geçerli.
- 6 sembol, 90 gün. Küçük coinlerde maliyet daha kötü; sonuç daha da negatif olurdu.
- Canlı 13 red için yön/stop kaydı yoktu (gölge izleme o zaman bağlı değildi) — backtest popülasyonundan çıkarım yapıldı. Artık kaydediliyor.
- Kenar hâlâ YOK. Bu analiz neden olmadığını açıklıyor; kâr üretmiyor.

---

## 11. Dosyalar

| Dosya | İçerik |
|---|---|
| `docs/kapi_atif_v5.2.json` | 1.121 adayın kapı atfı + karşı-olgusal sonuçlar |
| `docs/ablasyon_v5.2.json` | 5 varyantın tam metrikleri |
| `docs/dolum_iyimserligi.json` | TTL dışı dolum ölçümü |

### Yeniden üretme
```bash
python3 -m tools.gate_attribution --days 90 \
  --costs docs/maliyet_olcum_v5.2.json --out docs/kapi_atif_v5.2.json

python3 -m tools.ablate_gates --days 90 \
  --only TEMEL,MALIYET_KAPISI_KAPALI,HACIM_RVOL_0.5,MAKER_TTL_300,RR_KOMBINE \
  --out docs/ablasyon_v5.2.json
```
