# Futures Bot v4.0 — kısa paper ayar güncellemesi

Bu paket v4.0 teslimatına ait takip güncellemesidir; teknik bot sürümü **v37** olarak korunur. Önceden e-postalanan `Futures_Bot_v4.0_Release.zip` değiştirilmemiştir ve bu takip paketi ayrıca e-postalanmamıştır.

## İçerik
- `source/`: güncellenmiş tam v37 proje ağacı; tarihsel logs/run_artifacts ve testler dahil. Cache, `.pyc` ve boş süreç kilit dosyaları hariçtir.
- `paper_run/`: yeni ayarlarla başlatılan izole çalışma kopyası, parametreler ve logs. OKX kapsamı %90 hazırlık kapısına çıkmadığından 10 dakikalık ölçüm başlamadan kontrollü SIGTERM ile kapatılmıştır.
- `reports/`: bu denemenin raporu ile önceki v37/v7.8 raporları.
- `MANIFEST.sha256`: paket içindeki dosyaların SHA-256 değerleri (manifest kendisini hariç tutar).

Tam test paketi 428 test geçti. Yeni koşunun gerçek 10 dakikalık sinyal/işlem/PnL sonucu yoktur; raporda hazırlık sonucu ve sınırlar açıkça belirtilmiştir. Canlı veya testnet emri kullanılmamıştır.
