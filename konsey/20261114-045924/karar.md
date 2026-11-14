# Konsey kararı · 2026-11-14 05:59

**Görev:** bot/v9/motor.py içinde REJIM_DONUS çıkışı 44 işlemin 36'sını üretiyor (komisyon 24.66$). Çözüm: ters rejim TEYİDİ. Dosyadaki GERÇEK adlar: class Poz (satır 40), class MotorV9 (satır 71), metot _bakim (satır 121) içinde REJIM_DONUS kapatması var. İSTENEN: (1) Poz sınıfına ters_rejim_sayaci: int = 0 alanı ekle, (2) _bakim metodunu TAM olarak yeniden yaz: ters rejim görüldükçe ters_rejim_sayaci += 1, rejim düzelince 0 yap, kapatma koşulunu ters_rejim_sayaci >= 20 yapacak şekilde değiştir, diğer tüm mantığı (BE kilidi, trailing, zombi, pnl hesabı) AYNEN koru. Çıktı SADECE: [{tur: alan_ekle, sinif: Poz, dosya: bot/v9/motor.py, alan: '...'}, {tur: fonksiyon, ad: _bakim, dosya: bot/v9/motor.py, kod: '<tam metot>'}]
**Sağlayıcılar:** nvidia
**Çağrı:** 9

_Karar üretilemedi. `oturum.json` içindeki hatalara bak._

