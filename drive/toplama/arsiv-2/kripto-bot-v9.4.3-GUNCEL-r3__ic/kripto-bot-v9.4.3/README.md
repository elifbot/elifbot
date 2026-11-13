# Kripto Bot v9.4.3 — GÜNCEL paketleme r3 / PAPER

**Gerçek para ve kârlılık onayı yok.** Eski iki ZIP arşivdir; güncel teslim
`kripto-bot-v9.4.3-GUNCEL-r3.zip` dosyasıdır. Kanonik rapor
`reports/v943_final_report.md`, güncel kaynak donması 90 dosyalık
`reports/v943_packaging_freeze_manifest.json` dosyasıdır.

## Üç farklı kanıtı ayırın

1. **Önceki 15 dakika:** 900.534s, 59/59 örnek HTTP200, bir dolmayan deneme,
   0 açık/0 kapalı, 0 gözlenen IN_FLIGHT. Host pytest 121 geçti. Bunlar canlı
   PENDING yanıtı veya uçtan uca yürütme kabulü değildir.
2. **Yeni gerçek Docker testi:** ilk pytest 4 collection hatası (eksik PyYAML);
   ham çıktı korundu. PyYAML/sabit bağımlılık paketleme düzeltmesinden sonra
   Docker içinde **121 geçti / 11.73s**; kendi HEALTHCHECK sonucu **healthy**.
   `--network=host` kullanıldı, varsayılan bridge/Compose ağı test edilmedi.
3. **Yeni 24 saat PAPER:** plan 2026-11-03 09:51:12 UTCde kaydedildi;
   konteyner 09:51:31 UTCde başladı. **Teslim anında RUNNING; tamamlanmadı.**
   86.400s aktif + en fazla 600s drenaj; gerçek emir yok. Salt-okunur DB 0,25s,
   PENDING varken /health 0,5s, yokken 5s; state 15s, Docker durumu 20s.
   Doğal dolum ve tam kapanış aranır; filtre gevşetme/zorla işlem yok.
   Olay eksikse YETERSİZ GÖZLEM, erken kesilirse KESİLDİ; süreklilik garantisi yok.

`sampled_connectivity_checks_passed=true` eski 15dk örneklemine aittir.
`pending_in_flight_observed_live=false` ve operasyonel/gerçek para onayı false
korunmuştur. Güncel plan `reports/v943_24h_frozen_plan.json`; başlangıç durumu ve
Docker kanıtları `reports/v943_packaging_r3_update.md` ve `v943_docker_24h_start/`.
ZIP bir başlangıç anı kopyasıdır; gelecek 24 saatin sonuçlarını içermez.

Önceki 87 dosya donması tarihsel olarak korunur. Paketleme için iki gereksinim
listesi ve bütünlük kontrolcüsü güncellendi; Dockerfile/Compose/.dockerignore
ile yeni 90 dosyalık kayıt kullanılır. Sağlık/strateji/risk/çıkış/muhasebe runtime
Python kaynakları bu r3 düzeltmesinde değiştirilmedi. Çalışan sabit imajın kaynak90
hashleri aynı; imajın içindeki dokümanlar başlangıç öncesi kopyadır, bu ZIPteki
başlangıç sonrası dokümanlarla aynı olduğu ileri sürülmez.

Thread-token yarış penceresi doğrulanmış değildir. İzole sentetik 0–100MiB DB
kopya ölçümü eklendi; gerçek işlem nüfusu/tam API yük testi değildir.

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

## Diff notu

`reports/v942_to_v943_runtime.patch` v9.4.2 üzerine kaynak/doküman farkının
inceleme kopyasıdır; tam dağıtım manifestini ve eski ham deney dosyalarını
taşımaz. Kurulum ve tam paket doğrulaması için bu güncel ZIPi kullanın.
