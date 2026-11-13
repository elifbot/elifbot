# ACARBOT — DEĞİŞİKLİK GÜNLÜĞÜ DİZİNİ

Her satır tek bir sürüme aittir. Sürümsüz changelog dosyası yoktur;
dosya adı ile iç sürüm `tools/package_release.py` tarafından
`app.__version__` üzerinden tek kaynaktan türetilir ve tutarlılık
denetiminden geçmeyen paket YAZILMAZ.

| Sürüm | Dosya | Boyut | Başlık |
|---|---|---|---|
| v1.0 | `DEGISIKLIKLER_FINAL_v1.0.md` | 3.113 B | ACARBOT FINAL v1.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v1.1 | `DEGISIKLIKLER_FINAL_v1.1.md` | 4.242 B | ACARBOT FINAL v1.1 — Değişiklik Günlüğü (7 Kasım 2026) |
| v1.2 | `DEGISIKLIKLER_FINAL_v1.2.md` | 2.774 B | ACARBOT FINAL v1.2 — Değişiklik Günlüğü (7 Kasım 2026) |
| v2.0 | `DEGISIKLIKLER_FINAL_v2.0.md` | 14.403 B | ACARBOT v2.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v3.0 | `DEGISIKLIKLER_FINAL_v3.0.md` | 8.742 B | ACARBOT v3.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v3.1 | `DEGISIKLIKLER_FINAL_v3.1.md` | 10.399 B | ACARBOT v3.1 — Değişiklik Günlüğü (7 Kasım 2026) |
| v4.0 | `DEGISIKLIKLER_FINAL_v4.0.md` | 14.931 B | ACARBOT v4.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v5.0 | `DEGISIKLIKLER_FINAL_v5.0.md` | 6.204 B | ACARBOT FINAL v5.0 — Değişiklik Günlüğü (7 Kasım 2026) |
| v5.1 | `DEGISIKLIKLER_FINAL_v5.1.md` | 10.997 B | ACARBOT FINAL v5.1 — Değişiklik Günlüğü (7 Kasım 2026) |
| v5.2 | `DEGISIKLIKLER_FINAL_v5.2.md` | 12.915 B | ACARBOT FINAL v5.2 — DEĞİŞİKLİK GÜNLÜĞÜ |
| v5.3 | `DEGISIKLIKLER_FINAL_v5.3.md` | 15.024 B | ACARBOT FINAL v5.3 — Değişiklik Günlüğü |
| v5.4 | `DEGISIKLIKLER_FINAL_v5.4.md` | 10.584 B | ACARBOT FINAL v5.4 — Değişiklik Günlüğü |
| v5.5 | `DEGISIKLIKLER_FINAL_v5.5.md` | 6.898 B | ACARBOT v5.5 — Denetim düzeltmeleri: 6 kusur, bağımsız tarama, küme istatistiği (8 Kasım 2026) |

## Güncel sürüm

**v5.5** — denetim düzeltmeleri. Dış denetimin bildirdiği 6 kusurun
altısı da kodda doğrulandı ve düzeltildi: brüt/net etiketi, drawdown
kilidi (1.013 aday kilitli), "kapısız" sanılan bulaşık aday evreni,
bağımsızlık varsayımı (kümeleme %26 sanılıyordu, ölçülen %46,9),
ikili hüküm, stopsuz uzun ufuk.

Yeniden ölçüm: 5m (n=818) ve 15m (n=302) **kenar istatistiksel olarak
ELENDİ**; 1h (n=67) **YETERSİZ ÖRNEKLEM** — kenar elenmiş değil,
ölçülememiş. Stop'lu testte 15m 48 bar +0,106R → **−0,111R** (işaret
dönüyor, %75 stopa takılıyor). Bonferroni sonrası uzun ufuk
"işareti" ölüyor (p 0,028 → 0,419). **862 test.**

Önceki sürüm v5.4 — giriş kenarı testi. Önceki "kök neden çıkış geometrisi"
teşhisi **çürütüldü**: kapısız simetrik çıkışla 1.121 aday ölçüldü,
beklenti sıfırdan ayırt edilemiyor. Zarar = kenarsız girişe ödenen
maliyet (0,535 R). Önerilen çıkış geometrisi ölçüldü: iyileşmenin
%98,6'sı maliyet tasarrufu, kâr yok. İki gerçek risk hatası düzeltildi
(bağlayıcı etiketi, tabanın riski 64× yükseltmesi). TTL dürüstleştirildi.
"518 sembol elendi" iddiası çürütüldü. **819 test.**

**Hüküm: GİRİŞ KENARI YOK.** Çıkış ayarı yasak; önce örneklem büyütülüp
kenar kanıtlanmalı. Gerçek paraya ölçekleme yapılmamalı.
