# İşletme kılavuzu

## Elle kontrol (Telegram komutları gelene kadar)
- `touch data/PAUSE` → yeni giriş durur (açık pozisyonlar yönetilmeye devam eder). Dosyayı silince devam eder.
- `touch data/CLOSE_ALL` → tüm pozisyonları kapatır (dosya otomatik silinir).
- Teknik arızada bot kendiliği durur: veri bayatlığı ve API hataları düzelince otomatik devam eder;
  borsa/bot pozisyon uyuşmazlığı ve stop emri konulamaması **elle devam** gerektirir (neden alarmda yazar).

## Sonuçları değerlendirme (SQLite)
```bash
sqlite3 data/tradebot.db "select exchange, count(*), round(sum(pnl_net),2), round(avg(pnl_net),2) from trades group by exchange;"
sqlite3 data/tradebot.db "select reason, count(*), round(avg(pnl_net),2), round(sum(pnl_net),2) from trades group by reason;"
sqlite3 data/tradebot.db "select decision, count(*) from signals group by decision order by 2 desc;"
```
İzlenecekler: **net** kâr (komisyon dahil), ortalama kazanç/ortalama kayıp, isabet oranı, maksimum düşüş,
maker dolum oranı (özet mesajında: giriş istendi / dolan / iptal), aynı anda açık pozisyon sayısı (en kötü an).

## Canlıya geçiş ölçütleri (öneri — siz belirleyin, yazılı tutun)
- Gerçek veriyle paper: en az 4-6 hafta, en az 100 kapanan işlem; net beklenen değer pozitif.
- Paper sonuçları ile testnet sonuçları tutarlı; son 2 haftada kritik hata/uyuşmazlık yok.
- Stop emirlerinin borsada gerçekten durduğu testnet'te gözle doğrulandı.
- İlk canlı adım: çok küçük marjin (örn. 10$), sonra kademeli.

## Bilinen sınırlar (v0.1)
- Göstergeler 1 dk mumlarla ~36 dk ısınır; açık pozisyon (OI) ve emir defteri özellikleri henüz yok.
- Funding paper'da simüle edilmez. Paper çıkışlar taker modellenir (muhafazakâr).
- Live çıkış: taker (piyasa). "Önce maker dene" çıkışı henüz yok.
- Pozisyon modu tek yönlü (one-way/net) varsayılır; hedge modu desteklenmez.
- İki borsa ayrı cüzdan: bakiye (örn. 500/500) arasında transfer elle yapılır.
- Paper'da bot yeniden başlayınca sanal pozisyonlar sıfırlanır.

## Canlı kullanımdan önce DOĞRULANACAKLAR (ağ olmadan yazıldı)
- Binance futures WebSocket adresi ve bağlantı başına akış limiti; OKX abonelik ve bağlantı limitleri (kodda küçük parçalar kullanıldı).
- Komisyon oranları (hesap seviyenize göre `maker_fee` / `taker_fee`).
- OKX `trades` kanalındaki `sz` biriminin (kontrat) `ctVal` ile çevrimi: birkaç sembolde elle karşılaştırın.
- CCXT post-only ve stop-market parametrelerinin her iki borsada testnet/demo'da beklendiği gibi çalışması.
- `universe` komutunun gerçekte kaç coin döndürdüğü (`min_24h_volume_usd` ayarı ile oynanır).
