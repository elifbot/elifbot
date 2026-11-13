# v9.4 — On uzmanlık açısından karşı görüşlü tasarım incelemesi

Bu belge on bağımsız yapay zekânın gerçek diyaloğu değildir. Tek asistanın, kaynak kod ve kayıtlı sonuçlar üzerinden on farklı denetim perspektifiyle oluşturduğu değerlendirmedir. On deterministik kuralın oyu bağımsız istatistiksel kanıt sayılmaz.

## 1. Ölçülen problem

v9.3: 116 işlem, brüt -48.25, ücret 40.57, net -88.82 USDT. Kazanan oranı %56.90. Ortalama kazanan +1.12, kaybeden -3.26 USDT. Bu oranlarla yaklaşık %74.4 başabaş isabet gerekir; daha çok sinyal üretmek problemi büyütebilir.

Çıkış bazında: ACTIVE_SIGNAL_REVERSAL 39 işlem -151.81 net; PROFIT_LOCK_STOP 66 işlem +64.78 net (6 tanesi net negatif); kalanlar toplam net sonucu oluşturuyor. LONG 32 işlem -51.95, SHORT 84 işlem -36.87. Bu tek örnekten LONG'u kapatmak yasaklanan sonradan sembol/yön seçimine girer.

Canlı test sonu APR short -14.40 ve RUNE long -7.72 gerçekleşmemiş kayıpta; iki pozisyon dört kazanan işlemin +5.75 netini aşmış. Kâr kilidi hiç etkinleşmemiş kayıpların yalnız %8 fiyat / -$40 acil stopa dayanması asimetrinin merkezinde.

## 2. On perspektif, itiraz ve karar

| Perspektif | Somut bulgu / öneri | Karşı görüş | Karar |
|---|---|---|---|
| Veri mühendisi | Canlı ticker geçmiş kapanmış mumun close/high/low alanına yazılıyor. OKX nötr taker vekili gerçekmiş gibi işaretlenebiliyor. | Ticker'a duyarlı sinyal daha erken olabilir. | Kapanmış mum değiştirilemez; mark ayrı taşınır. Gerçek taker yoksa açık ret nedeni; vekil gerçek sayılmaz. |
| İstatistikçi | Eski holdout artık geliştirme verisi; yeniden OOS diye kullanılamaz. | Aynı sette düzeltmeyi kıyaslamak hızlıdır. | Eski görüntü yalnız geliştirme. Ayrık, erişilmemiş tarihsel blok mühürlenir; parametre dondurmadan açılmaz. Bunun prospektif OOS olmadığı belirtilir. |
| Sinyal araştırmacısı | Çok sayıda çakışan skor ve varsayılan ADX değerleri gerçek sinyali örter. | Çoklu gösterge gürültüyü azaltabilir. | EMA trendi, tamamlanmış HTF, hacim teyitli geri-alım/kırılım: daha küçük ve açıklanabilir çekirdek. Sürekli oy çoğunluğu eklenmez. |
| Emir-akışı uzmanı | 5m CVD '60s' etiketiyle yorumlanıyor; proxy ile gerçek ayrımı eksik. | Tam tick geçmişi yok. | Yeni çekirdek 2 kapalı bar taker dengesi adını kullanır. Tick iddiası yok; bağımsız güncel mikro-yapı metrikleri sadece yürütmede. |
| Piyasa rejimi uzmanı | Lider/genişlik ablasyonu eski sette net zararı 25.71 azaltmış. | BTC/ETH tamamen kaldırılırsa sistemik riske açık kalınır. | Otomatik kaldırma değil: yalnız lider ve genişlik birlikte belirgin tersken kapı. Eksik/bayat lider verisinde giriş yok. |
| Çıkış uzmanı | Erken sabit dolar kilidi küçük kazanan; geciken tez iptali büyük kaybeden üretiyor. | Daha geniş takip kazançları geri verebilir. | Başlangıç ATR taktik stop, 1.5R sonrası 2 ATR takip; yalnız iki önceden tanımlanmış geliştirme adayı. Sonra kör blokta değişiklik yok. |
| Risk yöneticisi | Çok sayıda eş-yönlü altcoin, tek BTC faktörünü kaldıraçla tekrarlıyor. | Pozisyon sayısını keyfi 3'e indirmek kapsamı değiştirir. | Sayı tavanı ve $50/10x korunur. Açık taktik risk toplamı özsermayenin %2'si, tek yönde %1.5'i ile ayrıca sınırlandırılır. |
| Yürütme mühendisi | Sinyal kapanışında aynı kapanıştan dolum ve giriş barındaki stop kontrolünün atlanması iyimser. | Sonraki açılışta fırsat kaçabilir. | Sinyal t kapanışı, dolum t+1 açılışı; açılış sıçraması ret; giriş barında stop; boşlukta olumsuz açılış; intrabar çıkış geliri aynı barın önceki açılışında kullanılamaz. |
| Muhasebe denetçisi | Sekiz bağımsız $1000 hesap toplamı tek $1000 portföy gibi okunabilir; kapanmış kâr açık zararı saklayabilir. | Sembol bazlı analiz yararlıdır. | Tek $1000 cüzdan, kronolojik olay sırası, açık dahil özsermaye eğrisi; net toplam ve işlem neti uzlaştırması. Sembol dökümü ikincil. |
| Operasyon/SRE | 15 dk smoke test kârlılık kanıtı değil; durdurma sonunda açık pozisyon kalabilir. | Hepsini test sonunda kapatmak da stratejiyi bozar. | Sabit süre paper test, gerçekleşmiş/açık KZ ayrı, son defter mutabakatı; gerçek para yasak. Yeni çekirdek canlı/backtest özellik eşitliği testleri. |

## 3. Geliştirme deney sınırı (testten önce)

Sıfırdan geniş parametre taraması yok. İki aday:

- A: 1.8 ATR taktik stop (min %0.35, max %1.20); 1.5R etkinleşme, 2.0 ATR takip.
- B: aynı stop; 2.0R etkinleşme, 2.5 ATR takip (kazananı daha uzun taşıma hipotezi).

Geliştirme kümesi önceki v9.3 kaydedilmiş 1500 barın [600:1500] aralığıdır. Bu aralık artık OOS değildir. Her iki adayın sonucu ve seçimi raporlanır. Seçim sadece geliştirme net KZ; eşitlikte düşük özsermaye düşüşü, sonra A. Çok az/hiç işlemli sonuç başarılı ilan edilmez.

Yeni doğrulama bloğu: eski görüntünün başlangıcından önce, en az 1 günlük boşlukla ayrılmış 4800 kapalı 5m bar/sembol; [600:4800] test. Veri dosyası mühürlenir, SHA-256 ve kaynak/konfigürasyon kaydı testten önce dondurulur. Tarihsel ve geriye dönük bloktur: geliştirmeden önceki tarihlerde bulunduğu için ileriye dönük kronolojik OOS diye adlandırılmaz. Ayrıca dondurma sonrasında 15 dakika prospektif canlı veri/PAPER smoke testi yapılır; üç 5m bar istatistiksel edge kanıtı değildir.

Dört operasyonel ablasyon (trend teyidi, gerçek akış teyidi, ortak piyasa kapısı, adaptif kâr takibi) ve 8/15bps sürtünme ile bir ek-bar gecikme stresi aynı mühürlü blokta bir kez raporlanır. Kör test sonuçlarıyla yeni aday üretilmez.

## 4. Kabul ölçütleri

1. Eski artefakt değişmeyecek; v9.4 ayrı klasör.
2. Tek karar çekirdeği, kapalı-mum değişmezliği, gerçek taker provenance.
3. Sonraki açılış ve giriş-bar stop, fon yeniden kullanım zamanlaması, bütün çıkışlarda cooldown testleri.
4. Aynı kasa için net muhasebe eşitliği; özsermaye düşüşü; ücret/kayma ve funding durumu görünür.
5. Yeni tarihsel doğrulamada ve maliyet stresinde negatif beklenti varsa gerçek paraya terfi yok. Pozitif tek blok dahi garanti/onay yerine daha uzun prospektif test gerektirir.
