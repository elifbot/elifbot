# 30 dakikalık %0,2 VWAP paper testi — sonuç

## Kimlik ve süre
- Sürüm: **v37 tabanlı, v7-benzeri aday yolu ve aktif %0,2 VWAP toleransı içeren deneysel paper kopyası**. Resmî yeni sürüm veya eski v7'nin birebir kopyası değildir. v7.8 akış adaptörü kapalıdır.
- 30 Ekim 2026, ana sayaç 07:31:41–08:01:42 UTC (Türkiye 10:31:41–11:01:42), 1801 saniye. Süre öncesinde gösterge hazırlığı yapıldı; sayaç başlangıcında Binance 522/522, OKX 22/22 hazırdı.
- Kapanış normal, çıkış kodu 0; `logs/ws_kapanis.json` ve `logs/ws_durum.json` kapanış sonrası kayıtlardır. Gerçek borsa veya testnet emri yoktur.

## Sonuç
| Ölçüm | Değer |
|---|---:|
| v7-benzeri ilk aday | 175 |
| Göstergeyi geçerek sonraki kontrollere sevk edilen | 41 |
| Bunların yalnız %0,2 toleransı sayesinde geçenleri | 16 |
| VWAP yön reddi | 108 |
| Gösterge verisi yok | 25 |
| ATR düşük | 1 |
| Zenginleştirilen / girişe uygun bulunan | 41 / 0 |
| Açılan / kapanan / açık paper pozisyon | 0 / 0 / 0 |
| Net PnL / son bakiye | 0 / 1.000 USDT |

Bir adet aday ayrıca bayat olarak sayılmıştır; sayaçlar farklı aşamaları ölçer, bu yüzden kategorileri zorla toplayıp bağımsız sonuçlar gibi yorumlamayın. Bant sayesinde geçen 16 aday kesinlikle işlem açardı anlamına gelmez. Zenginleştirmede 40 adayda CVD akışı giriş yönüne karşı, 24'ünde MTF karşı, 1'inde funding karşıydı. Bu ret nedenleri çakışır; 41 ayrı adayın tamamı engellenmiştir. CVD 15 saniyelik yönlü akış, MTF ve diğer filtreler sonraki anda değerlendirilir; aday anı gölge ölçümle aynı olması gerekmez. CSV'deki `taker_buy_sell_ratio_15s` alanı SHORT için giriş yönlü sell/buy oranıdır, daima buy/sell değildir.

## Veri güvenilirliği ve son bölüm
07:52:33 UTC'de Binance REST bağlantısı sıfırlandı; ardından OKX ve Binance akışları yeniden bağlandı. Son durumda Binance aggTrade bağlantı sayacı 9, şüpheli aggregate-ID boşluğu 1.036; 209 gecikmiş aggTrade kaydı da bayat diye reddedildi. Şüpheli ID boşluğu tek başına kesin veri kaybı kanıtı değildir; fakat kesintisiz ve tam akış da doğrulanamaz. Bağlantı sayacı toplamıdır, tamamı hata sayısı değildir. `logs/30dk_vwap02.log`, `logs/ws_durum.json` ve `logs/process_diagnostics.jsonl` kanıtları içerir.

Son sevk edilen v7-benzeri aday 07:50:38 UTC'de kaydedildi. 07:52:33'ten sonra kayda geçen 24 adayın tamamı `indikator_veri_yok` nedeniyle sevk edilmedi. Olaylar zamansal olarak yeniden bağlantı ile ilişkilidir, ancak bağlantı kopmasının bu eksik verinin kesin nedeni olduğu bu koşuda doğrulanmadı. Sıfır işlem sonucunun özellikle son bölümde veri eksikliğinden etkilendiği göz önünde bulundurulmalı; bu test kârlılığı veya strateji başarısını ölçmez.

## Testin sınırları
Varsayılan katı tolerans 0'dır; %0,2 sadece CLI ile açılan deneydir. MTF, CVD, funding/OI, tazelik, teyit, limit ve risk denetimleri korunmuştur. Bu koşu için `--min-genislik 0` olduğundan genişlik eşiği etkili değildir; `--cascade-esik 1`. %0,2 testi geçmiş v7 stratejisinin tam bir tekrarını oluşturmaz. Önceki testlerin kâr/zararı bu sonuçla birleştirilmemiştir. Test öncesi kaynak çalışma alanında 453 test geçti; koşuda işlem çıkmadığından emir yürütme ve pozisyon kapama mekanizmaları bu koşuda doğrulanmış sayılmaz.

## Kaynaklar
- `logs/ws_durum.json`: son sayaçlar; `logs/ws_kapanis.json`: normal kapanış ve zaman damgası.
- `logs/v7_karsilastirma.jsonl`: 175 aday ve bant/gölge ölçümleri.
- `logs/ws_sinyal_zenginlestirme.csv`: 41 adayın sonraki filtre sonuçları; `logs/ws_olay.csv`: olay kayıtları.
- `live_trades.csv`: yalnız sütun başlığı, kapanmış işlem yok. Tüm gerçek son koşu logları (kilitler hariç) pakettedir.
