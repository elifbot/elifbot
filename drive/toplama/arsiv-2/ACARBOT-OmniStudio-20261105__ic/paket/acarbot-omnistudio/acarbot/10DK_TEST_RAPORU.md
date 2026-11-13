# ACARBOT V10 — 10 dakikalık PAPER testi

Tarih: 5 Kasım 2026. Kaynak: `acarbot-system (1).html`.
Kanıtlar: `runs/acarbot-v10-10dk-20261105/SONUC.json`,
`config.json`, `events.jsonl`.

## Sonuç
- Durum: **COMPLETED**, aktif süre **600,002 saniye**; toplam 612,150 sn.
- Gerçek kamu piyasa verisi: **Gate.io USDT perpetual**, 20 önceden
  belirlenmiş kripto sözleşmesi; EMA trend, 5 dakikalık kapanmış mum.
- 2.300 başarılı alış/satış fiyatı sorgusu, 600 başarılı mum veri isteği;
  toplam 3.002 başarılı REST isteği, **0 REST hatası**, 0 HTTP 429.
  Bu koşu WebSocket değil REST kullanmıştır.
- 40 yeni sembol-mum değerlendirmesi, 8 strateji sinyali; 7 maliyet/ATR
  kapısında, 1 makas kapısında reddedildi. Diğer mumlar: 22 sinyal yok,
  3 teyit yok, 7 hacim teyidi yok.
- **0 açılan / 0 kapanan PAPER işlem**; gerçekleşmiş net 0 USDT, başlangıç
  ve gerçekleşmiş özsermaye 1.000 USDT. Hiçbir gerçek emir gönderilmedi.
- Kural konseyi modu yapılandırıldı, fakat 8 sinyalin tamamı konseye
  ulaşmadan reddedildi: bu koşuda konsey çağrısı **0**. Bununla konseyin
  veya işlem açma/kapatma yaşam döngüsünün canlı işleyişi doğrulanmış sayılamaz.
- En uzun gözlenen çevrim aralığı 12,109 sn; bu bir uptime garantisi değildir.

## Ağsız kontroller
- `python test.py`: **124/124 test** (13 V10 + 111 mevcut OmniStudio).
- `python -m acarbot.parite`: son HTML JavaScript sinyal kurallarıyla 300
  sentetik seri × 6 strateji = 1.800 karar, **0 uyuşmazlık**. Bu sınırlı
  örnekleme tüm olasılıkların veya bütün botun eşdeğerliği değildir.
- 13 V10 testinde sanal LONG stop, SHORT hedef ve takip stop örnekleri vardır;
  bunlar sentetik birim testleridir, bu koşudaki canlı PAPER işlemler değildir.

## Sınırlamalar
Diğer yapay zekâların fikirleri API anahtarı olmadığı için alınmadı. 20 kural
profili gerçek model yanıtı değildir. Sadece EMA trendi bu koşuda denenmiştir.
Orijinal HTML'nin grafik/lab/backtest ve bütün borsaları Python'a taşınmamıştır;
sonuç varsayımsal ücret ve kayma içerir, piyasa derinliği ve funding
muhasebesi yoktur. Bu kısa test kârlılık veya gerçek para uygunluğu kanıtlamaz.
