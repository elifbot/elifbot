# Binance / OKX — uygulama ve durum

## Kullanım
```
# Tüm aktif USD-M + COIN-M ve OKX SWAP + FUTURES evrenini keşfet;
# anlık quote ve 5dk mum kontrolü, işlem açmadan:
python -m acarbot.futures_scan --out runs/tarama

# Tüm erişilebilir enstrümanları kullan; 10dk PAPER çalışması:
python -m acarbot.futures_paper --duration 600 --out runs/paper-binance-okx
```
`--limit-per-market` yalnız kısa tanı içindir; varsayılan 0 = limit yok.
Kaynaklar: Binance `fapi`/`dapi`, OKX kamu `SWAP`/`FUTURES`. Enstrüman
anahtarı borsa + pazar + sözleşme içerir. Kullanılamayan borsa başka
borsanın verisiyle veya testnet ile değiştirilmez. Kısıtlı ortamın verdiği
HTTP 451 açıkça kaydedilir.

## Temel ayrım: gözlem ve PAPER kapsamı
Keşif ve mum taraması: erişilebilir her aktif vadeli sözleşme. Sembol listesi
koşu başında alınır; sonradan listelenenler bir sonraki koşuda görülür.

PAPER açılışı: yalnız USDT lineer sürekli sözleşmeler (OKX SWAP ve Binance
USD-M PERPETUAL). Coin-margined/inverse, USDC ve teslimatlı/X-perp ürünler
keşfedilir ve gözlenir, **PAPER pozisyon açılmaz**: farklı sözleşme büyüklüğü,
kâr/zarar ve takas hesabı henüz doğrulanmadı. Bu yüzden tüm futures üzerinde
PAPER işlem desteği tamamlanmış değildir, sonuç PARTIAL kalır.

Gerçek emir gönderen yol yoktur. Stop/TP, funding, derinlik ve dolum
sınırlamaları `README.md` içinde açıklanmıştır. Bağımsız model incelemesi
strateji tasarımı içindir, otomatik işlem hakemi değildir.

## Bu ortamın 5 Kasım 2026 canlı taraması
`runs/binance-okx-futures-tarama-20261105/SONUC.json`: Binance USD-M ve
COIN-M HTTP 451; OKX 540 SWAP + 287 FUTURES = 827 aktif enstrüman keşfedildi,
827 quote ve 827 mum yanıtı alındı. Tarama PARTIAL. Tarama saati nedeniyle
827 mumun hepsi kararın 90 saniyelik maksimum yaş sınırını geçti; bunlardan
stratejik sinyal/işlem performansı sonucu çıkarılmaz. Bu, gerçek emir veya
10dk PAPER koşusu değildir.

Deneme: `runs/binance-okx-paper-ontest20-20261105` = 40 OKX enstrümanla
15 saniyelik teknik ön kontrol; 0 PAPER işlem, Binance 451, sonuç PARTIAL.
Tek başına işlem yaşam döngüsünün çalıştığını ispatlamaz.

## Sınırsız evrenle PAPER koşusu
`runs/binance-okx-paper-10dk-son-20261105/SONUC.json`: hedef 600 saniye,
ölçülen aktif süre **613,942 saniye**; toplu mum taramasının son çevrimi
nedeniyle süre uzadı. Durum **PARTIAL**. OKX 827 enstrüman seçildi;
525'i lineer USDT perpetual PAPER için uygun, 302'si yalnız gözlem.
Binance'in iki pazarı da 451 verdi. 1.654 mum değerlendirmesinden 763'ü
90 saniyelik tazelik sınırını aştığı için reddedildi; dolayısıyla bu koşu
bütün enstrümanları zamanında taramanın sağlandığını göstermez.

129 strateji sinyali görüldü; 54'ü desteklenmeyen sözleşme türü, 28'i
makas, 27'si maliyet, 18'i fiyat sapması nedeniyle reddedildi; 2 sanal
pozisyon açıldı ve koşu sonunda kapandı. Varsayımsal ücret ve kayma dahil
net **-0,704494 USDT**; gerçek emir 0. 4.962 başarılı mum isteği, 192 başarılı
ticker isteği; 79.392 taze quote gözlemi (benzersiz enstrüman sayısı değil).
İki işlemin de kapanış nedeni RUN_END; stop/TP/funding kapanışını bu gerçek
verili koşu doğrulamaz. Bu kısa, kısmi örneklem kârlılık ya da gerçek para
uygunluğu kanıtı değildir.
