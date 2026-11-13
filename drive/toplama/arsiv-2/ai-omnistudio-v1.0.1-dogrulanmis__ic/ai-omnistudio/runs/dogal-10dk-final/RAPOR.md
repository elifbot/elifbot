# AI OmniStudio — Koşu Raporu `dogal-10dk-final`

**Sürüm:** 1.0.0 · **Mod:** PAPER · **Durum:** `COMPLETED`

> **Gerçek borsa emri gönderilmedi.** Veri gerçek piyasa verisidir; defter sanaldır. Bu rapor kârlılık kanıtı değildir.

> **Profil:** `natural` — üretim eşikleri, filtre gevşetmesi yok.

## 1. Süre protokolü

| Ölçüm | Değer |
|---|---:|
| Toplam monotonic (s) | 780.017 |
| Aktif pencere (s) | 600.462 |
| Drenaj (s) | 120 |
| Aktif pencere tamamlandı | True |

Monotonic ölçüm. Süreksizlik varsa COMPLETED yazılmaz. Bütün VM durduğunda gözlemci de durur; uptime garantisi yok.

## 2. Karar hattı

| Sayaç | Değer |
|---|---:|
| ticks | 105089 |
| signals | 0 |
| decisions | 0 |
| accepted | 0 |
| rejected | 0 |
| council_vetoes | 0 |
| risk_blocks | 0 |
| quote_ok | 5170 |
| quote_fail | 270 |

## 3. PAPER icra ve finansal fotoğraf

| Ölçüm | Değer |
|---|---:|
| Kapanan işlem | 0 |
| Kapanmış net (USDT) | 0 |
| Gerçekleşen net | 0.0 |
| Ödenen ücret | 0.0 |
| Açık unrealized | 0 |
| Toplam equity | 10000 |
| Kazanma oranı (%) | 0.0 |
| Maks drawdown | 0.0 |
| Ortalama tutma (s) | 0.0 |

total_equity açık unrealized içerir; GERÇEKLEŞMİŞ kâr değildir. Çıkış ücretleri düşülmemiştir.

## 4. 20 YZ konseyi

**Mod:** `RULE_BASED_QUANT` · **Üye:** 20 · **Anahtarlı:** 0

RULE_BASED_QUANT modunda hiçbir YZ çağrısı yapılmaz; çıktı deterministik kural denetimidir.

| Sayaç | Değer |
|---|---:|
| live_calls | 0 |
| rule_calls | 0 |
| approved | 0 |
| vetoed | 0 |
| quorum_failures | 0 |
| provider_errors | 0 |

## 5. Gerçek veri kaynakları

Erişilebilir: binance_vision, gateio

| Uç | Erişim | HTTP | WS mesaj | Reconnect | REST ok/fail |
|---|---|---:|---:|---:|---|
| binance_vision | OK | 200 | 41604 | 0 | 4222/0 |
| gateio | OK | 200 | 63494 | 0 | 4252/0 |

## 6. Süreklilik ve görev denetimi

- Boşluk sayısı: **0**
- Maks poll gecikmesi: 0.047971s
- Maks saat sapması: 0.000171s
- Görev hataları: `{}`
- Alarm sayısı: 0

## 7. Ölçülen süreler

| İşlem | Çağrı | Toplam s | Maks ms |
|---|---:|---:|---:|
| tick_total | 105089 | 4.150843 | 2.223 |
| detector_eval | 105089 | 3.844753 | 2.219 |
| policy_eval | 0 | 0.0 | 0.0 |
| council_eval | 0 | 0.0 | 0.0 |
| execution | 719 | 0.008782 | 0.621 |
| state_write | 0 | 0.0 | 0.0 |
| candle_refresh | 9 | 392.69114 | 81195.489 |
| quote_refresh | 69 | 505.29439 | 20699.023 |
| breadth_update | 719 | 0.802496 | 2.896 |

Bu süreler kapsayıcı duvar süresidir; CPU profili değildir. İç içe ölçümler TOPLANMAZ.

## 8. Dürüstlük beyanı

- Veri: `REAL_MARKET_DATA`
- Emir: `PAPER_ONLY_NO_EXCHANGE_ORDERS`
- YZ modu: `RULE_BASED_QUANT`
- Kârlılık iddiası: **False**

Küçük PAPER örneklemi kârlılık veya yürütme güvenilirliği kanıtı değildir. Açık unrealized gerçekleşmiş kâr değildir. Stop mesafesi maksimum zarar garantisi değildir.
