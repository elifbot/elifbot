# 100.000 USDT Paper Oturumu — Sonuç ve Bileşen İncelemesi

**GitHub Actions run:** [40077757773](https://github.com/omeracar56/kripto-bot/actions/runs/40077757773)  
**Tarih:** 24 Ekim 2026  
**Mod:** PAPER — canlı Binance/OKX Futures verisi, hayali kasa; gerçek emir yok  
**Sabit işlem boyutu:** 50 USDT marj, 10x kaldıraç

## 1. Kontrollü kapanış ve genel mutabakat

- Süre sonunda **55 açık pozisyon kontrollü olarak kapatıldı**.
- Oturum sonunda **açık pozisyon: 0**; kontrollü kapanış tamamlandı.
- Toplam **85 giriş ve 85 kapanış** kaydı var; pozisyon UUID'leri tekil.
- Nihai Telegram raporunun gönderildiği oturum logunda doğrulandı.

| Genel oturum — tüm paper kapanışları | Sonuç |
|---|---:|
| Başlangıç kasası | 100.000,00 USDT |
| Brüt fiyat K/Z | +72,92 USDT |
| Giriş + çıkış ücretleri | 29,77 USDT |
| Funding | +0,16 USDT |
| **Net oturum K/Z** | **+43,31 USDT** |
| **Bitiş kasası / özsermaye** | **100.043,31 USDT** |
| Net kazanan / kaybeden | 39 / 46 |
| Net kazanma oranı | %45,9 |
| Profit factor | 1,62 |

Kesin mutabakat:

`72,924932 - 8,498666 - 21,274853 + 0,158205 = 43,309619 USDT`

Bu genel sonuç bütün gerçekleşen paper maliyetlerini içerir. Aşağıdaki bot kohortu ise genel oturum sonucunun yerine geçmez.

## 2. Botun kendi kapattığı pozisyonlar

Oturum-sonu/manuel kapanışlar çıkarıldığında **30 bot kapanışı** vardır:

| Bot kapanış kohortu | Sonuç |
|---|---:|
| İşlem | 30 |
| Net kazanan / kaybeden | 22 / 8 |
| Net kazanma oranı | %73,3 |
| Brüt fiyat K/Z | +106,00 USDT |
| Ücretler | 10,50 USDT |
| Funding | +0,11 USDT |
| **Net K/Z** | **+95,60 USDT** |
| Profit factor | 36,07 |
| Leave-one-out kapsaması | 30/30 |

Borsa dağılımı:

- **Binance:** 16 işlem, net **+54,97 USDT**.
- **OKX:** 14 işlem, net **+40,63 USDT**.

Her bot kapanışının pozisyon UUID'si, sembolü, yönü, borsası, giriş/çıkış fiyatı, 50 USDT marj/10x bilgisi, brüt ve net K/Z'si, gerçekleşen giriş/çıkış ücreti, funding'i, kapanış nedeni, aktif teknik/order-flow/MTF/ML destekleri ve leave-one-out belirleyicileri `cohort-report.md` içinde tek tek listelenmiştir.

## 3. Çıkış modülleri — giriş bileşenlerinden ayrı

| Çıkış modülü | n | Net kazanma | Brüt | Ücret | Funding | Net | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| Kâr koşusu — order-flow dönüşü | 20 | %100,0 | +104,90 | 7,00 | +0,11 | **+98,01** | — |
| Trailing stop | 10 | %20,0 | +1,10 | 3,50 | -0,00 | **-2,41** | 0,12 |

**Okuma:** Bu oturumda order-flow dönüşüyle kâr koşusu kapanışları çok güçlü görünmektedir. Trailing-stop kohortunda brüt sonuç yaklaşık başa başken ücretler net sonucu negatif yapmıştır. Bu, tek oturumluk gözlemsel bir ilişkidir; tek başına trailing veya eşik parametresi değiştirme gerekçesi değildir.

## 4. Giriş bileşenleri ve leave-one-out

Aktif katkı kohortları örtüşür; satırlar toplanmaz. Leave-one-out, bileşen çıkarıldığında aynı yönde giriş kararının oluşmamasını ayrı ölçer.

| Bileşen / kohort | n | Net K/Z | Yorum |
|---|---:|---:|---|
| CVD yönü — leave-one-out belirleyici | 26 | +94,53 USDT | Bu kohortta güçlü ilişki |
| Taker delta — leave-one-out belirleyici | 27 | +62,49 USDT | Bu kohortta olumlu ilişki |
| Order-book depth — leave-one-out belirleyici | 10 | +48,56 USDT | Olumlu; diğer bileşenlerle örtüşür |
| OI/liquidation — leave-one-out belirleyici | 4 | +51,95 USDT | Yetersiz örnek; sonuç yoğunlaşması yüksek |
| ML skoru — yönle uyumlu aktif | 13 | +34,03 USDT | Tek başına leave-one-out belirleyicisi kaydı yok |
| MTF uyumu — yönle uyumlu aktif | 30 | +95,60 USDT | Bot kohortunun tamamında mevcut; bağımsız etki kanıtı değil |

**Yoğunlaşma uyarısı:** En yüksek net sonuçlu iki ORDER/USDT işlemi toplam yaklaşık **+48,10 USDT** üretti; bu, bot kohortu net sonucunun yaklaşık **%50,3**'üdür. Bu nedenle 36,07 PF ve bileşen sonuçları birkaç büyük kazançtan belirgin biçimde etkilenmektedir.

## 5. Manuel/erken kapanış kohortu

- **55 pozisyon** `SÜRELİ PAPER ÖLÇÜMÜ SONU` ile kapandı.
- Bunlar bot performans kohortuna ve yukarıdaki 30 işlemlik PF/kazanma oranına dahil edilmedi.
- `cohort-report.md` içinde her biri için yalnız pozisyon UUID'si, sembol/yön/borsa, giriş fiyatı ve girişi destekleyen gerçek teknik, order-flow, MTF/ML ve leave-one-out kanıtları raporlandı.
- Bu kohortun gerçekleşen nakit etkisi yalnız genel paper kasa mutabakatında korunur; manuel kohortta çıkış performansı değerlendirilmez.

## 6. Veri ve işlem kanıtı

| Kanıt | Binance | OKX |
|---|---:|---:|
| USDT perpetual katalog | 741 | 507 |
| OHLCV başarı / hata | 26.157 / 0 | 2.931 / 0 |
| WS trade mesajı | 5.806.619 | 2.052.146 |
| WS book mesajı | 5.597.185 | 9.982.472 |
| Paper fill | 94 | 76 |
| Kapanan işlem | 47 | 38 |

- Fill sayıları iki borsada da işlem başına giriş + çıkış ile uyumludur: **94 = 47×2**, **76 = 38×2**.
- Oturum evreni iki borsa sembollerinin birleşimi olarak **808 tekil parite** içerir.
- 85/85 işlemde borsa alanı, pozisyon UUID'si ve giriş attribüsyonu mevcuttur.
- 85/85 işlemde 50 USDT marj ve 10x kaldıraç doğrulandı.
- İşlem bazında `net = brüt - giriş ücreti - çıkış ücreti + funding` özdeşliğinde sapma yoktur.

## 7. Sonuç ve sınır

Bu iki saatlik paper oturumu kontrollü kapandı, açık pozisyon bırakmadı ve genel kasa **+43,31 USDT net** ile mutabık kaldı. Botun kapattığı ayrı kohortta order-flow kâr koşusu öne çıkarken trailing-stop sonuçları ücretler sonrası zayıf kaldı. Bunlar tek run'a ait, örtüşen ve sonuç yoğunlaşması taşıyan gözlemlerdir; **nedensellik/ablation kanıtı değildir ve otomatik parametre değişikliği yapılmamıştır.**

## Dosyalar

- `sonuc-ozeti.md`: bu yönetici özeti
- `cohort-report.md`: genel mutabakat, bot kohortu, 30 ayrıntılı bot işlemi ve 55 manuel/erken kapanışın giriş kanıtı
- `cohort-report.json`: aynı raporun makine okunabilir biçimi
- `gunluk.txt`: ham genel oturum raporu ve tüm bileşen tabloları
- `islem_gecmisi.json`: 85 işlemin ham kayıtları ve giriş bağlamları
- `oturum_analizi.json`: ham oturum analizi ve borsa veri kanıtı
- `paper-session.txt`: maskelenmiş oturum logu; kontrollü kapanış ve Telegram teslim kanıtı
- `preflight.json`: iki borsa Futures katalog/veri ön-kontrolü
