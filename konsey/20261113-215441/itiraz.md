## test
**Katıldığım nokta:** `REJIM_DONUS` kaynaklı yüksek churn ve düşük WR'nin sistemi negatif beklentiye sürüklediği kanıtlanmıştır.

**İtirazlar:**

1. **Yama 1 (Teyit Mekanizması):** "Ardışık 2 mum" önerisi varsayımsaldır; mevcut veri setinde 1 mumluk gürültü ile gerçek rejim değişimi arasındaki zaman farkına dair bir **gecikme/kayma (lag) analizi kanıtı** yoktur.
2. **Yama 2 (Giriş Filtresi):** Sinyal sıklığının azaltılması önerisi, düşük WR'nin "fazla işlemden" mi yoksa "yanlış yönden" mi kaynaklandığını ayıran bir **korelasyon kanıtı** sunmamaktadır.
3. **Ops (RestartRecovery):** 7/24 çalışma gereksinimi operasyonel bir istektir; mevcut smoke test verilerinde sistemin çöktüğüne veya state kaybı yaşadığına dair bir **hata logu/crash kanıtı** yoktur.

## olcum
**Katıldığım nokta:** REJIM_DONUS kaynaklı yüksek churn ve komisyon erimesi tespiti doğrudur.

**İtirazlar:**

1. **Yama 1 (ATR Teyidi):** Önerilen `atr * 0.2` katsayısının hangi veri setine veya optimizasyon testine dayandığı belli değil; sayısal kanıttan yoksun, tahmindir.
2. **Yama 2 (BE Optimizasyonu):** Mevcut trailing stop'un hangi fiyat seviyelerinde tetiklendiğine dair işlem bazlı veri (trade log) sunulmamıştır; sorun varsayımsaldır.
3. **Ops (RestartRecovery):** Mevcut sistemin kopma sıklığına veya hata loglarına dair bir kanıt sunulmadan "asgari gereksinim" olarak eklenmesi gereksiz karmaşıklık yaratır.

## ops
**Katıldığım nokta:** `REJIM_DONUS` kaynaklı yüksek churn ve komisyon erimesi tespiti doğrudur.

**İtirazlar:**

1. **Yama 1 (Teyit Mekanizması):** `regime_duration >= 3` önerisi keyfidir; hangi zaman diliminde veya hangi volatilite koşulunda 3 barın yeterli olduğuna dair veri kanıtı sunulmamıştır.
2. **Yama 2 (Sinyal Filtresi):** Sinyal sıklığını azaltma önerisi, mevcut %15.9'luk düşük WR'nin "yanlış sinyal"den mi yoksa "yanlış zamanlama"dan mı kaynaklandığına dair ayrıştırılmış bir kanıta dayanmamaktadır.
3. **Operasyonel Gereksinimler:** `RestartRecovery` ve `EmergencyController` önerileri standart prosedürdür; mevcut sistemin hangi spesifik kopma noktalarında çöktüğüne dair bir hata logu kanıtı yoktur.