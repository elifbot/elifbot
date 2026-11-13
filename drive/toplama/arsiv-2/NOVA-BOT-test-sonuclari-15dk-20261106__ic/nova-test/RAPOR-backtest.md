# NOVA-BOT — geriye dönük test

**Sembol:** 60 · **Sembol başına mum:** 999 (~16.65 saat) · **Parametre:** skor≥3, chop<62.0

> Gerçek kamu mumlarıyla PAPER simülasyonu. Kârlılık kanıtı değildir.

| Ölçüm | Değer |
|---|--:|
| İşlem | 2212 |
| Net | -506.9666 |
| Kazanma % | 29.97 |
| Profit factor | 0.653 |
| Ort. R | -0.063 |
| Maks. düşüş | 507.5341 |
| Başlangıç | 1000.0 |
| Bitiş | 493.0334 |

**Çıkış dağılımı:** `STOP`×1484, `TAKE_PROFIT`×647, `MAX_HOLD`×54, `EQUITY_HALT`×27

## Sınırlar

- Tek pozisyon/sembol, aynı mumda stop+hedef çakışırsa STOP varsayıldı.
- Funding sabit 0,01%/8saat varsayımı (geçmiş oran arşivi yok).
- Kısa pencere kârlılık kanıtı değildir.
- Gerçek emir, kısmi dolum ve likidasyon motoru yok.
