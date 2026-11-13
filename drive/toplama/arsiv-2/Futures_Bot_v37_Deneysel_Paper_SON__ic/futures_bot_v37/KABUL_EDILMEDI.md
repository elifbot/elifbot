# v37 — yalnız deneysel PAPER

Kullanıcı isteğiyle aktif VWAP/ATR giriş kapısı bu adayın komut satırında etkindir. 60 son TAM 1m mum quote/base VWAP; ATR Wilder(14)/fiyat ≥ %0,10. Eksik/kopuk/bayat mumda giriş kapalıdır. Son 60 TAM dakika, saniye hassasiyetinde kayan 60 dakika değildir; cari mum dışlanır.

Kullanıcı onayıyla 19 ve 71 saniyelik doğrulanmamış gap durumlarında sıkı fail-closed kabulü bu paper denemesinden muaftır. Bu, söz konusu testlerin geçtiği veya veri bütünlüğünün kanıtlandığı anlamına gelmez. H-01/P0 açık; gerçek emir veya canlı kullanıma uygunluk iddiası yoktur. 120 saniye gap/5 saniye geçmiş olay eşiği uygulanmıştır; geleceğe dönük 2 saniye ve sırasızlık koruması değişmedi. Gecikmiş işlemler RVOL'de işlenme zamanına örneklenir ve kısa pencereyi etkileyebilir.

v37 geliştirme testleri: 12 gösterge testi, 7 tolerans testi; 2 sıkı güvenlik testi bilinçli olarak seçilmedi; diğer tam testler 407 geçti. Testler gerçek zamanlı kaynak verisinin eksiksizliğini, kârlılığı, Windows uyumunu veya 300+ ileriye dönük işlem sonucunu kanıtlamaz. Kullanıcının Colab doğrulaması bağımsız olarak burada doğrulanmadı.
