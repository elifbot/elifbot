# Yeni ılımlı PAPER denemesi
600 saniye aktif + en fazla 120 saniye girişsiz drenaj + başlangıç ısınması. Yeni prefix/boş DB; eski oturumlar devralınmaz. Log ve launch_attempt.lock exclusive.
Yalnız mild profil emir açabilir. Baseline aynı girdide sinyal karşılaştırmasıdır; shadow emir/dolum/PnL yok. profiles.jsonl ilk sembol–mum gözlemini kaydeder; bu bir çift portföy getirisi değildir.
Güvenlik, ATR risk, stop, spread/maliyet, gerçek taker ve sinyal tazeliği korunur. Hiç işlem çıkmazsa yapay işlem açılmaz. Alarm yeni girişleri kilitler. Drenaj sonunda açık kayıt kalırsa izlenmediği açıkça bildirilir.
Launcher önce doğrulanmış SENT/ek makbuzunu ve bütünlük hashlerini ister. Test sonrası salt-okunur panel: python snapshot_preview.py; botu başlatmaz. /health bu salt-okunur sunucuda yalnız önizleme hazırlığıdır.
