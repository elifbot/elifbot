# Konsey kararı · 2026-11-13 21:51

**Görev:** Altı botlu Binance+OKX vadeli işlem sistemini iyileştir. Değişmez kurallar: 1000$ kasa, 50$ giriş x10 kaldıraç (500$ notional), sınırsız pozisyon, CROSS teminat, pozisyon başına -10$ stop, evren tüm Binance+OKX vadeli pariteleri. Ölçülmüş gerçek veri (v9 smoke, 60 sembol): 44 kapanan işlem, WR %15.9, PF 0.676, en iyi +16.1$, en kötü -6.02$, maksDD -30.38$, çıkış dağılımı REJIM_DONUS 36 / STOP 8, komisyon 24.66$. Kenar ölçülmedi, churn yüksek. Görevin: havuzdaki tüm bilgileri tarayıp (1) churn'ü azaltan, (2) REJIM_DONUS çıkışını kanıta bağlayan, (3) stop mesafesini 0.50$ maliyetle uyumlu hale getiren somut, uygulanabilir yama önerisi üret. Dosya+fonksiyon düzeyinde diff öner. Kısa ve madde madde yaz.
**Sağlayıcılar:** nvidia
**Çağrı:** 13

## 1. REJIM_DONUS Çıkış Analizi ve Loglama
- **Gerekçe:** İşlemlerin %81'inin REJIM_DONUS ile kapanması ve PF'nin 0.676 olması, bu çıkışların kârlı olmadığını ve churn yarattığını kanıtlıyor. Gerçek kaymayı ölçmek için loglama zorunludur.
- **Kanıt:** `test_trading_system.py:1290-1296`
- **Etki / risk:** orta / düşük

## 2. Sinyal Katmanı Likidite Filtresi Entegrasyonu
- **Gerekçe:** Düşük WR (%15.9) ve yüksek komisyon maliyetleri, botun düşük likiditeli sembollerde gürültüye tepki verdiğini göstermektedir. Giriş öncesi hacim kontrolü churn'ü azaltacaktır.
- **Kanıt:** `app/executor.py`
- **Etki / risk:** yüksek / düşük

## 3. Risk-Free Pozisyon Koruma Mekanizması
- **Gerekçe:** REJIM_DONUS sinyali geldiğinde, eğer pozisyon risk-free durumuna geçmişse, kârı korumak adına çıkışın optimize edilmesi gerekmektedir.
- **Kanıt:** `executor.py:719-725`
- **Etki / risk:** orta / orta

