# Kripto Bot v9.4.3 — Sağlık ve telemetri yaması / PAPER

**Gerçek para onayı yok. Strateji kârlılığı onaylanmış değildir.**

Bu sürüm v9.4.2 üzerine yalnız sağlık/raporlama düzeltmesidir. Önceki sürümler ve
e-postadan alınan özgün ZIP değiştirilmedi. Sabit $50 marj / 10x, strateji, risk,
çıkış ve dolum/muhasebe kuralları korunur. Ek gözlem maliyetinin canlı zamanlamayı
hiç etkilemediği iddia edilmez.

## Değişiklikler

1. Bu StateStore örneğinin başarılı prepare işleminden sonra tuttuğu süreç-içi
   sahiplik kaydıyla eşleşen PENDING, **15 saniyeden kısa** ise HTTP sağlık
   görünümünde `IN_FLIGHT` olur. `/health` 200 dönebilir, ama
   `ledger_reconciled=false` kalır; defter kesinleşmiş gibi gösterilmez.
2. **15 saniyede ve sonrasında** alarm/503. Önceki süreçten kalan, başka store veya
   PID tarafından oluşturulmuş, saati bozuk veya sahibi bilinmeyen PENDING hemen 503.
   Sağlık durumu gerçek bir nakit/ücret/funding/pozisyon hatasını tolere etmez.
3. Üretim DBsi sağlık kontrolünde değiştirilmez. Tutarlı SQLite kopyası bellekte
   doğrulanır; yalnız uygun genç niyetler geçici kopyada ayrıştırılır. Kopyadaki
   kesinleşmiş hesap aynı sıkı doğrulayıcıdan geçmek zorundadır.
4. `verify_paper_ledger_integrity()` ve recovery/yeniden başlatma yolu değiştirilmedi:
   genç dahi olsa her PENDING burada hâlâ `ok=false` verir. Alım-satım kilidi açılmaz.
5. Alarm artık `LEDGER_INTEGRITY_ERROR(reason=...)` veya gerçek pozisyon kümesi
   farkında `POSITION_SET_MISMATCH` gösterir. PENDING uyarısı ve yaşları ayrıca görünür.
6. Binance `endpoint_aggTrade` ve `endpoint_bookTicker` ayrı tutulur; genel `endpoint`
   artık tek bir kanalın adresiymiş gibi sunulmaz.

## Çalıştırma

```bash
python -m pip install -r requirements-tested.txt
python -m pytest -q
python -m scripts.check_v943_integrity
python -m src.live_runner --config configs/v9-canonical-production.json --duration-sec 900 --max-drain-sec 180 --port 8080 --report-prefix yeni_v943_paper
```

Config `genel.mod=paper` olmalıdır. Yeni önek yeni kayıt oluşturur; aynı önek eski
kaydın üstüne yazar. Piyasa verileri için internet gerekir. Panel `/`, JSON
`/api/state`, sağlık `/health`. Docker dosyaları mevcuttur, ancak bu yamanın test
raporu hangi ortamın kullanıldığını ayrıca belirtir.

## Kanıtlar ve sınırlar

- `reports/v943_pytest.txt`: tam regresyon sonucu. İlk denemede eski alarm metnine
  bağlı bir test başarısız oldu; beklenti yeni ve daha doğru POSITION_SET_MISMATCH
  sözleşmesine güncellendi. İlk çıktı da arşivlendi, hata gizlenmedi.
- `reports/v943_freeze_manifest.json`: yeni yama için test öncesi kaynak hashleri.
- `reports/v943_reference_sources/`: önceki StateStore/UnifiedTradingEngine kaynakları;
  finansal fonksiyonların AST ve sıkı doğrulayıcının değişmezlik testleri için.
- `reports/v943_final_report.md`: yeni canlı test ve HTTP hata senaryolarının sonuçları.
- `PACKAGE_MANIFEST.json`: yeni teslimin dosya hashleri.

Diğer v94/v941 raporları devralınmış tarihsel arşivlerdir, yeni v9.4.3 testi değildir.
Eski `scripts.validate_v94` bu yeni sağlık sürümünün kanonik doğrulayıcısı değildir;
önceki açılmış blokla yeni bağımsız OOS veya kârlılık iddiası üretilmez.
Önceki negatif tarihsel sonuçlar geçerliliğini korur.

v9.4.2deki tek 503 için güncel yorum: **en olası neden geçici PENDING emir niyeti;
deneyle yeniden üretildi, canlı olayda ayrıca yakalanmadı.** Eski sonuç sonradan
başarılıya çevrilmez. Her canlı koşu tek ağ/zaman örneğidir; yeniden test gerekebilir.
Az sayıda paper dolumdan güvenilir yürütme veya kârlılık sonucu çıkarılamaz.
