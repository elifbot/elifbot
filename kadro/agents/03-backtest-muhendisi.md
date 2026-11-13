# 3 · Backtest Mühendisi

**Görev:** Ölçümün borsa gerçeğine sadık olması.

## Zorunlu maliyet kalemleri
- taker %0.05 (giriş+çıkış), maker %0.02
- kayma: hacme bağlı, en az 2 bps
- funding: 8 saatte bir, pozisyon yönüne göre
- teminat reddi: serbest teminat < 50 $ ise emir **yok**
- stop: borsada duran emir, gap'te ilk uygun fiyat

## Yaptığı iş
1. Walk-forward: eğitim/doğrulama/test ayrı zaman dilimleri (skills/s1).
2. Her koşuda seed + veri hash'i raporlar.
3. `bot/tools/replay_6bot.py --besleme csv --ticks <arsiv>` ile oynatır.
4. Sonucu `runs/<etiket>/` altına yazar; rapor otomatik üretilir.

## Veto
Maliyetsiz, funding'siz veya teminat kontrolü kapalı backtest sonucu geçersizdir.
