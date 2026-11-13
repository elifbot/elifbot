# v5.6.2 — hijyen paketi (sürüm damgası 5.6-final kalır)

Sürüm damgası bilerek DEĞİŞTİRİLMEDİ (regresyon kapısı sürüm değişince
backtest kanıtının yeniden üretilmesini ister). Strateji davranışı ve
backtest sonuçları DEĞİŞMEDİ. v5.6.1 notları (kasa1000_cross profili,
requirements-lock, OKU_BENI_ONCE) bu pakete dâhildir.

Kaynak: `ACARBOT_v5_6_Eksik_Analiz_Raporu.docx` bölüm 5-7.

## Düzeltilenler
1. **`--help` çökmesi** — `app/main.py` `--dca` yardım metnindeki `%1`
   `%%1` yapıldı. Tüm `tools/*.py --help` ayrıca denendi.
2. **Kararsız test** — `TickVerifier(auto_fetch=False)` eklendi (varsayılan
   `True`: üretim davranışı aynı). `test_unverified_warn_keeps_strict_excludes`
   artık ağa çıkmaz; tick testleri ağdan bağımsız.
3. **Örnek veri vaadi** — README'deki "paket gerçek veriyle gelir" iddiası
   kaldırıldı; hızlı başlangıç önce indiriciyi çalıştırır. (Gerçek piyasa
   verisi uydurulmadı; paket `data/` boş gelir.)
4. **Windows başlatıcıları** — `run_paper_windows.bat` v5.6'ya taşındı
   (`kasa1000`, `py -3` öncelikli Python arama, hata çıkışları);
   `run_test_15min.bat` ve `run_testnet_session.bat` eklendi. `.sh` dosyaları
   `apex` yerine `kasa1000` kullanır.
5. **README tutarsızlıkları** — 4 farklı test sayısı kaldırıldı (tek kaynak:
   `pytest` çıktısı); eski sürüm blokları kaldırıldı (geçmiş
   `DEGISIKLIKLER_FINAL_v*.md` dosyalarında). V6 planında 1.5 tamamlandı olarak işaretlendi.
6. **Bağımlılıklar** — kullanılmayan `aiohttp` kaldırıldı; `pytest`/`ruff`
   `requirements-dev.txt`'e taşındı; CI test işi dev dosyasını kurar;
   `requirements-lock.txt` buna göre daraltıldı; `.dockerignore` eklendi.

## Eklenenler
- `safety/news_guard.py`: `health()` + `status()["degraded"/"degraded_reason"]`
  — takvim hiç yüklenemediyse (fail-open) veya 3 yenileme aralığından
  bayatsa görünür.
- `tools/data_budget.py`: Faz 1 indirme/disk bütçesi (çevrimdışı tahmin;
  50 sembol × 12 ay × 5m = 5.256.000 mum).
- `tests/test_v562_hygiene.py` (18 test).
- `monitor/dashboard.py` docstring'i "profesyonel panel" beklentisi yaratmayacak şekilde düzeltildi.

## Silinen fazlalıklar
`V55_CHANGELOG.md` (v5.6 günlüğünün kopyası), eski oturum kanıtları
(`canli_kanit_*`, `session_report_15min_v5*`, `TEST_RAPORU_15dk_*`),
`docs/arsiv/`, eski giriş-kenarı ham çıktıları (`docs/giris_kenari_v5.4.json`,
`_15m`, `_1h`; v55 sürümleri kalır), `docs/test_ciktisi_v5.5.txt`,
`DEGISIKLIKLER_v5.6.1.md` (bu belgeye katıldı). Testlerin ve araçların
okuduğu hiçbir dosya silinmedi. Eski analiz belgelerindeki silinen
dosyalara giden bağlantılar tarihsel kayıttır.

## YAPILMAYANLAR (bu pakette çözülemez)
- Faz 1: 12 ay × 30-50 sembol veri indirme (ağ + saatler gerekir).
- Testnet 24-48 saat oturumu ve 300 dolum markout (API anahtarı gerekir).
- Binance komisyon ölçümü (`tools/measure_costs.py`, ağ gerekir).
- Giriş kenarı: kod ile düzelmez; hüküm `NO_EDGE` aynen duruyor.
- Tam `pytest` koşumu bu ortamda yapılamadı (pytest kurulamadı); doğrulama
  notları teslim mesajında. İlk iş: `python -m pytest tests/ -q`.
