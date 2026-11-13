# v37 tabanlı %0,2 VWAP paper deney paketi — 30 Ekim 2026

**ws_bot.py sürüm kimliği:** v37 tabanlı, v7-benzeri aday yolu ve %0,2 VWAP toleransı eklenmiş izole deneysel paper kopyasıdır. Resmî yeni sürüm değildir. `logs/ws_durum.json` sürüm alanı 37'dir; dosyalar çalışan koşudan aynen alınmıştır. v7.8 akış tetikleyicisi bu koşuda kapalıydı. Gerçek borsa veya testnet emri yoktur.

`config.py`, `scanner/` ve `portfolio/` tamdır. Diğer Python modülleri, bağımlılık dosyaları, testler, `live_trades.csv`, son koşunun kilit dışındaki `logs/` içeriği ve rapor dahildir. Daha önceki koşuların raporları son koşu zannedilmemesi için pakete alınmamıştır. Bir sonraki çalıştırma aynı klasördeki logları değiştirebilir; önce bu arşivin bir kopyasını koruyun.

## Kurulum / aynı ayarlarla çalıştırma
Python 3.10+ ortamında `python -m pip install -r requirements.txt`; testler için ayrıca `python -m pip install -r requirements-dev.txt`. Borsa verisi için internet gereklidir. Son test komutu:

```bash
python -u ws_bot.py --sure-dk 30 --sembol-limit 0 --tp 0.8 --sl 0.5 --tut-dk 5 --giris limit --limit-payi 0.05 --limit-bekle-sn 30 --cascade-esik 1 --min-genislik 0 --binance-hacim-kaynagi aggtrade --indikator-hazirlik-oran 90 --indikator-hazirlik-okx-min 50 --indikator-hazirlik-binance-min 70 --indikator-hazirlik-zamanasimi-dk 75 --sinyal-zenginlestirme --kar-kilidi --no-defter-golge --v7-aday-karsilastir --vwap-tolerans-pct 0.2
```

Hazırlık, 30 dakikalık sayaçtan önce yapılır. Gerçek emir yoktur. `--vwap-tolerans-pct 0.2` açıkça verilmiştir; bu parametrenin varsayılanı 0 (katı VWAP), izin verilen deney aralığı 0–0,2'dir. LONG için VWAP'ın en fazla %0,2 altı ve SHORT için en fazla %0,2 üstü, diğer koşullar sağlanırsa kabul edilir. Eksik veri, ATR, CVD, MTF, funding/OI, teyit, limit ve risk kuralları korunur. Bu koşuda minimum genişlik 0'dır ve genişlik filtresi etkin değildir. Ayrıntılar ve veri kalitesi uyarısı için `30DK_VWAP02_TEST_SONUCU.md`.

## Testler hakkında
Bu deneyin kaynak çalışma alanında koşu öncesi `python -m pytest -q` sonucu 453 geçti. Paketlenmiş `tests/test_vwap_cvd_replay.py` eski analiz scriptine `/home/user/analiz_raporu/vwap_cvd/aday_sonrasi_analiz.py` mutlak yoluyla bağlıdır. Script referans için `ek_kaynak/aday_sonrasi_analiz.py` içinde aynen verilmiştir; bu dosyayı belirtilen yola yerleştirmeden veya testteki yolu uyarlamadan bütün testler başka makinede çalışmayabilir. Scriptin kendi CLI analiz akışı da eski koşunun harici verilerine bağlıdır; son koşu sonucu değildir.

## Dikkat
Test sırasında bağlantı sıfırlanması, yeniden bağlantı, 1.036 şüpheli aggregate-ID boşluğu ve son bölümde eksik göstergeler görüldü. Bu eksikler performans yorumunu sınırlar. Finansal tavsiye değildir.
