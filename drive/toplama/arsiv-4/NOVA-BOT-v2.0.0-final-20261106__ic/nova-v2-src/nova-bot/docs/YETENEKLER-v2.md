# NOVA-BOT v2.0.0 — yetenek envanteri ve kaynak eşlemesi

Bu belge, "çalışan bottaki (NOVA) eksik yetenekleri, çalışmayan bottan (ACARBOT)
alarak tamamla" isteğinin **denetlenebilir** kaydıdır. Her satır: yetenek, kimde
vardı, v2'de nasıl uygulandı, hangi testle kilitlendi.

> PAPER only · gerçek emir yolu yok · özel API anahtarı yok · YZ servisi yok.
> Hiçbir yetenek kârlılık iddiası üretmez.

## 1. Envanter tablosu

| # | Yetenek | NOVA v1 | ACARBOT (Python) | acarbot HTML v3.4 | NOVA v2 | Test |
|---|---|:--:|:--:|:--:|:--:|---|
| 1 | WebSocket kapanmış mum akışı | ✅ | ✗ (REST anket) | ✗ (tarayıcı REST) | ✅ | `test_nova.py` |
| 2 | 3 borsa (Binance/OKX/Gate) | ✅ | ✗ (yalnız Gate) | ✗ (Binance/OKX) | ✅ | `test_nova.py` |
| 3 | Funding oranı okuma + muhasebe | ✅ | ✗ (yalnız kaçınma) | ✗ | ✅ | `test_nova.py` |
| 4 | Likidasyon mesafesi kapısı | ✅ | ✗ | kaba (stop<liq) | ✅ | `test_nova.py` |
| 5 | Evren filtresi (hacim/yaş/çapraz borsa) | ✅ | ✗ sabit 20 sembol | ✗ | ✅ | `test_nova.py` |
| 6 | **Confluence 10 filtre oylaması** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 7 | **ADX (Wilder, seri)** | kısmi (tek değer) | ✗ | ✅ | ✅ **seri** | `test_yetenek.py` |
| 8 | **Stochastic %K/%D** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 9 | **OBV + SMA(10)** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 10 | **Günlük VWAP** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 11 | **CCI(20)** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 12 | **Supertrend(10,3)** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 13 | **DCA güvenlik emirleri (LONG)** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 14 | **Maliyet/hareket kapısı (EDGE_BELOW_COST)** | ✗ | ✅ | ✗ | ✅ **eklendi** | `test_yetenek.py` |
| 15 | **Mum sürekliliği/bütünlük denetimi** | ✗ | ✅ | ✗ | ✅ **eklendi** | `test_yetenek.py` |
| 16 | **Sembol başına cooldown** | ✗ | ✗ | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 17 | **Maks. tutma süresi (mum)** | ✅ (sn) | ✗ | ✅ | ✅ **mum + sn** | `test_yetenek.py` |
| 18 | **Kill switch (pozisyon kapatma seçenekli)** | ✗ | ✗ (equity) | ✅ | ✅ **eklendi** | `test_yetenek.py` |
| 19 | **Risk-bazlı pozisyon boyu** | ✅ (%risk) | ✅ | ✅ (v6) | ✅ | `test_yetenek.py` |
| 20 | **Piyasa genişliği (breadth) filtresi** | ✗ | kısmi (kullanılmadı) | ✗ | ✅ **eklendi** | `test_yetenek.py` |
| 21 | 20 üyeli YZ konseyi | ✗ (bilinçli) | ✅ iskelet (anahtarsız **çağrılmıyor**) | ✗ | ✗ **eklenmedi** | — |
| 22 | Tarayıcı arayüzü / grafik / laboratuvar | ✗ (CLI) | ✗ | ✅ | ✗ **eklenmedi** | — |
| 23 | HTML↔Python parite testi | ✗ | ✅ 1.800 karar | — | ✗ **eklenmedi** | — |

## 2. Eklenmeyenler ve gerekçeleri (dürüstlük)

**#21 — YZ konseyi (20 üye).** ACARBOT'ta iskelet var; anahtar olmadığı için
`live_calls = 0`, mod `RULE_BASED_QUANT`. Yani "20 YZ onayı" **fiilen çalışmıyor**.
Çalışmayan bir yeteneği kopyalamak "mükemmele geçiş" değil, sahte bir onay
katmanı üretmek olurdu. NOVA bu yüzden konsey eklemedi; `SONUC.json` içinde
`council_or_llm: "YOK"` yazıyor. Anahtar sağlanırsa ayrı bir sürümde eklenebilir.

**#22 — HTML arayüzü.** NOVA bir CLI/pipeline botu; tarayıcı terminali (grafik,
optimizasyon laboratuvarı, CSV içe aktarma) farklı bir ürün. Eklemek botun
çekirdeğini değiştirmez, yalnız görsel katman olur. İsterseniz ayrı bir
görevde yapılabilir.

**#23 — HTML parite testi.** NOVA'nın HTML kaynağı yok; parite testi edilecek
bir JavaScript motoru bulunmuyor. Confluence formüllerini birebir port ettim ve
Python testleriyle kilitledim, ama "HTML ile 1.800 karar aynı" iddiası
**kurulamaz** — kaynak yok.

## 3. Confluence portunun birebir eşleştiği yerler
HTML `CFG` varsayılanları ve formüller doğrudan Python'a çevrildi:

| HTML | NOVA v2 |
|---|---|
| ADX(14), alpha = 1/14, Wilder (adjust=False) | `adx_series()` aynı |
| Stoch(14) → SMA(3) → SMA(3) | `stochastic(14,3,3)` aynı |
| OBV + SMA(10) | `obv_series(10)` aynı |
| VWAP, UTC gün sıfırlamalı (ts//86400000) | `vwap_series()` aynı |
| CCI(20), tipik fiyat, 0.015×ort. sapma | `cci_series(20)` aynı |
| Supertrend(10, 3) | `supertrend_series(10,3)` aynı |
| 10 oy, eşik `confTh` clamp(2..8) | `confluence_skoru()` aynı, varsayılan 4 |
| DCA: adım %, çarpan, TP %, stop %, **yalnız LONG** | `DcaPlan` + `dca_ekle()` aynı |

**Fark (bilinçli):** HTML DCA'da stop yüzdesi likidasyonun içine sığdırılıyor;
NOVA'da da aynı kırpma var **ama** NOVA ayrıca `LIQ_TOO_CLOSE` kapısını önden
uyguluyor (HTML'de bu kapı yalnız `stop <= liq` kontrolü).

## 4. Ölçülen etki (15 dakikalık final tarama)
Bkz. `runs/nova-v2-final/RAPOR.md` ve `KARSILASTIRMA-ve-YETENEKLER.md`.
Özet: `--min-edge-ratio 1.15` ACARBOT'un kapısıyla aynı eşik; bu eşikle işlem
sayısı **ciddi biçimde** düşer (ACARBOT'ta 11 sinyalin 10'u burada reddedildi).
Bu bir kusur değil, tercih: az ve maliyeti karşılayan işlem. Varsayılan
`min_edge_ratio = 0` (kapalı) bırakıldı; açmak için CLI anahtarı var.

## 5. Test envanteri
- `tests/test_nova.py` — 35 test (v1 çekirdeği; regresyon kilidi)
- `tests/test_yetenek.py` — 23 test (v2 yetenekleri)
- **Toplam 58 test, tamamı çevrimdışı** (ağ gerekmez).
