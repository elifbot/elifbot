# Canlı akış testi — 30 dakika, OKX WebSocket

**Koşu:** `43591136539` · 14 Kasım 2026 11:40–12:10 UTC · GitHub Actions (ubuntu-latest)
**Akış:** `wss://ws.okx.com:8443/ws/v5/public` → `trades` kanalı, 20 sembol, 5 saniyelik bar
**Ölçek:** **273.024 tick · 5.428 bar · 20 sembol · 1.800 saniye · kopma 0**

Semboller (24s USD hacme göre en likit): BTC, ETH, SOXL, SOL, ZEC, SNDK, AKE, NVDA, XRP, HYPE ...

## Sonuçlar

| Sürüm | İşlem | WR | PF | Realize | Açık poz | Açık PnL |
|---|---:|---:|---:|---:|---:|---:|
| v1 kbot (EMA9/21 + hacim) | 9 | %22,2 | 0,05 | **−24,10 $** | 11 | −0,24 $ |
| v2 kbot2 (rejim + komite) | 13 | %7,7 | 0,08 | **−44,97 $** | 18 | −15,11 $ |
| **v3 kbot3 (kanıt eşikleri)** | 10 | **%70,0** | **1,90** | **+27,12 $** | 3 | −0,01 $ |

v3 çıkış dağılımı: izli kâr 6 · stop 3 · süre 1 → **kâr kilidi çalışıyor**.
v2 çıkış: stop 4 · süre 9 → rejim sinyalleri canlı akışta gürültü üretiyor.

## Yorum — abartmadan
1. **v3 ilk kez canlı akışta pozitif:** +27,12 $, PF 1,90, WR %70.
   Kâr kilidi sayesinde 6 işlem kârla kapandı, 3 stop (−30 $) sınırlı kaldı.
2. **Örneklem küçük:** 10 işlem. İstatistiksel olarak "kanıtlandı" denemez; 30 dakika tek oturum.
3. **v1/v2 net zararda.** EMA kesişimi ve rejim-komite sinyalleri 5 sn barında gürültüye yenik düşüyor.
4. **Önceki 14 saatlik klines testiyle çelişki:** orada v3 190 işlemde −549 $ yaptı. Burada 10 işlemde +27 $.
   Sebep: işlem sayısı ve piyasa rejimi farkı. Aynı bot, farklı pencere → farklı sonuç. **Tek koşuya güvenilmez.**

## Doğrulama
- `runs/akis_20261114_114030/ozet.json` — ham sonuç
- `runs/akis_tani.txt` — dakika dakika tick/bar sayacı, WS durumu (`bagli` boyunca)
- KOŞULLAR: taker komisyon %0,05×2, stop −10 $ net, 500 $ notional, kasa 1.000 $

## Sonraki adım
Aynı testi **6–12 saat** koşmak (Actions'ta 6 job, paralel 20 sembol) → 100+ işlem.
O zaman v3'ün PF'si anlam kazanır. `akis_test.yml` `--dakika 360` ile hazır.
