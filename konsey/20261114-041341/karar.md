# Konsey kararı · 2026-11-14 04:37

**Görev:** bot/v9/motor.py içindeki REJIM_DONUS çıkışını teyide bağla. Mevcut kod satır 140-144: pozisyon açıldıktan rejim_karsi_cikis_sn=120 sn sonra, rejim ters dönerse ve pnl negatifse anında kapanıyor; 44 işlemin 36'sı böyle kapanıyor, komisyon 24.66$. İSTENEN: Poz dataclass'ına ters_rejim_sayaci: int = 0 alanı ekle; _izle içinde ters rejim görüldükçe sayacı artır, rejim düzelince sıfırla; kapatma koşulunu ters_rejim_sayaci >= 20 yapacak şekilde değiştir. DEĞİŞMEZ: 1000$ kasa, 50$ x10, CROSS, sınırsız pozisyon, -10$ stop. Sadece JSON.
**Sağlayıcılar:** nvidia
**Çağrı:** 15

_Karar üretilemedi. `oturum.json` içindeki hatalara bak._

