# AI OmniStudio — Koşu Raporu `yasam-dongusu-tani`

**Sürüm:** 1.0.0 · **Mod:** PAPER · **Durum:** `COMPLETED`

> **Gerçek borsa emri gönderilmedi.** Veri gerçek piyasa verisidir; defter sanaldır. Bu rapor kârlılık kanıtı değildir.

> ⚠️ **TANI KOŞUSU — DOĞAL KANIT DEĞİL.** Profil: `lifecycle-diagnostic`. Eşikler, yalnız pozisyon aç/kapat yaşam döngüsünü gerçek veri üzerinde doğrulamak için gevşetildi. Bu koşunun işlem sayısı, PnL'i veya isabet oranı strateji değerlendirmesinde KULLANILAMAZ. Doğal üretim eşikleri için `configs/default.json` ile koşun.

## 1. Süre protokolü

| Ölçüm | Değer |
|---|---:|
| Toplam monotonic (s) | 320.69 |
| Aktif pencere (s) | 240.225 |
| Drenaj (s) | 40.0 |
| Aktif pencere tamamlandı | True |

Monotonic ölçüm. Süreksizlik varsa COMPLETED yazılmaz. Bütün VM durduğunda gözlemci de durur; uptime garantisi yok.

## 2. Karar hattı

| Sayaç | Değer |
|---|---:|
| ticks | 32613 |
| signals | 844 |
| decisions | 604 |
| accepted | 1 |
| rejected | 603 |
| council_vetoes | 0 |
| risk_blocks | 6 |
| quote_ok | 8377 |
| quote_fail | 71 |

### Kapı ret dağılımı

| Kapı | Ret |
|---|---:|
| `EDGE_BELOW_COST` | 546 |
| `ATR_OUT_OF_BAND` | 51 |
| `ACCEPTED` | 7 |

## 3. PAPER icra ve finansal fotoğraf

| Ölçüm | Değer |
|---|---:|
| Kapanan işlem | 1 |
| Kapanmış net (USDT) | -0.335406 |
| Gerçekleşen net | -0.335406 |
| Ödenen ücret | 0.10897 |
| Açık unrealized | 0 |
| Toplam equity | 9999.664594 |
| Kazanma oranı (%) | 0.0 |
| Maks drawdown | 0.335406 |
| Ortalama tutma (s) | 68.849 |

total_equity açık unrealized içerir; GERÇEKLEŞMİŞ kâr değildir. Çıkış ücretleri düşülmemiştir.

### Çıkış nedenleri

- `STOP_LOSS`: 1

## 4. 20 YZ konseyi

**Mod:** `RULE_BASED_QUANT` · **Üye:** 20 · **Anahtarlı:** 0

RULE_BASED_QUANT modunda hiçbir YZ çağrısı yapılmaz; çıktı deterministik kural denetimidir.

| Sayaç | Değer |
|---|---:|
| live_calls | 0 |
| rule_calls | 1 |
| approved | 1 |
| vetoed | 0 |
| quorum_failures | 0 |
| provider_errors | 0 |

## 5. Gerçek veri kaynakları

Erişilebilir: binance_vision, gateio

| Uç | Erişim | HTTP | WS mesaj | Reconnect | REST ok/fail |
|---|---|---:|---:|---:|---|
| binance_vision | OK | 200 | 12056 | 0 | 4850/0 |
| gateio | OK | 200 | 20561 | 0 | 4852/0 |

## 6. Süreklilik ve görev denetimi

- Boşluk sayısı: **0**
- Maks poll gecikmesi: 0.004828s
- Maks saat sapması: 1.2e-05s
- Görev hataları: `{}`
- Alarm sayısı: 0

## 7. Ölçülen süreler

| İşlem | Çağrı | Toplam s | Maks ms |
|---|---:|---:|---:|
| tick_total | 32613 | 1.748178 | 0.634 |
| detector_eval | 32613 | 1.51005 | 0.494 |
| policy_eval | 604 | 0.150588 | 2.358 |
| council_eval | 1 | 0.000243 | 0.243 |
| execution | 281 | 0.005856 | 0.333 |
| state_write | 605 | 0.15895 | 6.916 |
| candle_refresh | 10 | 20.185227 | 2504.146 |
| quote_refresh | 72 | 107.248725 | 2412.938 |
| breadth_update | 280 | 0.150271 | 1.085 |

Bu süreler kapsayıcı duvar süresidir; CPU profili değildir. İç içe ölçümler TOPLANMAZ.

## 8. Dürüstlük beyanı

- Veri: `REAL_MARKET_DATA`
- Emir: `PAPER_ONLY_NO_EXCHANGE_ORDERS`
- YZ modu: `RULE_BASED_QUANT`
- Kârlılık iddiası: **False**

Küçük PAPER örneklemi kârlılık veya yürütme güvenilirliği kanıtı değildir. Açık unrealized gerçekleşmiş kâr değildir. Stop mesafesi maksimum zarar garantisi değildir.
