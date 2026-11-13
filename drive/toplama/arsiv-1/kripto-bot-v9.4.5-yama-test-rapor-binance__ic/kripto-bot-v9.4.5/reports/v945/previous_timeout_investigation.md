# Önceki v9.4.4 zaman aşımı incelemesi

Timeout kaydı UTC 11:07:33.586762. İstek 2s sınırında kaldığından yaklaşık
11:07:31.58 civarında başlatılmıştır. Çevresindeki başarılı sağlık cevapları
11:07:30.576 ve 11:07:35.306; kayıtlar arasında 4.730s boşluk var.
Çevredeki yanıtların defteri RECONCILED; ±10s içinde gözlenen PENDING olayı yok.
Beş dakikalık mum kapanışı 11:05/11:10 olduğundan tam kapanış anına denk gelmiyor;
bu durum sonraki değerlendirme/ısınma işini dışlamaz. 11:07:35.529da HOT paritesinin
terfi kaydı var. Yakınlık CPU blokajının sebebini kanıtlamaz.
Sunucu 11:07:34.193te gecikmiş /health 200 loglamış olabilir; request-id ile
istemci korelasyonu olmadığından bunun zaman aşımına uğrayan istek olduğu kesin değil.
Önceki sürümde health-render/analytics ve döngü gecikme profili olmadığından DB
kopyası, başka senkron hesap, VM scheduling ve istemci gecikmesi ayrıştırılamadı.
Kesin kök neden BELİRLENEMEDİ; PENDING kaynaklı dendiği de YOK. Yeni yamada
poll/duvar-saat sapması, değerlendirme hazırlık süresi ve health-render/analytics
süreleri kaydedilerek sonraki olayın ayrıştırılması kolaylaştırılır.
