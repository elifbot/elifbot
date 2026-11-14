# OmniRoute analiz görevi: ACARBOT bot ailesi

Dil: Türkçe. Çıktı: madde madde, rakamlı, kaynak gösteren bir rapor.

## Amaç
Elimizdeki tüm bot kodlarını, indikatörleri ve test sonuçlarını tek bir süzgeçten geçir:
hangi indikatör ve hangi yapı **kazandırdı**, hangisi **kaybettirdi**, hangileri **yanlış
ölçülmüş** ya da sentetik veriye bağlı olduğu için güvenilmez; sonunda bu bilgiye dayanarak
en iyi bot konfigürasyonunu öner.

## Kurallar (değiştirilemez)
- Kasa 1000 USD, teminat 50 USD, kaldıraç 10x, CROSS, net stop -10 USD. Bu kurallar kullanıcı
  kuralıdır; öneri bunları değiştiremez. Bir öneri bunlardan birini değiştiriyorsa reddet.
- Simülasyon varsayılandır. Gerçek emir gönderme önerisi yoktur. Yatırım tavsiyesi değildir.
- SENTETİK veriye dayalı sonuç kenar kanıtı değildir. Her sonucu veri kaynağına göre etiketle:
  `SENTETIK`, `CANLI_WS` (30 dk, OKX websocket), `GECMIS_KLINE` (OKX REST), `PAPER_TUR` (kısa tur).
- Örnek sayısı küçük (örn. <30 işlem) sonuçları "kanıt yok" diye işaretle.
- Her iddiaya dosya:satır veya e-posta/rapor kimliği ekle. Kaynaksız iddia yazma.

## Girdi sırası
1. `bot/` — v8 (kural kilitli motor), v9 (rejim + komite), `canli/botlar.py` (MotorV1/V2/V3),
   `acarbot_6bot/` (TURBO, OMEGA, ÜÇ-R, DÖRT, BEŞ, ALTI motorları, apex/hybrid), `konsey_bot/`.
2. `drive/` — `BOTLAR_BIRLESIK.py`, `drive/toplama/arsiv-1..4` (jurnaller, paper testler,
   raporlar), `drive/MANIFEST/`.
3. `runs/` — gerçek ve sentetik koşu çıktıları. `runs/README.md` zorunlu okunur:
   `rapor.json.besleme` alanı; `SENTETIK` sonuç kenar ölçümü değildir.
4. `docs/` — 00–11 raporları (özellikle 05 eksik; 10 canlı OKX testi, 11 canlı 30 dk akış).
5. `analiz_girdi/GMAIL_DRIVE_ENVANTER.md` — e-posta ve Drive kaynak kimlikleri (yalnızca üst veri).

## Analiz başlıkları
A. **İndikatör envanteri**: her indikatör (EMA 9/21, RSI, ADX, Bollinger, ATR, hacim, VWAP,
   CVD, funding/OI/likidasyon, rejim sınıflandırıcı, komite oylaması) için: nerede hesaplanıyor,
   parametre, hangi botta, hangi sonuçta.
B. **Kenar tablosu**: ADX/BB/RSI kovaları için ileri getiri (30 bar, %0,2 maliyet). Bilinen
   değerler: ADX<20 n=5606 ort −0,224%; ADX 35+ n=9223 ort −0,329%; BB 2+ n=2183 ort −0,849%.
   Bunları yeniden hesapla, tekrar üret, tutarsızsa bildir.
C. **Bot karşılaştırması**: aynı veri, aynı maliyet, aynı kasa kuralıyla. kbot v1/v2/v3,
   TURBO v1/v10, ULTIMATE v3/v10, BOT 4/8/9/10/11, DÖRT, BEŞ, ALTI. Net PnL, işlem sayısı,
   WR, PF, maksimum düşüş, kapanış nedenleri (stop, trailing, zorunlu kapanış).
D. **Kazandıran yapılar**: hangi giriş/çıkış kuralı, hangi rejim, hangi sembol grubu,
   hangi saat. Kanıt düzeyini belirt.
E. **Kaybettiren yapılar**: komisyon kaynaklı kayıplar (1 işlem = 0,50 USD), tek kayıp
   stop, kapı engelleyicileri (TUKENIS_SUPURME, GUNLUK_MOMENTUM, HTF_YON), bayat fiyat,
   emir kuyruğu. Her biri için ölçülmüş katkı.
F. **Yanlış ölçümler**: buy_usd=0 sıfır yerine "bilinmiyor" sorunu, ULTIMATE tape hatası,
   prefill eksikliği, 1m bar ile saniye-altı tick motorlarının uyumsuzluğu, sentetik PF 10–15
   yanılgısı, kısa turlardan kanıt çıkarma.
G. **Çelişkiler**: 30 dk canlı v3 +27,12 USD ile 14 saat/190 işlem −548,88 USD çelişiyor.
   Bunu açıkla, hangisinin daha güvenilir olduğunu gerekçelendir.
H. **En iyi konfigürasyon**: yalnızca A–G'den çıkan ve GECMIS_KLINE veya CANLI_WS ile
   desteklenen değişiklikleri öner. Her öneri için: beklenen etki, ölçüm planı, kabul/ret eşiği.
   Eşik sağlanmazsa "en iyi" yerine "henüz kanıtlanmış bir bot yok" de.

## Çıktı biçimi
1. Yönetici özeti (en fazla 10 madde)
2. Tablolar (A–C)
3. Kazandıran / kaybettiren listesi, kanıt düzeyiyle
4. Güvenilmez veya çelişkili sonuçlar
5. Önerilen konfigürasyon ve doğrulama planı
6. Eksik veriler (hangi dosya okunamadı, neden)
