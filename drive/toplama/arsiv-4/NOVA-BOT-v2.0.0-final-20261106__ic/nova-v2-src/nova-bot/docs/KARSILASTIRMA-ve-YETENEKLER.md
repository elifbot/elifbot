# ACARBOT (iki sürüm) → NOVA-BOT v2.0.0 : yetenek aktarımı ve final sürüm notu

Bu belge üç kaynağı karşılaştırır ve **her aktarılan yeteneğin nereden geldiğini**
yazar:

1. **ACARBOT V10 (Python)** — mailden indirilen `ACARBOT-V10-…zip` (`acarbot/` + `omnistudio/`, ~6.100 satır)
2. **acarbot-system v3.4 "MEGA MOTOR" (HTML)** — ekteki `acarbot-system (5).html` (317 KB, 5.947 satır)
3. **NOVA-BOT v1.0.0** — çalışan bot (3 borsa, WS, 1m)

Sonuç: **NOVA-BOT v2.0.0** — 58 çevrimdışı test, 2.000+ satır, tek bağımlılık (aiohttp).

---

## 1. Attığınız HTML'in (v3.4) içinde ne var?

| Yenilik | v3.3 → v3.4 farkı | NOVA v2'ye alındı mı |
|---|---|:--:|
| **Confluence 10 filtre oylaması** (yeni strateji) | EMA dizilişi + MACD kesişimi + RSI bölgesi + ADX hizası + Stoch kesişimi + OBV akışı + CCI + Supertrend + VWAP + BB kırılımı, eşik 4 | ✅ birebir port |
| Yeni göstergeler | ADX(14, Wilder), Stoch(14,3,3), OBV+SMA10, günlük VWAP, CCI(20), Supertrend(10,3) | ✅ birebir port |
| **DCA güvenlik emirleri** (LONG) | adım %, marj çarpanı, TP %, stop %; stop likidasyonun içine kırpılır | ✅ port (yalnız LONG) |
| **Cooldown** (sembol başına) | kapanıştan sonra N dk yeniden giriş yok | ✅ `--cooldown-dk` |
| **Maks. tutma (mum)** | `maxHoldMum` → MAX_HOLD | ✅ `--max-hold-mum` |
| **Kill switch seçeneği** | `killPozKapat` — kill switch pozisyonları kapatır mı | ✅ `kill_close_positions` |
| Risk-bazlı boyut (`pozModu: risk`) | sabit marj yerine risk/stop mesafesi | ✅ NOVA'da zaten vardı |
| Tarayıcı arayüzü, grafik, lab, CSV | — | ✗ (farklı ürün, bkz. §4) |

> Not: HTML'in kendi içinde `finL` (başka bir Python projesi) referansları var;
> formülleri o mantığa göre yazılmış. Ben formülleri **HTML'deki JS kodundan**
> okuyup Python'a çevirdim, dışarıdan kopyalamadım.

## 2. ACARBOT Python'da olup NOVA'da olmayan yetenekler

| Yetenek | ACARBOT'ta nasıl | NOVA v2'de nasıl | Durum |
|---|---|---|---|
| **`EDGE_BELOW_COST` kapısı** | maliyet = 11 bps ücret + 4 bps kayma + makas; hareket = 0,35×ATR; oran < 1,15 → reddet | `edge_dengesi()` + `--min-edge-ratio 1.15` | ✅ |
| **Mum sürekliliği** | `CANDLE_GAP` (tek eksik mum → reddet), `BAD_CANDLE`, `STALE_CANDLE` | `mum_denetimi()` — tek eksik mum hoş görülür (WS kopmaları için), 2+ eksik = GAP | ✅ (uyarlanmış) |
| **Kill switch (equity/zarar)** | `breaker_tripped` → yeni giriş yok | NOVA'da `halt` (günlük %2 / 4 ardışık zarar) zaten vardı; **+ `--kill`** ile elle kill switch ve pozisyon kapatma seçeneği | ✅ |
| **Sembol başına cooldown** | yok (yalnız `girisEngel`) | `COOLDOWN` sayacı | ✅ (HTML'den) |
| **20 üyeli YZ konseyi** | iskelet var, anahtar yok → `live_calls 0`, karar `RULE_BASED_QUANT` | **eklenmedi** — gerekçe §4 | ✗ |
| **HTML↔Python parite testi** | 1.800 karar / 0 uyuşmazlık | NOVA'nın HTML kaynağı yok | ✗ |
| **126 test** | 111 OmniStudio + 15 | 58 test (35 çekirdek + 23 yetenek), hepsi çevrimdışı | ✅ (kapsam farklı) |

## 3. NOVA'da olup ACARBOT'ta olmayanlar (korunan üstünlükler)

- **WebSocket** ile 1m kapanmış mum akışı (ACARBOT: 5m REST anketi; 15 dk'da 60 mum vs 630 mum)
- **3 borsa**: Binance USD-M + OKX swap + Gate.io USDT (ACARBOT Python: yalnız Gate)
- **Funding muhasebesi**: oran okunur, pozisyona işlenir, 3 dk kala giriş yasak (ACARBOT: yalnız kaçınma)
- **Likidasyon kapısı**: `LIQ_TOO_CLOSE`, `MMR_INVALID` (ACARBOT Python'da yok)
- **Evren filtresi**: 24s hacim + ürün yaşı + hem-Binance-hem-OKX doğrulaması (kripto dışı hisse sözleşmeleri elenir)
- **Mikro-yapı kapıları**: `SPREAD`, `STALE_QUOTE`, `PRICE_DRIFT`, `NO_QUOTE`
- **Mum içi çift tetik koruması**: `stop_window_ms`

## 4. Eklenmeyenler ve dürüst gerekçeler

1. **YZ konseyi (20 üye).** ACARBOT'ta iskelet var ama anahtar olmadığı için hiç
   çağrılmıyor (`live_calls: 0`). Çalışmayan bir yeteneği kopyalamak "mükemmele
   geçiş" değil, sahte bir onay katmanı olur. NOVA v2 de YZ çağırmaz ve bunu
   `SONUC.json` içinde `council_or_llm: "YOK"` olarak yazar.
2. **Tarayıcı terminali.** NOVA bir CLI/pipeline botu. Grafik + laboratuvar +
   CSV içe aktarma katmanı çekirdeği değiştirmez, ayrı bir ürün olur.
3. **HTML parite testi.** NOVA'nın karşılaştıracağı bir JS motoru yok. Confluence
   formüllerini birebir port ettim ve Python testleriyle kilitledim; "HTML ile
   1.800 karar aynı" iddiası **kurulamaz**.
4. **Gerçek emir / özel API.** Hiçbir sürümde yok, olmayacak.

## 5. v2'de ölçülüp düzeltilen hata (dürüst kayıt)

İlk v2 denemesinde `MAX_HOLD_BARS` sayacı **tüm pozisyonlar için her sembolün
mumunda** artıyordu. 45 sembolde 1 dakikada 45 artınca 20 mumluk sınır ~30
saniyede doluyor ve **8 pozisyonun 8'i de `MAX_HOLD_BARS` ile kapanıyordu**
(hiçbiri stop/hedef görmüyordu). Yakalandı, düzeltildi: sayaç artık sembolün
**kendi** kapanmış mumunu sayıyor (`bar_sayaci(key, …)`), regresyon testi eklendi.
Düzeltilmiş koşunun sonuçları `runs/nova-v2-final/` altındadır.

## 6. v2 CLI — tek bakışta

```bash
python3 nova.py live --minutes 15 --symbols 45 \
    --strateji confluence --conf-th 5 \
    --cooldown-dk 5 --max-hold-mum 30 \
    --min-edge-ratio 1.15 \
    --out runs/nova-v2-final
```
| Anahtar | Kaynak | Varsayılan |
|---|---|---|
| `--strateji {skor,confluence}` | HTML v3.4 | `skor` |
| `--conf-th` | HTML v3.4 | 4 |
| `--min-edge-ratio` | ACARBOT Python | 0 (kapalı) |
| `--cooldown-dk` | HTML v3.4 | 0 |
| `--max-hold-mum` | HTML v3.4 | 0 |
| `--dca --dca-adim --dca-adet` | HTML v3.4 | kapalı |
| `--breadth-guard` | ACARBOT fikri (kullanılmıyordu) | 0 (kapalı) |
| `--kill` | HTML v3.4 + ACARBOT | kapalı |

## 7. Sınırlar (değişmedi)
PAPER only · gerçek emir 0 · özel API yok · kârlılık iddiası yok · kısmi dolum
ve gerçek tasfiye motoru modellenmedi · 15 dakikalık koşu istatistiksel kanıt
değildir · sonuçlar KISMİ.
