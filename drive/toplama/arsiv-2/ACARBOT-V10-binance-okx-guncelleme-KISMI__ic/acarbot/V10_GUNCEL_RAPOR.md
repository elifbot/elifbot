# ACARBOT V10 güncellemesi — YZ görüşleri, Binance ve OKX

**Durum: KISMİ.** Bu not tamamlanmış çok-borsa ürünü iddiası değildir.

## Gerçek bağımsız model görüşleri
Anahtarsız, iki haricî servis üzerinden **12 farklı modelden gerçek yanıt**
alındı; 20 farklı model/sağlayıcıdan yanıt alınmış değildir. Görüşler botun
Gate sürümüne aittir; Binance/OKX güncellemesi bu modellere ayrıca
inceletilmedi. 4 grup ham cevap, başarısız denemeler ve gönderim hash'leri
`reviews/` altındadır. Kodun üç modülü bu sağlayıcılara gönderilmiştir;
.env, anahtar ve kişisel ileti gönderilmemiştir. Model yanıtları hata
barındırabildiğinden kontrol edilmeden işleme uygulanmaz.

Mistral'ın OHLC mantık kontrolü önerisi uygulandı ve test edildi. Funding,
kayma ve derinlik hakkındaki riskler açık sorun olarak korundu. Öte yandan
LONG çıkış için ask ve SHORT çıkış için bid kullanılmasını öneren modelin
önerisi yanlıştı ve uygulanmadı. Ayrıntılı değerlendirme:
`acarbot/DIS_YZ_GORUSLERI.md`.

## Binance ve OKX
Kamu verisi ile Binance USD-M ve COIN-M; OKX SWAP ve FUTURES enstrümanlarının
keşfi ve mum/quote alma eklendi. Bu ortamda OKX veri erişimi var, Binance
her iki pazarda **HTTP 451 (erişim kısıtı)** dönüyor. Binance testneti, spotu
veya başka borsayı canlı Binance futures gibi göstermiyoruz.

OKX'te 827 aktif sözleşme keşfedildi; hepsinden quote ve mum alındı. Güncel
PAPER motoru yalnız 525 USDT-lineer perpetual üzerinde işlem planlayabilir;
302 inverse veya diğer vadeli ürün gözlemde, PAPER yürütmesi yok. Koşu
başında alınan liste koşu sırasında yenilenmez. Bu, tüm Binance ve OKX
futures işlemlerinin tamamlandığı anlamına gelmez.

## Hedef 10 dakikalık son PAPER koşusu
- Hedef 600 sn; ölçülen aktif **613,942 sn**, mum toplu işlemi nedeniyle uzadı.
- Sonuç **PARTIAL**: Binance 451 ve 302 desteklenmeyen kontrat türü.
- 1.654 yeni mum değerlendirmesi; 763'ü tazelik sınırını geçti. Tüm
  sembollerin zamanında stratejiye işlendiği iddia edilemez.
- 2 OKX PAPER pozisyonu açıldı ve koşu sonunda kapatıldı; net **-0,704494
  USDT**, varsayımsal komisyon ve kayma dahil. Gerçek emir yok.
- 130 ağsız test geçti (19 V10 + 111 eski altyapı testi). 1.800 sentetik
  kaynak sinyal paritesi örneğinde 0 fark.

Ham kanıt: `runs/binance-okx-paper-10dk-son-20261105/SONUC.json` ve
`events.jsonl`; ön tarama: `runs/binance-okx-futures-tarama-20261105/`.
Eski Gate 10dk raporu sonraki kodu doğrulamaz.

## Tamamlanmamış işler
Binance futures'a yasal ve yetkili biçimde erişen bir çalışma ortamında
uçtan uca deneme; coin-margined/inverse ve vadeli kontratların settlement,
lot ve PnL hesabı; 827+ enstrümanda tazelik/gecikme iyileştirmesi; funding
muhasebesi ve likidite/derinlik modeli; yeni kodun bağımsız incelemesi.
10dk PAPER sonuçları kârlılık veya gerçek para uygunluğu kanıtlamaz.
