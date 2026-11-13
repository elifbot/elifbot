# ACARBOT v6.1 — değişiklik ve doğrulama notu

Kaynak: kullanıcının Drive'a yüklediği `ACARBOT_FINAL_v5.6.2_TEMIZ.zip`. v6.1 eski motor üzerine sınırlı değişikliktir; yeni ve kârlı bir üretim stratejisi iddiası değildir.

1. Funding dosyası enstrüman anahtarları, borsa önekli motor anahtarlarına eşlenir; istenen tüm sembollerde eşleşme yoksa tam kapsama raporlanmaz (`backtest/funding.py`, `tools/validate_strategy.py`).
2. 1m önbelleğindeki birbirinden kopuk pencereler arasında veri varmış gibi davranılmaz (`tools/validate_strategy.py`).
3. İsteğe bağlı `--require-cost-coverage` spread/giriş/çıkış kayması kaydı olmayan sembolleri reddeder. Bu kayıtların gerçekten doğru veya güncel olduğunu ispatlamaz.
4. Yalnız araştırma için momentum/pullback aracı, örnek bölme, gün bootstrap ve 18 yeni test (`tools/momentum_research.py`, `tests/test_v61_research.py`). Gerçek emir yoluna eklenmedi.
5. 6 sembol / yaklaşık 90 günlük araştırma raporu `docs/momentum_v6.1.json`: maliyet varsayımı sonrası, funding hariç ilk dönem −0,288R ve son dönem −0,275R. Bu çalışma üretim backtesti değildir.
6. Eski dokümanlar, tarihsel veri ve `.env` yeni dağıtım dışında bırakıldı. Orijinal Drive kaynağı korunur.

## Güvenlik ve eksikler

- Canlı izin listesi boş ve kenar şartı etkin; kârlılık yok. Testnet elle açılan özellik olarak korunur.
- Üretim motoru 5m'dir; 1h üretim uyarlaması ve tam doğrulama yapılmadı.
- Funding verisi, gerçek maliyet ölçümü, 12 ay/30–50 sembol ve bağımsız nihai OOS eksik.
- Tam yayın regresyon referansı bilinçli olarak oluşturulmadı. `tools.package_release` referans yokken hata vermeye devam eder. Bu, kanıt olmadan yeşil kapı üretmemek içindir.
- Temizlenmiş pakette artık mevcut olmayan geçmiş belge/referansa bağlanan eski testlerin atlanması veya başarısız olması mümkündür; tam test raporunda açıkça gösterilmelidir.
