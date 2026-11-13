# v4.0 kısa paper ayarları — test raporu

**Teknik bot sürümü:** v37  
**Paket/rapor etiketi:** v4.0  
**Kapsam:** Paper/replay; canlı veya testnet emirleri kullanılmadı.

## Uygulanan varsayılanlar

Güncellenen kaynak: `Futures_Bot_v37_Deneysel_Paper_SON/futures_bot_v37/ws_bot.py`.

| Ayar | Yeni varsayılan | Uygulama notu |
|---|---:|---|
| Cascade eşiği | `1` | Sinyal, denetimden önce 60 sn sayacına ekleniyor; kod `cascade_esik > 1` iken engelliyor. Dolayısıyla `1`, tek sinyal adayını cascade filtresinde engellemez. |
| Piyasa genişliği | `0.0` | Genişlik kapısı kapalı; ölçüm/sayaçlar kalabilir. |
| TP | `%0.8` | CLI ve `Bot.__init__` varsayılanı. |
| SL | `%0.5` | CLI ve `Bot.__init__` varsayılanı. |
| Azami tutma | `5.0 dk` | CLI ve `Bot.__init__` varsayılanı. |
| Giriş modu | `limit` | CLI ve `Bot.__init__` varsayılanı. Dolmayan paper limit emri bekleme süresi sonunda iptal edilir. |

İncelenen çalışma ağacında değişiklik öncesi bazı değerler istekte belirtilenlerden farklıydı: cascade sabiti `0`, genişlik `0.04`, CLI TP/SL/tutma `1.25/2.0/240`, `Bot.__init__` ise TP/SL/tutma `0.8/1.2/10` idi. Yeni değerler CLI, sınıf varsayılanları ve ilgili sabitlerde tutarlı hale getirildi.

`firsat_takasi` veya `cross_rescue` adıyla bir özellik Python kaynaklarında bulunmadı; bu nedenle kaldırılacak bir çapraz-kurtarma mekanizması yoktu. Bulunan pozisyon durumunu geri yükleme/kurtarma kodu, kâr eden işlemi zarardaki işlemi kapatmak için kullanmıyor.

### Maker komisyonu hakkında

Paper portföyünde maker giriş ücreti `%0.02`, taker ücreti `%0.05`. Dolan limit girişinin **giriş komisyonu**, aynı notional üzerinden market girişine kıyasla `%60` daha düşük modellenir (`0.03% × notional`). Çıkış ücreti taker olarak kalır; limit emrin dolması garanti değildir. Örnek olarak `25 USDT` marj × `10x` kaldıraçla `250 USDT` notional girişte teorik giriş komisyonu farkı `0.075 USDT` olur.

Bu koşuda hiçbir emir/pozisyon dolmadığı için **gerçekleşmiş komisyon tasarrufu 0.0000 USDT**. Yukarıdaki tutar yalnızca dolan her giriş için model varsayımıdır.

## Testler

- Odaklı regresyonlar: **24 geçti**.
- Tam test paketi: **428 geçti**, `32.05 sn`.
- Limit girişinin maker giriş ücreti ve taker çıkış ücreti muhasebesi mevcut regresyon testleriyle doğrulandı.
- `Bot.__init__` varsayılanları ve CLI yardımındaki varsayılanlar için kontroller eklendi.
- Varsayılan giriş modu market'ten limit'e geçtiği için, önceki testlerde anında market dolumu varsayan test düzenekleri açıkça `giris_modu="market"` olarak ayarlandı; böylece değişmeyen market davranışı izole biçimde test edilmeye devam ediyor.

## Yeni paper denemesi

**Kopya/çıktı dizini:** `/home/user/v37_paper_tuning_run_20261029_03/`  
**Çalışma:** `2026-10-29 20:20:02.226 UTC` – `20:37:09.493 UTC` (yaklaşık 17 dk 7 sn).  
**Ayarlar:** TP `%0.8`, SL `%0.5`, tutma `5 dk`, limit giriş, cascade `1`, genişlik `0`; aggTrade hacim kaynağı, sinyal zenginleştirme ve kâr kilidi açık.

İstenen **10 dakikalık ölçüm başlamadı**. Zamanlayıcı yalnızca her borsanın indikatör hazırlığı **%90'ın üzerine** çıktıktan sonra başlatılmalıdır. Bu koşu boyunca OKX kapsamı `13/22 = %59.09` düzeyinde kaldı (eşiği geçmek için en az `20/22` gerekir). Binance kapsaması dalgalandı; kapanış durumunda `501/522 = %95.98` idi. Bu nedenle katı, mevcut hazırlık kapısı doğru biçimde kapalı kaldı. Hazırlıkta sinyaller ölçüm/portföy hesabına alınmadı.

SIGTERM ile kontrollü durdurma kaydı: `logs/ws_kapanis.json` içinde `durum=tamamlandi`, `hata_turu=null`; `tarama_baslangic_utc=null` ve `sure_sn=0`.

| Metrik | Yeni denemede gözlenen durum |
|---|---:|
| Ölçüm zamanlayıcısı | Başlamadı (`0 sn`) |
| Ölçüme alınan sinyal | `0` — hazırlık öncesi sinyaller hariç |
| Açılan/kapanan pozisyon | `0 / 0` |
| Dolan/iptal edilen limit | `0 / 0` |
| Gerçekleşmiş komisyon | `0.0000 USDT` |
| Ölçülmüş net kâr | **Yok**; `0.0000 USDT` görünen hesap bakiyesi değişimi yalnızca hazırlık durumudur, 10 dk test sonucu değildir |
| Kapanış bakiyesi / açık pozisyon | `1000.00 USDT / 0` |

## Yorum ve sınırlamalar

Bu çalışmada istenen daha gevşek ayarlar koda işlendi, ancak OKX hazırlık kapsamı geçmediği için güncellenmiş filtrelerle 10 dakikalık sinyal/işlem etkinliği **ölçülemedi**. Ölçülmeyen komisyon tasarrufu veya net kâr hakkında sonuç çıkarmıyorum.

Ayrıca TP/SL ve tutma süresi pozisyon açıldıktan sonraki çıkış yönetimini etkiler; tek başlarına sinyal üretmez veya girişe izin vermez. Önceki başarılı 10 dk paper koşusunda zenginleştirmeye ulaşan aday sayısı `0` idi. Bu nedenle önceki `0 işlem` sonucunu yalnızca TP/SL değerlerine bağlamak mevcut kayıtlarla desteklenmiyor.

Bir sonraki deneme için güvenli yol, `%90+` borsa başına hazır olma şartını gevşetmeden OKX'teki eksik 9 sembolün kapalı 1 dakikalık indikatör geçmişinin neden oluşmadığını incelemek veya kapsam hazır olduğunda yeniden çalıştırmaktır. Bu raporda 10 dakikalık sonuç iddiası yoktur.

## Kanıt dosyaları

- Son durum ve kapsam: `v37_paper_tuning_run_20261029_03/logs/ws_durum.json`
- Kontrollü kapanış: `v37_paper_tuning_run_20261029_03/logs/ws_kapanis.json`
- Süreç tanısı/başlatma argümanları: `v37_paper_tuning_run_20261029_03/logs/process_diagnostics.jsonl`
- Çalıştırma parametreleri: `v37_paper_tuning_run_20261029_03/RUN_PARAMS.txt`
