# V10 kaynak incelemesi ve geliştirme kararları

Bu belge asistanın yaptığı mühendislik incelemesidir; başka yapay zekâlardan
gelen yanıtlar değildir. Kullanıcı başka YZ'lerin fikrini istedi; 0/20 API
anahtarı yapılandırılmış olduğundan şu anda gerçek model görüşü alınamamıştır.

## En son HTML'de öne çıkanlar
- Altı strateji: EMA trend, RSI dönüş, EMA+RSI, MACD, Bollinger kırılım/dönüş.
  EMA200+50 kapalı mum ısınması, trend için iki mum teyidi, hacim teyidi.
- ATR SL/TP, komisyon/slipaj, başabaş/takip ve sanal cüzdan.
- Önceki HTML'ye ek olarak gömülü sembol listesi, OKX kontrat çarpanları,
  bağlantı yedeği, paralel yükleme ve bağlantı durma/geri çekilme davranışı.
- Tarayıcı arayüzü, geçmiş test, optimizasyon ve risk metrikleri de var.

## V10 seçimleri ve itirazlar
1. Kapanmamış mum bazlı ileriye bakma engellendi, mumların zaman/sıra ve
   tazeliği denetlendi. Kapanış zamanında eski veriden geriye dönük giriş yok.
2. Kaynağın yaygın strateji kuralları ayrı modüle alındı; sentetik ve kaynak
   JS karşılaştırması sistematik yürütülebilir (`parite.py`). Bu örnekleme,
   tüm piyasalar veya tam ürün eşdeğerliği ispatı değildir.
3. Belirsiz/eskimiş quote, geniş makas, maliyeti aşmayan ATR hareket tahmini,
   eksik/yakın funding ve fazla pozisyon girişini önleyen kapılar eklendi.
   ATR hareketi gerçek beklenen getiri veya pozitif istatistiksel kenar değildir.
4. Gerçek veri yalnız erişilen Gate.io USDT vadeli uçlarından okunur; yalnızca
   önceden belirtilen 20 kripto sözleşmesi kullanılır. Veri kesilirse sentetik
   piyasa üretmek yerine tazelik sınırları ve hata kayıtları kullanılır.
5. 5.5 bps/taraf komisyon, 2 bps/taraf kayma varsayılmıştır; gerçek
   doldurma, kısmi dolum, marjin/likidasyon ve funding muhasebesi değildir.
6. HTML'nin arayüz/lab/backtest ve tüm borsa özellikleri aktarılmadı. Bunlar
   yapılmış veya test edilmiş sayılmamalıdır.

## Dış yapay zekâ görüşleri
Kullanıcının talep ettiği bağımsız model görüşleri: **bekliyor — sağlayıcı
anahtarları yok**. Kural tabanlı sayısal denetçinin kararları, dış bir modelin
görüşü ya da diğer modellerin bu tasarım hakkında tartışması değildir.
