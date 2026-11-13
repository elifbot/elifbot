# Konsey kararı · 2026-11-13 22:10

**Görev:** Altı botlu Binance+OKX vadeli işlem sistemini iyileştir. Değişmez kurallar: 1000$ kasa, 50$ giriş x10 kaldıraç (500$ notional), sınırsız pozisyon, CROSS teminat, pozisyon başına -10$ stop, evren tüm Binance+OKX vadeli pariteleri. Ölçülmüş gerçek veri (v9 smoke, 60 sembol, 20 dk): 44 kapanan işlem, WR %15.9, PF 0.676, en iyi +16.1$, en kötü -6.02$, maksDD -30.38$, çıkış dağılımı REJIM_DONUS 36 / STOP 8, komisyon 24.66$ (işlem başına gidiş-dönüş 0.50$). Kenar ölçülmedi, churn yüksek: işlemlerin %81'i REJIM_DONUS ile kapanıyor. Görevin: bot/v9/motor.py, rejim.py, sinyaller.py dosyalarındaki GERÇEK koda dokunan en fazla 4 somut yama öner. Öncelik: (1) churn'ü azalt, (2) REJIM_DONUS çıkışını teyide bağla, (3) stop mesafesini 0.50$ maliyetle uyumlu hale getir. Kararlar uygulanabilir kod değişikliği olmalı.
**Sağlayıcılar:** nvidia
**Çağrı:** 14

## 1. Giriş Sinyali RVOL Filtresi
- **Dosya:** `bot/v9/sinyaller.py` · **Durum:** ✅ kod doğrulandı
- **Gerekçe:** Düşük WR (%15.9) ve gürültülü girişleri engellemek için hacim teyidi şarttır. Mimar ve Test tarafından onaylanan RVOL filtresi, düşük hacimli sahte kırılımları eler.
- **Kanıt:** `—`
- **Etki / risk:** yüksek / düşük

