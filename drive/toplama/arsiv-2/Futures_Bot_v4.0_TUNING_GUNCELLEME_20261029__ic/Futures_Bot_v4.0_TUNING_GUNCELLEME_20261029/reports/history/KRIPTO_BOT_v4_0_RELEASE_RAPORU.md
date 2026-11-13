# Kripto Bot v4.0 Release · v37 · v7.8 Fade / MTF / kâr koruma

**Release adı:** v4.0  
**Teknik bot sürümü:** v37 (korundu; v4.0 bu teslimat/release adıdır).  
**Tarih:** 29 Ekim 2026 · tüm koşu zamanları UTC  
**Kapsam:** yalnızca paper; live/testnet emir yolu eklenmedi.

## Değişiklikler

- `Futures_Bot_v37_Deneysel_Paper_SON/futures_bot_v37/scanner/signal_intel.py` eklendi. Kapalı 1h/4h mumlarından MTF trend skoru üretir (1h %45, 4h %55); yayın gecikmesi ve yerel/borsa saat farkına karşı son HTF mumunu 2 dakika emniyet payıyla değerlendirir. Aynı `(exchange, symbol)` için funding ve OI, ikinci örnek geldiğinde OI değişimi/fiyat matrisi, gerçek taker işlemlerinden 15s/60s CVD ve yönlü imbalance teyidi sağlar. Eksik, eski veya başarısız veri sinyali **fail-closed** engeller. Public GET adresleri merkezi allowlist üzerinden doğrulanır ve istekler borsa bazında hız sınırlıdır.
- `ws_bot.py` içinde mevcut Fade yön çevirme yolu korunup MTF/türev/order-flow teyidi paper girişinden önce bağlandı. Hazırlık kapısı geçilmeden sinyal ölçülmez; asenkron REST değerlendirmesinden sonra 10 saniyeyi aşan aday da reddedilir. CLI’de `--sinyal-zenginlestirme` ve `--kar-kilidi` varsayılan açık, açıkça kapatılabilir. Sinyal filtreleri ve engel nedenleri ayrı CSV/JSON telemetrisine yazılır.
- `portfolio/paper_futures.py` pozisyon başına favorable peak, MFE, kilit kademesi ve MFE-kalkan durumunu tutar. İki kademeli kilit (`+%0,50 → net +%0,12`, `+%0,90 → net +%0,30`) ile MFE kalkanı (`MFE ≥ $1,75`, zirve kârının `%48`’i) v37’nin gerçek giriş/çıkış ücretleri, funding’i, modellenen kayması ve stop aşımı hesaba katılarak monotonic stop fiyatına çevrilir. Yeni durum alanları state dosyasına kaydedilir; olaylar `logs/ws_kar_kilidi.csv`’ye yazılır. Stop fiyatının üzerinden boşlukla geçilmesi halinde gerçekleşen dolumun hedef net kârı koruyacağı garanti değildir; bu hâlâ paper fill varsayımıdır.
- Pozisyonlar, OI/funding geçmişi ve akış `(exchange, symbol)` anahtarıyla ayrı kalır; Binance/OKX bakiyeleri birleştirilmedi. OKX’te Binance ile çakışan base’leri çıkarıp Binance’te tutan mevcut davranış korundu.

## Doğrulama

- Değişiklik öncesi baz çizgisi: **413 test geçti**.
- Değişiklik sonrası: **428 test geçti** (**15 yeni vaka dahil**, 31,58 sn). `py_compile` ve güvenlik/allowlist testleri de geçti.
- Ayrıca paper koşusundan ayrı, gerçek public endpoint smoke testi yapıldı: Binance ve OKX için 1h/4h mum, funding ve OI uç noktalarına toplam **8 public GET**, **0 hata**. Her iki venue’de de MTF ve güncel funding/OI verisi çözümlendi. Bu test işlem/kârlılık testi değildir; OI değişimi ilk snapshot’ta doğal olarak boştu.

## İzole 10 dakikalık paper koşusu

- Dizin: `/home/user/v37_paper_v7_8_run_20261029_02/`
- Komut: `python -u ws_bot.py --sure-dk 10 --sembol-limit 0 --binance-hacim-kaynagi aggtrade --indikator-hazirlik-oran 90 --indikator-hazirlik-zamanasimi-dk 75 --sinyal-zenginlestirme --kar-kilidi --no-defter-golge`
- Hazırlık kapısı **19:46:35.788 UTC**’de geçti; ölçüm sayacı **19:46:35.813–19:56:35.886 UTC** arasında yaklaşık 600 sn çalıştı. Sayacın başlamasından önce her borsa ayrı ayrı eşiği geçti: **Binance 522/522 (%100), OKX 22/22 (%100)**. Son kapanış kapsamı Binance **490/522 (%93,87)**, OKX **22/22 (%100)** idi; son snapshot’ta da her iki borsa `%90` üzerindeydi.
- Sonuç: **0 sinyal, 0 açılış, 0 kapanış, 0 açık pozisyon**. Bakiye **1.000,00 USDT**, net PnL **0,0000 USDT**. İşlem olmadığı için komisyon **0**, pozisyona uygulanmış funding **0**. Kâr kilidi kademe-1/kademe-2/MFE aktivasyonları **0/0/0**.
- Flow feed’i çalıştı: AkışDefteri toplam **331.733** trade aldı; Binance aggTrade **327.297**, akış veri hatası **0**, şüpheli ID boşluğu **0**. Ancak sinyal adayı oluşmadığından order-flow teyidi çağrılmadı. `SignalEnricher` fetch çağrısı **0**; Fade/MTF/funding/OI/order-flow filtre sayaçlarının tamamı **0**. Dolayısıyla bu paper koşusu filtrelerin işlem üzerinde gerçek zamanda tetiklendiğini veya performansı doğrulamıyor; kod yolu birim testleriyle, public veri uçları da ayrı smoke testiyle kontrol edildi.
- Sinyal çıkmamasında tarayıcı kapılarında görülen sayaçlar (benzersiz sembol/sinyal sayısı değildir): `ret_esik=438.335`, `hacim_orani_hazir_degil=241.380`, `bayat_hacim=117.047`, `rvol_esik=7.343`. Bu sayılar tarama tiklerindeki eleme sayımlarıdır.
- Öncesindeki proxy-hacim ön denemesi Binance kapsamı `0/522` kaldığı için test sayacı başlamadan kontrollü SIGTERM ile durduruldu; raporlanan 10 dakikaya dahil değildir. Başarılı koşu aggTrade modunda ve ayrı izole dizinde yapıldı.

## Sınırlar

10 dakikalık sıfır işlem sonucu ne kârlılık kanıtı ne de strateji başarısızlığıdır; performans çıkarımı yapmak için yeterli örneklem oluşmadı. Funding muhasebesi yalnız gözlenen olayları kapsar; eksiksiz funding garantisi değildir. Mevcut evren filtresi için yetkili bir ABD-kökenli varlık listesi bulunmuyor; mevcut filtrelerin ABD-kökenli varlıkları kesin biçimde dışladığı garanti edilemez.

## Kayıtlar

- Son durum ve per-borsa kapsam: `v37_paper_v7_8_run_20261029_02/logs/ws_durum.json`
- Paper portföy/state: `v37_paper_v7_8_run_20261029_02/logs/ws_state.json`
- Sinyal olay CSV’si (yalnız başlık; sinyal yok): `v37_paper_v7_8_run_20261029_02/logs/ws_olay.csv`
- Yeni testler: `Futures_Bot_v37_Deneysel_Paper_SON/futures_bot_v37/tests/test_v37_signal_intel_and_profit_lock.py` ve `tests/test_v37_signal_enrichment_bot_wiring.py`
