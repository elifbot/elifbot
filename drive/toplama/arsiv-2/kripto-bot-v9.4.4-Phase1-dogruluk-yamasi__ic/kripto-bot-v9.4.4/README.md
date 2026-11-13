# Kripto Bot v9.4.4 — Phase 1 / PAPER doğruluk yaması

İşlem giriş/çıkış, indikatör, risk ve maker/fill kuralları değiştirilmedi.
Erken durdurma INTERRUPTED; süre protokolü tamamlanması COMPLETED; foreground
hata FAILED olarak ayrılır. Drenaj sırasında stop da INTERRUPTED olur.
Drenaj sınırında açık pozisyon kalması açıkça ayrıca belirtilir; COMPLETED tam
emir yaşam döngüsü veya kârlılık kabulü değildir. Süresiz koşu stop ile biterse
INTERRUPTED yazılır. Süre tamamlandıktan sonra panelin kapatılması sonucu bozmaz.

Toplam değerlendirme, giriş/pozisyon tekrar koruması ve tekrar dışı çağrı ayrı
metriklerdir; hiçbiri otomatik olarak benzersiz fırsat/olgun örneklem sayılmaz.
Eski v94.entry_rejections ham alanı uyumluluk için korunmuştur ve tekrar sayaçları
içerdiği işaretlenir. Yeni alan evaluation_telemetry hem API hem paneldedir.

Pozisyon olup ilk tick gelmeden panelde erişilen lazy last_venue_prices alanı
raporlama fallback'inde güvenli okunur. Executor ve finansal davranış değiştirilmedi.

Kontrollü PENDING testi gerçek HTTP handlerı fakat sentetik hesap/fiyat/token
verileri ve ayrı test defterleri kullanır. Doğal canlı PENDING/dolum kanıtı değildir.
İlk başarısız çıktılar reports/v944 altında korunur. Eski v94/v941/v943 dosyaları
tarihsel kanıttır; v9.4.4 sonucu reports/v944/FINAL_REPORT.md ve RELEASE_STATUS.json.

## Doğrulama
```bash
python -m pip install -r requirements-tested.txt
python -m pytest -q
python -m scripts.check_v944_integrity
python -m scripts.probe_v944_pending --output /tmp/v944-disposable-probe
```
Probe çıktı öneki yalnız kendi geçici test klasörünüz olmalıdır; gerçek koşu
klasörü vermeyin. Doğal PAPER veya gerçek borsa emri bu teslimde başlatılmadı.
Eski scripts.check_v943_integrity tarihsel sürüm içindir; burada kullanmayın.

Docker sonuçları nihai raporda ayrıca yer alır; imaj kurulurken sonuç belgeleri
henüz üretilmemiş olabilir. Sabit kaynak hashleri test öncesinde dondurulmuştur.
Bağımlılıklar önceki test edilmiş doğrudan sürümlerde korundu; bu tam transitive
lock veya evrensel dağıtım/uptime garantisi değildir. Docker ağ testi host modundadır.

Strateji araştırması sonraki ayrı aşamadır. 70 puan, 1.5 ATR, kademeli TP,
intra-candle tetikleme veya gate gevşetme uygulanmadı. Önceki negatif tarihsel
kârlılık sonucu ve gerçek para onayının yokluğu değişmedi.
