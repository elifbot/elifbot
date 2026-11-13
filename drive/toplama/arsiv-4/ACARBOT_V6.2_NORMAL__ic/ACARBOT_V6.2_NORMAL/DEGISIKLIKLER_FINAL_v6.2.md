# ACARBOT v6.2 — güvenlik ve doğrulama notu

Kaynak: v6.1 normal paket; özgün Drive kaynağı ve önceki teslimler değiştirilmedi. Araştırma ve paper içindir; gerçek para veya testnet ağına bu geliştirmede emir gönderilmedi. Kârlılık ispatlanmadı.

## Yapılanlar

1. `LiveMirror` yeni girişte ve DCA'da etkin config, timeframe/kenar kapısı, başarılı ve kullanılabilir mirror yükleyici/kaydedici ister. DCA ayrıca borsadan aynı yönde pozisyon ve saklanan stop kimliği kontrolü ister. Stop ve çıkış kapıya bağlanmaz. Kayıt hatası sonraki girişleri durdurur.
2. Mirror girişinden önce seçilen borsanın gerçek public metadata yanıtında sembol, sayısal değerler, miktar/tick ve OKX kontrat adımı kontrol edilir, aykırılık reddedilir. Ardından aynı kurallar adaptör önbelleğine yazılır. Girişte otomatik yukarı yuvarlama yapılmaz.
3. Açılış veritabanı ve yeni yedek `PRAGMA quick_check` ile kontrol edilir. Mevcut yedeklerin üzerine yazılmaz; bozuk yeni yedek silinir. Mirror JSON'u bozuksa exception üretilir. Testnet açıkken yedek başarısızlığı ve yedeğin kapatılması açılışı reddeder; paper uyarı ile devam edebilir.
4. Kök uygulama log handler'larının çıktı ve exception metninde yaygın anahtar/imza/token ve bilinen secret değerleri maskelenir; `_FILE` secret'ları da kayıt edilir. Bu koruma gizli bilgilerin loglanmaması gereğini ve OS erişim izinlerini ortadan kaldırmaz.
5. Emrin açık olup olmadığı sorgulanamazsa, veya post-only iptali başarısızsa, sistem yeni girişleri kapatır ve otomatik market yedeği açmaz; borsanın manuel kontrolü gerekir.
6. Yeni ağsız, gerçekten assertion içeren fail-closed, demo/mock giriş/çıkış, filtre, bozuk state/yedek, log ve varsayılan kilit regresyonları eklendi. Eski mekanik testler yalnız testte izinli açık config, test içi bellek kaydı ve sahte enstrüman bilgileriyle çalıştırılır; bunlar varsayılan gerçek ayar değildir.

## Kapsam ve çözülmemiş riskler

- Başka kodun broker adaptörlerine doğrudan emir göndermesi `LiveMirror` korumasını atlar. Otomatik testler gerçek ağ, gerçek kimlik bilgisi ve gerçek para kullanmaz.
- Sembole ilişkin tüm borsa kurallarının tam kapsamı, özellikle piyasa emrinin gerçek fiyatına bağlı minimum notional, maksimum limitler ve işlem zamanında kural değişikliği doğrulanmadı. Kesin dolum veya doğru stop garantisi yoktur.
- Post-only emrin açık listeden kaybolmasının dolum olarak yorumlanması, iptal-dolum yarışları ve bazı gönderim hatalarının market fallback'e dönüşmesi tamamen düzeltilmedi. Kısmi dolum veya bağlantı hatası durumunda pozisyon/stop manuel kontrol gerektirir. Yeni kilitler üretime hazır olunduğu anlamına gelmez.
- SQLite quick_check eski ama geçerli yedeği, tüm mantıksal tutarsızlıkları veya emir gönderiminden kayıt öncesi çökme aralığını yakalamaz. Yeniden başlatmada borsa mutabakatı gerekir.
- Log maskelemesi en iyi çabadır, her gizli değer biçimini ve harici log handler'ını kapsamaz; gizli değerler şifrelenmez.
- 1h üretim doğrulaması, gerçek funding ve ücret/kayma ölçümü, bağımsız kör OOS, testnet operasyon testi ve kârlılık doğrulaması yapılmadı. Varsayılan canlı giriş kapalıdır.
- Eski doğrulama referansları temiz pakette bulunmadığından yayın kapısı `tools.package_release --check-only` yeşil değildir. Atlanan referans testleri başarı veya işlem performansı kanıtı değildir.
