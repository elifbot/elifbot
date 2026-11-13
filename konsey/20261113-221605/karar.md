# Konsey kararı · 2026-11-13 22:29

**Görev:** Altı botlu Binance+OKX vadeli işlem sistemi. DEĞİŞMEZ: 1000$ kasa, 50$ x10, CROSS, sınırsız pozisyon, -10$ stop. ÖLÇÜLEN: 44 kapanan işlem, WR %15.9, PF 0.676, komisyon 24.66$, çıkış dağılımı REJIM_DONUS 36 / STOP 8. TANI: churn'ün kaynağı bot/v9/motor.py satır 142-144. Pozisyon açıldıktan rejim_karsi_cikis_sn=120 sn sonra rejim ters dönerse ve pnl negatifse pozisyon kapatılıyor; bu yüzden işlemlerin %81'i anında kesiliyor ve her biri 0.50$ komisyon ödüyor. ÖNCEKİ DENEME: sinyaller.py'ye RVOL filtresi (hacim_orani < 1.5) eklendi, A/B ölçümünde etkisi SIFIR çıktı — o yolu tekrar önerme. GÖREV: motor.py içinde REJIM_DONUS çıkışını gerçek bir TEYİDE bağlayan yama üret: örn. rejim tersliğinin N ardışık tick boyunca sürmesi veya pnl'in ek bir eşiği aşması. eski_kod'a motor.py'den birebir satırlar yaz. En fazla 3 karar.
**Sağlayıcılar:** nvidia
**Çağrı:** 15

## 1. Pozisyon Nesnesi State Genişletmesi
- **Dosya:** `bot/v9/motor.py` · **Durum:** ✅ kod doğrulandı
- **Gerekçe:** Rejim dönüşü onay mekanizmasının çalışabilmesi için 'regime_flip_count' değişkeninin Poz sınıfında tanımlı olması gerekir; aksi takdirde çalışma anında AttributeError riski oluşur.
- **Kanıt:** `—`
- **Etki / risk:** orta / düşük

## Kural gereği düşen öneriler

- ~~Rejim Dönüşü Onay Mekanizması~~ — eski_kod 0 kez geçiyor (tam 1 olmalı)

