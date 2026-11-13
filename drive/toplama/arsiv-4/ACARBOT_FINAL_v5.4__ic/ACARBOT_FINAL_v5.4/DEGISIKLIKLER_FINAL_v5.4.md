# ACARBOT FINAL v5.4 — Değişiklik Günlüğü

**8 Kasım 2026 · Önceki sürüm: 5.3-final**

Bu sürüm bir **teşhis düzeltmesi** sürümüdür. v5.3'ün "kök neden çıkış
geometrisi" hükmü, kapısız simetrik çıkış testiyle **çürütüldü**. Ayrıntılı
ölçüm ve iddia denetimi: `ANALIZ_v5.4_GIRIS_KENARI.md`.

---

## 1. Önceki teşhis düzeltildi

v5.3 şöyle diyordu: kazananlar +0,44R'de kapanıyor, ödül/risk 0,452,
gereken 2,500 → 5,53× açık; sorun çıkışta.

**Bu akıl yürütme eksikti.** Aynı veri "fiyat zaten lehimize gitmiyor"
ile de açıklanabilir. İkisini ayırmanın tek yolu çıkışı sabit ve
simetrik tutup tüm adayları ölçmek. Yapıldı:

| Ölçüm (1.121 aday, kapısız) | Değer |
|---|---|
| Simetrik 1R brüt beklenti, kötümser | **−0,0246 R** · GA [−0,0778, +0,0285] |
| Simetrik 1R brüt beklenti, iyimser | −0,0175 R · GA [−0,0707, +0,0357] |
| Ortalama maliyet | **0,5352 R** |
| Skor ↔ ileri getiri korelasyonu | **0,040** |

Güven aralığı sıfırı içeriyor → **giriş yazı-tura**. Gözlenen gerçek
beklenti −0,5679 R ile "0 − 0,535 R" tahmini neredeyse eşit.
**Zarar, kenarsız girişe ödenen ücret.**

---

## 2. Yeni araç: `tools/entry_edge.py`

Kapısız giriş kenarı testi. Tüm adaylar (drawdown koruması dahil hiçbir
kapı uygulanmadan), sabit simetrik çıkış (−1R/+1R) ve "N bar sonra çık"
varyantı. Baz çizgisi: aynı sembol/yön/saat, rastgele gün, 500 permütasyon.

Karar kuralı: brüt ileri getiri > maliyet + 2·SE **ve** p < 0,05.

Mum içi sıra belirsizliği **iki sınır** olarak raporlanır (kötümser:
stop önce; iyimser: hedef önce). Tek sayı verilmez.

`--resample-minutes` ile 5m önbellek 15m/1h/4h'ye toplanır (uydurma yok;
eksik kovalar atlanır).

### Zaman dilimi merdiveni (90 gün, 6 OKX sözleşmesi)

| Zaman dilimi | Aday | Maliyet (R) | Simetrik net (R) | %95 GA | Skor r |
|---|---|---|---|---|---|
| 5m | 1.121 | 0,535 | −0,0246 | [−0,078, +0,029] | 0,040 |
| 15m | 412 | 0,332 | +0,0729 | [−0,019, +0,165] | 0,078 |
| 1h | 105 | 0,154 | +0,0669 | [−0,115, +0,248] | 0,235 |

Üçünde de hüküm **GIRIS_KENARI_YOK**. Yön umut verici (maliyet payı
düşüyor, skor 1h'de bilgi taşımaya başlıyor) ama **örneklem yetersiz**.

---

## 3. Yeni araç: `tools/exit_geometry.py`

Önerilen çıkış geometrisi aynı aday evreninde ölçüldü.

| | MEVCUT | ÖNERİLEN |
|---|---|---|
| stop_atr / tp1_r | 1,5 / 1,0 | 2,0 / 1,5 |
| be_activation_r | 1,0 | 0,75 |
| trail_activation_r / trail_atr | 0,75 / 2,0 | 1,0 / 1,0 |
| **Net beklenti** | **−0,5429 R** | **−0,4076 R** |
| %95 GA | [−0,603, −0,483] | [−0,466, −0,349] |
| Kazanma | %36,47 | **%36,11** |
| Maliyet (R) | 0,5338 | 0,4004 |
| TP1'e ulaşan | 511 | **184** |

**İyileşme var, kâr yok.** Kaynağı:

```
Beklenti iyileşmesi = +0,1353 R
Maliyet tasarrufu   = +0,1334 R   →  iyileşmenin %98,6'sı
```

Trailing mantığının ölçülebilir katkısı yok; kazanma oranı düştü,
TP1'e ulaşan işlem sayısı 511'den 184'e çöktü. "Kâr kilitleniyor"
iddiası veride görünmüyor.

### Yapısal kaldıraç

`maliyet_payı = maliyet_oranı / stop_kesri`. Çıkış parametreleri bunu
değiştirmez. Ölçülen: maliyet %0,214, stop %0,419 → pay **%51,0**.
%15 hedefi için stop **3,40×** genişlemeli. ATR ≈ √zaman ile
3,40² = 11,6 → 5dk × 11,6 ≈ **58 dk ≈ 1 saat**. Ölçüm doğruladı:
1h'de pay **%15,4**.

---

## 4. Düzeltilen gerçek hatalar

### 4.1 Bağlayıcı kısıt yanlış etiketleniyordu

`binding = min(components, key=...)` — tüm bileşenler 1,0 olduğunda
sözlüğün ilk anahtarı (`drawdown`) seçiliyordu. v5.3 raporundaki
*"bağlayıcı kısıt drawdown 6"* **yanlıştı**; taze hesapta hiçbir kısıt
bağlamıyordu. Artık `scale >= 1.0` ise **`binding = "none"`**.

### 4.2 Risk tabanı, ölçekleyicinin isteğini yukarı çekiyordu

Ölçekleyici 0,039 USDT hesaplıyor, `min_risk_usdt` tabanı 2,50 USDT'ye
çıkarıyordu (**64×**). "Asla yukarı ölçeklenmez" garantisi sessizce
deliniyordu.

Yeni: `below_floor_action = "block"` (varsayılan) → işlem **açılmaz**,
`OLCEK_TABAN_ALTINDA`. Eski davranış `"floor_up"` opt-in, İYİMSER etiketli.
Sayacı: `below_floor_blocks`.

### 4.3 TTL — tek kaynak ve çözürlük

`_limit_ttl_ms()` artık `config.exit.order_ttl_seconds`'tan okuyor.
Eski kod `timeframe_ms` (300.000 ms) döndürüyordu → canlıya göre **6,7×**.
Üstelik fark tam bir bar olduğu için `> ttl` karşılaştırması **hiç**
tetiklenmiyordu; sayaç sessizce 0 kalıyordu.

**`return 45000` tek başına YANLIŞ ve zararlıdır:** emir N. mumda
kurulup N+1. mumda denetleniyor; o fark 300.000 ms olduğundan **hiçbir
emir dolmazdı**. Bu dürüstlük değil, bozulma.

Doğru model — `ttl_model = "fine_window"` (varsayılan):
- Emir sinyal mumunun **kapanışında** kurulur (`created_ms = ts + tf`).
- Dolum yalnız TTL penceresine düşen **1m alt mumlarda** aranır.
- İnce veri yoksa 45 sn **çözülemez** → **doldurulmaz**, `ttl_cozulemez`.
- 1m'de 45 sn tam çözülemez (60s > 45s) → dolum **üst sınır**;
  kesin sonuç için tick/aggTrade gerekir.

`legacy_bar` opt-in'i eski davranışı tam geri verir (test opt-in'i,
İYİMSER). Rapor alanları: `ttl_model`, `ttl_cozulemeyen_aday`,
`ttl_1m_cozulen_aday`, `ttl_cozunurluk`.

### 4.4 n<30 yön iddiası yasak

`core/gates.py`: `MIN_DIRECTIONAL_N = 30`. Gölge özeti her neden için
`yön_iddiasi_gecerli` ve `yön_notu` üretiyor. v5.3'teki *"1 gözlem,
backtest ile aynı yönde"* ifadesi bu kuralla geçersiz.

### 4.5 Hedefli 1m indirmesinde KİLİTLENME (yeni bulundu)

Dürüst TTL modeli dolumu yalnız 1m alt mumda arıyor. Ama
`refine_fine_data()` yalnız **işlem gören** aralıklara 1m çekiyordu
(`trade_windows(result.trades)`). Sonuç bir kısır döngü:

```
1m yok → dolum yok → işlem yok → hedef pencere yok → 1m yok
```

İlk v5.4 doğrulama koşusu bu yüzden **0 işlem / net 0,0000** üretti.
Bu bir "strateji öldü" sonucu değil, **araç kilitlenmesi**.

**Düzeltme:** `candidate_windows()` eklendi; her adayın giriş barı
hedeflenir. `BacktestResult.gate_probe` alanı eklendi ve
`refine_fine_data()` aday + işlem pencerelerinin birleşimini kullanır.
Artık işlem olmasa da 1m iner.

### 4.6 Gecikme ölçeği uyuşmazlığı (yamada bulundu, düzeltildi)

`created_ms` mum kapanışına alınınca kaba bar farkı **tam 0** olur.
Eski gecikme karşılaştırması `ts_ms - created_ms < latency` → `0 < 350ms`
→ **True** → her dolum bloklanıyordu. İlk düzeltilmiş koşu yine
**0 işlem** üretti (kapsama %60,7'ye çıkmasına rağmen).

**Düzeltme:** `fine_window` modunda gecikme **alt mum ölçeğinde**
uygulanır — soru "alt mumun sonu gecikme penceresinden sonra mı?"
Gecikme alt mum aralığından büyükse blok geçerli kalır (test edildi).

**Ölçülen etki (30 gün, 6 sembol, aynı veri):**

| Model | Dolum | İşlem | Net |
|---|---|---|---|
| `legacy_bar` (eski, İYİMSER) | 21 | 21 | −71,9831 |
| `fine_window` (dürüst) | **11** | **11** | **−76,7337** |

Dolum **%48 azaldı**; 24 pencere çözüldü, 14'ü çözülemedi. Sıfır değil —
model artık çalışıyor ve canlıya daha yakın.

### 4.7 Kapsama ölçüsü artık karşılaştırılabilir DEĞİL

`real_coverage_ratio` paydası `path.steps()` çağrı sayısıdır. v5.4'te
bekleyen emir denetimi de bu fonksiyonu çağırdığı için çağrı sayısı
çok arttı. Bu yüzden v5.3'ün %92,9 kapsaması ile v5.4'ün oranı
**doğrudan karşılaştırılamaz** — veri kalitesi düşmedi, ölçüm tabanı
genişledi. Karşılaştırma için `real_1m_bars` mutlak sayısına bakılmalı.

### 4.8 Binance etiket dürüstlüğü

`infra/tick_verify.py` raporu artık `kisit_turu` (`YASAL_UYGUNLUK`,
`ERISIM_HATASI`, `YOK`) ve `unverified_gercek_anlami` içeriyor.

---

## 5. Çürütülen iddialar

| İddia | Gerçek |
|---|---|
| 518 sembol elendi, huni daraldı | Rapor: `excluded_symbols: []`, `allowed_symbols: 518`. **Hiçbiri elenmedi.** `warn` politikada `unverified` geçer. |
| Endpoint rotasyonu 451'i çözer | Gövde: *"restricted location according to 'b. Eligibility'"* → **yasal uygunluk**. fapi1/2 → 302, web sitesine. |
| `https://://binance.com` geçerli | Bozuk URL (netloc `":"`). `binance.us` ayrı borsa, vadeli kontratları farklı. |
| Beklenti +0,0311 R'ye geçti | **Uydurma.** Ölçüldü: −0,408 R (önerilen geometri). |
| Ortalama kazanç +1,10 R oldu | **Uydurma.** Kazanma oranı düştü. |
| 518 sembol aktif edildi | **Uydurma.** Zaten aktiflerdi. |
| Dolum %17'ye indi, hacim %77 azaldı | **Uydurma.** Böyle bir koşu yapılmadı. |

Proxy desteği (`BINANCE_BASE_URL` / `BINANCE_WS_URL`) ve 403/451
algılama kodda **zaten vardı**. Proxy ile kısıt aşmak kullanım şartları
uyumu kararıdır; kod bunu sessizce yapmaz.

---

## 6. Tespit edilen, kapatılmayan açık

**Funding modellenmiyor.** `engine.run(funding_rates=...)` destekliyor;
`tools/validate_strategy.py` **iletmiyor**. Futures için gerekli.
OKX funding geçmişi bağlanmalı (Adım 4).

---

## 7. Test ve kapılar

| | v5.3 | v5.4 |
|---|---|---|
| Test | 790 | **819** |
| Lint | temiz | temiz |
| Katı JSON | temiz | temiz |

+29 test: TTL dürüstlüğü (6), gölge örneklem guard'ı (2), giriş kenarı
aracı (10), risk tabanı/bağlayıcı (2), aday penceresi/kilitlenme (5),
gecikme ölçeği (2), sınır hesaplanamazlığı (2).

### 90 günlük doğrulama — v5.4

| | v5.3 | v5.4 |
|---|---|---|
| Birincil işlem | 14 | **12** |
| Net | −80,4766 | **−80,5192** |
| Gerçek 1m kapsama | %92,9 | %91,1 |
| Walk-forward | 242 işlem, 0/6, −390,61 | **104 işlem, 0/6, −301,69** |
| Monte Carlo kayıp | %99,9 | %99,7 |
| Hüküm | NO_EDGE | **NO_EDGE** |

Dürüst TTL işlem sayısını düşürdü; hüküm değişmedi.

### Sentetik sınır aralığı artık HESAPLANAMIYOR

Dürüst model sentetik yolda 45 sn'yi çözemez → iki sınır koşusu da
**0 işlem** verdi. Bunu "aralık sıfırı kapsıyor" diye raporlamak
yanıltıcı olurdu: bu bir **sonuç değil, ölçüm yokluğu**.
`bounds_interval.hesaplanabilir = false` + açık neden eklendi; kapı
uyarısı da buna göre ayrıştı. Sınır aralığı için gerçek 1m/tick gerekir.

Mekanik birim testleri `tests/helpers.py::legacy_ttl()` ile eski TTL
moduna opt-in oldu — onlar 1m yolu olmayan sentetik mumlarla dolum/
maliyet mekaniğini test ediyor, TTL penceresini değil. **Üretim
varsayılanı değişmedi.**

**Deterministik fixture parmak izi DEĞİŞTİ** — bu bilinçli bir model
değişikliğidir (dolum penceresi artık dürüst). Referans yeniden üretildi.
Sessiz kayma değildir; değişiklik bu günlüğde kayıtlıdır.

---

## 8. Yeni dosyalar

| Dosya | İçerik |
|---|---|
| `tools/entry_edge.py` | Kapısız giriş kenarı testi + permütasyon + zaman dilimi |
| `tools/exit_geometry.py` | İki geometri karşılaştırması + yapısal kaldıraç |
| `ANALIZ_v5.4_GIRIS_KENARI.md` | 9 bölüm — iddia denetimi ve tüm ölçümler |
| `docs/giris_kenari_v5.4.json` | 5m, 1.121 aday, ham satırlar dahil |
| `docs/giris_kenari_15m.json` | 15m, 412 aday |
| `docs/giris_kenari_1h.json` | 1h, 105 aday |
| `docs/cikis_geometri_v5.4.json` | İki geometrinin tam metrikleri |
| `docs/dogrulama_v5.4.json` / `.md` | 90 gün doğrulama |

---

## 9. Öncelik listesi — ölçümle yeniden sıralandı

**Çıkış parametre ayarı şu an YASAK** (giriş kenarı kanıtlanmadı).

1. **Zaman dilimi + evren hizalama:** 15m/1h, ilk 30–50 likit sözleşme.
   Kriter: maliyet payı ≤ %15.
2. **Örneklem büyütme:** ≥1 yıl, n ≥ 1.000 aday.
   Kriter: simetrik çıkış GA alt sınırı > 0 ve permütasyon p < 0,05
   (çoklu karşılaştırma düzeltmeli).
3. **Skor kalibrasyonu:** dilim bazlı ileri getiri monotonluğu.
4. **Funding bağlanması.**
5. **Tick dolum modeli + markout.**
6. **Ancak kenar varsa çıkış tasarımı.**
7. **Canlıya geçiş:** ≥300 OOS işlem, beklenti > +0,1R, bootstrap alt
   sınır > 0, PF > 1,3, çoklu sembol/TF tutarlılığı.

**Hiçbiri bugün karşılanmıyor. Gerçek para YASAK; pozisyon başına azami
kayıp 2,5–5 USDT.**

---

## 10. Açık sınırlar

- Mum içi sıra bilinmez → iki sınır raporlandı (5m'de belirsiz bar %0,36).
- 15m/1h yeniden örnekleme: 5m'den toplandı, emir defteri mikro yapısı yok.
- TP1'de tam çıkış modellendi; kısmi çıkış yok.
- Funding modellenmiyor.
- Evren 6 majör; canlı mikro altları da tarıyor, orada maliyet ölçülmedi.
- 90 gün tek rejim; boğa/ayı/yatay ayrımı yok.
- Permütasyon saat eşleşmeli; otokorelasyon tam kontrol edilmiyor.
- Binance futures tick/maliyet doğrulanamıyor (yasal kısıt).
- Testnet yok; paper gerçek emir defterini simüle etmiyor.

---

## 11. Yeniden üretme

```bash
python3 -m tools.entry_edge --days 90 --permutations 500 \
    --costs docs/maliyet_olcum_v5.2.json --out docs/giris_kenari_v5.4.json
python3 -m tools.entry_edge --days 90 --resample-minutes 60 \
    --costs docs/maliyet_olcum_v5.2.json --out docs/giris_kenari_1h.json
python3 -m tools.exit_geometry --days 90 \
    --costs docs/maliyet_olcum_v5.2.json --out docs/cikis_geometri_v5.4.json
python3 -m tools.validate_strategy --days 90 --fine-mode targeted \
    --costs docs/maliyet_olcum_v5.2.json --out docs/dogrulama_v5.4.json
python3 -m tools.make_reference --from docs/dogrulama_v5.4.json
python3 -m pytest -q && python3 -m ruff check .
python3 -m tools.package_release --out-dir ..
```
