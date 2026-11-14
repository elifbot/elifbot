# Konsey kararı · 2026-11-14 00:23

**Görev:** bot/v9/motor.py içindeki REJIM_DONUS çıkışını teyide bağla. Mevcut kod (satır 140-144): pozisyon rejim_karsi_cikis_sn=120 sn sonra, rejim ters dönerse ve pnl negatifse anında kapanıyor; 44 işlemin 36'sı böyle kapanıyor, komisyon 24.66$. İSTENEN: (1) Poz dataclass'ına ters rejim sayacı alanı ekle, (2) _izle metodunda ters rejim görüldükçe sayacı artır, düzelince sıfırla, (3) kapatma koşulunu 'sayaç >= 20' olacak şekilde değiştir. Değişmez kurallar: 1000$ kasa, 50$ x10, CROSS, sınırsız pozisyon, -10$ stop (bu sayılara dokunma). Renkli/uzun yazma, sadece JSON.
**Sağlayıcılar:** nvidia
**Çağrı:** 14

_Karar üretilemedi. `oturum.json` içindeki hatalara bak._

## Kural gereği düşen öneriler

- ~~?~~ — dosya/eski_kod boş
- ~~?~~ — dosya/eski_kod boş
- ~~?~~ — dosya/eski_kod boş

