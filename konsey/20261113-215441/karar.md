# Konsey kararı · 2026-11-13 22:02

**Görev:** Altı botlu Binance+OKX vadeli işlem sistemini iyileştir. Değişmez kurallar: 1000$ kasa, 50$ giriş x10 kaldıraç (500$ notional), sınırsız pozisyon, CROSS teminat, pozisyon başına -10$ stop, evren tüm Binance+OKX vadeli pariteleri. Ölçülmüş gerçek veri (v9 smoke, 60 sembol): 44 kapanan işlem, WR %15.9, PF 0.676, en iyi +16.1$, en kötü -6.02$, maksDD -30.38$, çıkış dağılımı REJIM_DONUS 36 / STOP 8, komisyon 24.66$ (işlem başına gidiş-dönüş 0.50$). Kenar ölçülmedi, churn yüksek: işlemlerin %81'i REJIM_DONUS ile kapanıyor. Görevin: bot/v9/motor.py, rejim.py, sinyaller.py dosyalarındaki GERÇEK koda dokunan, en fazla 4 somut yama öner. Öncelik: (1) churn'ü azalt (giriş/çıkış sıklığı), (2) REJIM_DONUS çıkışını kanıta bağla (anlık rejim dönüşü yerine teyit), (3) stop mesafesini 0.50$ maliyetle uyumlu hale getir. eski_kod alanına dosyadan birebir kopyalanmış satırlar yaz.
**Sağlayıcılar:** nvidia
**Çağrı:** 7

_Karar üretilemedi. `oturum.json` içindeki hatalara bak._

## Kural gereği düşen öneriler

- ~~REJIM_DONUS Çıkışına Teyit Mekanizması~~ — eski_kod 0 kez geçiyor (tam 1 olmalı)
- ~~Operasyonel Durum Yönetimi Kalıcılığı~~ — eski_kod 0 kez geçiyor (tam 1 olmalı)

