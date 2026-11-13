# ACARBOT FINAL v1.6 — RVOL Sahte-Hacim Düzeltmesi (7 Kasım 2026)

## Kullanıcı sorusu
"91 şüpheli sinyal engellendi — bunlar gerçekten şüpheli miydi, yoksa
gerçekten doğru yöne mi gitti? Şu an her şeye şüpheli diyor, araştır."

## Kök neden (kanıtlı)
Canlı spike dedektörü hacmi `quote = baz_hacim × fiyat` olarak hesaplıyordu
(özellikle OKX). Fiyat oynadığında, HİÇ İŞLEM OLMASA BİLE quote hacmi
değişiyor → sahte hacim deltası → RVOL 100-500x şişiyor → gerçek sinyaller
"şüpheli/veri hatası" diye engelleniyordu.

**Kanıt:** Engellenen coinlerin (MRNA, MINIMAX, ZRX, CRO, COIN) gerçek 5dk
mum verisinde max/ortalama hacim oranı 8-16x iken, canlı filtre 100-500x
bildiriyordu. Matematik: 24s baz hacim 100.000 birim + %0,5 fiyat hareketi
= işlem yokken ~500 birim sahte hacim → RVOL ~100x.

## Düzeltme
- `Ticker`'a `base_volume_24h` alanı eklendi (fiyattan bağımsız baz hacim).
- Binance: miniTicker `v` alanı (baz hacim) kullanılır.
- OKX: `volCcy24h` (baz hacim) doğrudan kullanılır, fiyatla ÇARPILMAZ.
- Executor: spike dedektörüne baz hacim deltası verilir (quote/fiyat yok).
- Baz hacim yoksa eski quote yoluna geri dönülür (geriye uyum).

## İkincil düzeltme: SQLite thread hatası
v1.5'in paralel değerlendirmesi `asyncio.to_thread` ile SQLite'a farklı
thread'den erişiyordu → "SQLite objects created in a thread..." hatası.
v1.6: değerlendirme ana event loop'ta (tek tüketici kuyruğu sıralı erişim).

## Sonuç (canlı, tam pazar 1046 feed)
| Metrik | v1.5 (hatalı) | v1.6 (düzeltilmiş) |
|---|---|---|
| RVOL "şüpheli" engel | ~300 / 28 dk | **0** |
| SQLite thread hatası | var | **0** |
| Gerçek giriş emri | 0 | **dakikalar içinde 4+** |

İlk gerçek işlemler: DGBUSDT LONG, FTTUSDT SHORT (aç+kapa), ZECUSDT SHORT,
SOFTBANK LONG. Kullanıcının şüphesi DOĞRUYDU: engeller gerçek fırsatları
önlüyordu.

## Test
**258/258 geçti** (250 v1.5 + 8 hacim düzeltmesi testi).
Yeni testler kilitler: fiyat oynasa bile baz hacim sabitse spike girdisi 0;
baz hacim artışı fiyattan bağımsız doğru delta; baz hacim quote'a öncelikli.

## Not
Sanity cap (RVOL>100) hâlâ aktif — ama artık GERÇEK aşırı sapmaları
yakalar, fiyat oynaklığını değil. PAPER ONLY.
