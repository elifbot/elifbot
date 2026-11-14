# Konsey kararı · 2026-11-14 01:11

**Görev:** bot/v9/motor.py içindeki REJIM_DONUS çıkışını teyide bağla. Mevcut kod satır 140-144: pozisyon açıldıktan 120 sn sonra rejim ters dönerse ve pnl negatifse anında kapanıyor; 44 işlemin 36'sı böyle kapanıyor, komisyon 24.66$. İSTENEN 3 PARÇALI YAMA: (1) Poz dataclass'ına ters_rejim_sayaci: int = 0 alanı ekle, (2) _izle içinde ters rejim görüldükçe sayacı artır, rejim düzelince sıfırla, (3) kapatma koşulunu 'ters_rejim_sayaci >= 20' yapacak şekilde değiştir. DEĞİŞMEZ: 1000$ kasa, 50$ x10, CROSS, sınırsız pozisyon, -10$ stop. Sadece JSON.
**Sağlayıcılar:** nvidia
**Çağrı:** 14

_Karar üretilemedi. `oturum.json` içindeki hatalara bak._

