# ACARBOT — DEĞİŞİKLİK GÜNLÜĞÜ DİZİNİ

Her satır tek bir sürüme aittir. Sürümsüz changelog dosyası yoktur;
dosya adı ile iç sürüm `tools/package_release.py` tarafından
`app.__version__` üzerinden tek kaynaktan türetilir ve tutarlılık
denetiminden geçmeyen paket YAZILMAZ.

| Sürüm | Dosya | Boyut | Başlık |
|---|---|---|---|
| v1.0 | `DEGISIKLIKLER_FINAL_v1.0.md` | 3,113 B | ACARBOT FINAL v1.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v1.1 | `DEGISIKLIKLER_FINAL_v1.1.md` | 4,242 B | ACARBOT FINAL v1.1 — Değişiklik Günlüğü (7 Kasım 2026) |
| v1.2 | `DEGISIKLIKLER_FINAL_v1.2.md` | 2,774 B | ACARBOT FINAL v1.2 — Değişiklik Günlüğü (7 Kasım 2026) |
| v2.0 | `DEGISIKLIKLER_FINAL_v2.0.md` | 14,403 B | ACARBOT v2.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v3.0 | `DEGISIKLIKLER_FINAL_v3.0.md` | 8,742 B | ACARBOT v3.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v3.1 | `DEGISIKLIKLER_FINAL_v3.1.md` | 10,399 B | ACARBOT v3.1 — Değişiklik Günlüğü (7 Kasım 2026) |
| v4.0 | `DEGISIKLIKLER_FINAL_v4.0.md` | 14,931 B | ACARBOT v4.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v5.0 | `DEGISIKLIKLER_FINAL_v5.0.md` | 6,204 B | ACARBOT FINAL v5.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v5.1 | `DEGISIKLIKLER_FINAL_v5.1.md` | 10,997 B | ACARBOT FINAL v5.1 — Değişiklik Günlüğü (7 Kasım 2026) |
| v5.2 | `DEGISIKLIKLER_FINAL_v5.2.md` | 12,915 B | ACARBOT FINAL v5.2 — DEĞİŞİKLİK GÜNLÜĞÜ |
| v5.3 | `DEGISIKLIKLER_FINAL_v5.3.md` | 13.101 B | ACARBOT FINAL v5.3 — Değişiklik Günlüğü |

## Güncel sürüm

**v5.3** — kapı atfı: hangi kapı hangi adayı reddetti, o aday açılsaydı
ne olurdu. Üç kapının da bizi **zarardan kurtardığı** ölçüldü. İki önceki
teşhis (hacim kapısı darboğaz; ters seçilim hatası) çürütüldü. Kök neden
bulundu: **çıkış geometrisi** — ödül/risk 0,452, gereken 2,5 (5,53× açık).
Canlı/backtest maliyet eşitliği kapatıldı. Backtest dolum iyimserliği
ölçüldü (5 dk pencere vs 45 sn gerçek). **790 test.**

**Hüküm: KENAR YOK.** Gerçek paraya ölçekleme yapılmamalı.
