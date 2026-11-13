# Konsey kararı · 2026-11-13 23:28

**Görev:** Altı botlu Binance+OKX vadeli işlem sistemi. DEĞİŞMEZ: 1000$ kasa, 50$ x10, CROSS, sınırsız pozisyon, -10$ stop. ÖLÇÜLEN: 44 kapanan işlem, WR %15.9, PF 0.676, komisyon 24.66$, çıkış dağılımı REJIM_DONUS 36 / STOP 8. TANI: churn kaynağı bot/v9/motor.py satır 140-144. Pozisyon açıldıktan rejim_karsi_cikis_sn=120 sn sonra rejim ters dönerse ve pnl negatifse hemen kapatılıyor. ÖNCEKİ İKİ DENEME ETKİSİZ ÇIKTI: (a) sinyaller.py RVOL filtresi — A/B'de fark sıfır; (b) Poz dataclass'ına regime_flip_count alanı eklemek — alanı kullanan mantık yazılmadı. GÖREV: motor.py'de REJIM_DONUS çıkışını teyide bağlayan, 2-3 parçalı TUTARLI bir yama üret: (1) Poz'a sayaç alanı ekle, (2) _izle içinde ters rejim sayacını güncelle, (3) kapatma koşulunu sayaca bağla. Parçalar sırayla uygulanacak; her eski_kod dosyada birebir geçmeli. En fazla 2 karar.
**Sağlayıcılar:** nvidia
**Çağrı:** 8

_Karar üretilemedi. `oturum.json` içindeki hatalara bak._

