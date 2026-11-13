# ACARBOT V10 — eski botlardan Binance/OKX bağlantı düzeltmesi

**Durum: KISMİ / yalnız PAPER.** 5 Kasım 2026. Bu sürüm tüm sözleşmelerde işlem desteği veya gerçek para onayı değildir.

## Önceki hata ve eski kaynaklar
Kullanıcı haklıydı: maildeki eski botlarda Binance ve OKX bağlantısı vardı. Özellikle v8.4 `scanner/binance_flow.py` ve v9.5.3 `src/exchanges.py`, Binance kamu `www.binance.com/fapi/...` yolunu kullanıyordu. V9.5.3 kaynak ZIP'i ve tarihsel test kanıtı mailden indirildi, SHA-256 ve ZIP CRC doğrulandı. Detaylar `acarbot/GECMIS_BOT_KANITLARI.md`.

Önceki testte yalnız Binance'in belgelenmiş `fapi.binance.com` ve `dapi.binance.com` uçları denenmişti; bunlar bu ortamda 451 döndü. Eski botun kamu `www` yolu atlanmıştı. Bu düzeltme o yolu yalnız **imzasız kamu verisine** uyguladı. USD-M ve COIN-M katalog, teklif ve mum uçları gözlendi; Binance USD-M vadeli WebSocket'inden gerçek `aggTrade` mesajı ayrıca alındı. Bu test çalışan PAPER motoruna WebSocket akışı entegre edildiği anlamına gelmez: motor REST kullanır. `www` yolunun standart futures API temeli olarak resmî belgede yer aldığı veya sürekli çalışacağı doğrulanmamıştır; hiçbir özel hesap/gerçek emir yolu bu alana yönlendirilmemiştir.

V10'un COIN-M enstrümanlarında `status` yerine `contractStatus` okunması gerektiği saptanıp düzeltildi. Geçmiş v9.5.3 sürümü iki borsayı destekliyordu ama kendi katalog kodu USDT lineer perpetual ile sınırlıydı; tüm inverse, teslimatlı ve USDC sözleşmelerde işlem desteği olarak sunulamaz.

## Bağlantı / evren kontrolü
| Pazar | Aktif keşfedilen | Fiyat yanıtı bulunan |
|---|---:|---:|
| Binance USD-M | 804 | 804 |
| Binance COIN-M | 30 | 30 |
| OKX SWAP | 540 | 540 |
| OKX FUTURES | 287 | 287 |
| **Toplam** | **1.661** | **1.661** |

Bu bir anlık yanıt sayısıdır; her teklifin eş zamanlı taze olduğu iddiası değildir. Liste sadece koşu başlangıcında yenilenir. `runs/binance-okx-eski-bot-baglanti-evren-duzeltilmis-20261105/SONUC.json` bağlantı gözleminde COMPLETE demek **yalnız keşif/quote adımı tamamlandı** demektir, işlem kapsamı tamamlandı demek değildir.

## Toplu bekleme sorunu ve ikinci koşu
İlk dört pazar PAPER koşusunda tüm mumları beklemek nedeniyle 3.322 değerlendirmenin tamamı eski mum olarak reddedildi; hedef 600 saniye iken toplu istek 859,354 aktif saniyeye uzadı. `runs/binance-okx-eski-bot-baglanti-10dk-duzeltilmis-20261105/`.

Düzeltmede her sözleşme veri gelir gelmez değerlendirilir; süre bitiminde bekleyen görevler iptal edilir. Eski mum kontrolü 90 saniye olarak korunur. Ağsız test, hızlı sembolün yavaş sembolü beklemediğini ve deadline sonunda bekleyen isteğin iptalini doğrular. Bu, önceki WebSocket kodunun bütünüyle V10'a taşındığı anlamına gelmez.

### Son gerçek veri PAPER sonucu
`runs/binance-okx-geldikce-degerlendirme-10dk-20261105/SONUC.json` ve `events.jsonl`:
- **600,038 saniye aktif**, başlangıç ısınması dahil **865,404 saniye**; sonuç **PARTIAL**.
- Dört pazarın tamamı erişilebilir; 1.661 sözleşme keşfedildi ve başlangıçta en az 250 kapanmış mumla hazırlandı.
- 1.047 sözleşme PAPER motorunun USDT-lineer perpetual filtresinden geçer; **614 sözleşmede PAPER açılmaz**. Keşif/gözlem ile sözleşmeye özgü PnL/lot/settlement desteği farklıdır.
- 5.187 başarılı mum isteği; 2.735 yeni mum değerlendirmesi. **1.402'si (%51,3) tazelik sınırında reddedildi.** Her sözleşmenin her yeni mumunun zamanında işlendiği kanıtlanmadı.
- 5 sanal pozisyon açıldı: 1 Binance USD-M ve 4 OKX SWAP. **Hepsi koşu sonunda RUN_END nedeniyle kapandı**; doğal stop, hedef, funding veya gerçek borsa dolumu doğrulanmadı.
- Varsayımsal komisyon ve kayma dahil net **−3,996898 USDT**, 1.000 başlangıçtan **996,003102 USDT** sanal özvarlık; gerçek emir **0**. Bu örnek kârlılık veya zarar sınırı garantisi değildir.
- 129.794 taze quote gözlemi benzersiz sözleşme sayısı değil, tekrar eden gözlemlerdir. Alınan piyasa verisi gerçek; dolum, lot, ücret ve kayma simüledir. OKX sembolleri içinde borsanın sentetik hisse temalı vadeli kontratları da bulunabilir; bu sürüm tüm futures keşfi nedeniyle geçmiş botun yalnız kripto filtresini aynen uygulamaz.
- **133 ağsız test geçti**, 1.800 sentetik HTML karar-paritesi karşılaştırmasında 0 fark. Bunlar yatırım performansı testi değildir.

## Devam eden eksikler
1. Inverse/COIN-M, USDC, teslimatlı ve diğer uyumsuz türlerde sözleşme büyüklüğü, teminat/settlement, PnL ve emir adımı doğrulanmadığından PAPER işlem yok.
2. Toplu yük ve tazelik sorunları sürüyor; quote ve mum güncellemelerinde uzun süreli dayanıklılık ve her sembolün zamanında işlenmesi kanıtlanmadı. Koşu başı ısınma yaklaşık 265 saniye sürdü.
3. Funding muhasebesi, emir defteri derinliği ve gerçek borsa dolumu modellenmiyor. v9.5.3 saat/süreklilik denetimlerinin tamamı bu V10 çalıştırıcısına taşınmadı.
4. 12 haricî modelin gerçek yorumları önceki Gate çekirdeğine aittir; bu yeni Binance/OKX güncellemesine ayrı uygulanmış hakem tartışması değildir. `DIS_YZ_GORUSLERI.md`.
5. Sonuç PAPER ve kısa süreli bir araştırmadır; gerçek para veya 7/24 hizmet onayı yoktur.

## Kullanım
```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 test.py
python3 -m acarbot.futures_scan --no-candles --out runs/yeni-evren
python3 -m acarbot.futures_paper --duration 600 --out runs/yeni-paper
```
Yeni boş `--out` klasörü gerekir; kısmi koşu `PARTIAL` raporlar ve çıkış kodu 1 olabilir. Gerçek para API çağrısı bu çalıştırıcıda yoktur.
