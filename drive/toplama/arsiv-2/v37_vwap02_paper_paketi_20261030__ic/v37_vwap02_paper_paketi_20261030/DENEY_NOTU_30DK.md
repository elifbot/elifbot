# Aktif %0,2 VWAP toleransı — 30 dakikalık izole paper deneyi

- 10 dakikalık önceki VWAP/CVD gözlemi ve orijinal ana ürün ayrı korunur. Bu klasör paper-only; gerçek/testnet emir göndermez.
- `--vwap-tolerans-pct 0.2`: LONG fiyatı VWAP'ın en fazla %0,2 altındaysa, SHORT en fazla %0,2 üstündeyse VWAP koşulu geçebilir. ATR minimumu ve eksik/bayat veri reddi korunur. Sadece deney CLI'si; 0 varsayılan katı kurala döner, değer 0–0,2 ile sınırlı.
- Aday gözlemi, v37 dedektör ve nihai paper giriş/teyit/limit kontrolü aynı tolerans kullanacak şekilde düzenlenmiştir. v7 aday yolunda orijinal v37 bağlamı reddeden adaylar 0,2 bandı, ardından mevcut MTF/funding/OI/CVD ve tüm paper korumalarından geçirilir; orijinal v37 bağlam yolu da çalışır. v7.8 adaptörü kapalıdır.
- %0,2 bandı giriş garantisi, ekonomik başarı veya geçmiş v7'nin birebir tekrarı değildir. Kayma, teyit, limit, komisyon ve risk davranışı eskisinden farklıdır.
- 30 dakikalık sayaç, Binance/OKX göstergeleri geçici %70/%50 hazırlık eşiğini geçtiğinde başlar. CVD, MTF/funding/OI, teyit, risk, limit, kâr kilidi açık. Min genişlik 0 ve cascade 1 bu kullanıcı testlerinde daha önce seçilmiş ayarlardır; genişlik aktif denmemelidir.
- Test suite: 453 geçti. Sinyal olayları `logs/ws_olay.csv`, band-only adayları `logs/v7_karsilastirma.jsonl`, paper işlemler `live_trades.csv`; ana ürün değiştirilmedi. Önceki koşunun sentetik test çıktıları temizlendi.
