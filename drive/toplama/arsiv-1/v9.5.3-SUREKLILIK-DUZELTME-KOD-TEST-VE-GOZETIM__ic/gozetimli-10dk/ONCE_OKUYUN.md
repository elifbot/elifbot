# Süreklilik düzeltmesi — sınırlı gözetimli PAPER
Çalıştırma: BINANCE_PUBLIC_WWW=1 python finite_supervise.py. Bu sonlu komut tamamlanana kadar bekleyin. 600 sn aktif + en çok 120 sn drenaj + ısınma. Üst gözetici en fazla 850 sn bekler; timeout gerçek sonuç yerine başarı yazmaz.
Yeni boş DB/prefix. Mail SENT/ek makbuzu olmadan child başlamaz. Önceki prefixler tekrar çalıştırılmaz; loglar exclusive.
Saat sapmasında giriş kilidi kalkmaz: aktif pencere sonlanır, sınırlı güvenlik drenajı ve DISCONTINUOUS raporu. Host saatini/VM askısını önlediğimiz iddia edilmez. Tamamlanmış test sonucu ayrı dosyada oluşur.
Mild üç sinyal eşiği v952 ile aynı. Baseline yalnız aynı girdide sinyal karşılaştırmasıdır; shadow emir/dolum/PnL yok. Gerçek para/ücretli API/dış model yok. Maker dolumu veya doğal işlem garantisi yok.
Koşu bittikten sonra yalnız son paneli göstermek için python snapshot_preview.py. Bu botu yeniden başlatmaz; /health bu modda yalnız viewer hazırlığıdır, bot sağlığı değildir.
