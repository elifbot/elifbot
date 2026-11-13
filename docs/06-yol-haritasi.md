# 06 · Yol haritası

## Şimdi neredeyiz

- 6 bot tek akışta koşuyor, panelde 6 dikey kart olarak izleniyor.
- Orijinal paketteki 5 yapısal hata bulundu, 2'si koda yamalandı (stop −10, teminat fiziği).
- v8 motoru yazıldı: kurala sabit, stop borsada, teminat fiziği ve tasfiye modelli.
- 38 test yeşil; kural testleri sayıları kilitliyor.
- **Eksik:** gerçek piyasa verisi (ağ kapalı) → kenar ölçümü yapılmadı.

## Sıradaki işler (öncelik sırası)

### 1. Gerçek tick arşivi (engelleyici)
30 gün × 30+ sembol tick verisi. Kaynak: `data.binance.vision` (aggTrades), OKX `trades`,
veya kendi kaydın. Geldiği an:
```bash
python3 bot/tools/replay_6bot.py --besleme csv --ticks arsiv.csv --dakika 43200 --etiket gercek_30g
```
Kabul: rapor `besleme: GERCEK PIYASA VERISI` + veri sha256.

### 2. v8 canlı adaptör entegrasyon testi
Binance testnet + OKX demo (`x-simulated-trading: 1`) ile 7 gün. Emir/iptal/amend
döngüsü, uzlaştırma, kopma senaryoları.

### 3. Funding + likidasyon cezası
Simülasyona 8 saatlik funding ve MMR kademeleri. Şu an basitleştirilmiş.

### 4. Sinyal seçkisi
Gerçek veride 3 dedektörün ayrı ayrı katkısını ölç (`skills/s7`), negatif katkılı olanı kaldır.

### 5. Panel
WebSocket push (şu an 3 sn polling), işlem bazlı PnL dağılım grafiği, günlük rapor.

### 6. 30 gün paper
`skills/s8` kapısı: 30 gün kesintisiz, kopma < 0.1/gün, tasfiye 0.
Hepsi geçerse **pilot**: 10 $ teminatla canlı.

## Yapılmayacaklar (bilinçli)

- Kural sayılarını "daha kârlı olur" diye değiştirmek.
- Gerçek veri olmadan "şu bot kazanıyor" demek.
- Sentetik sonucu performans kanıtı olarak sunmak.
- Kaldıracı artırmak: 10x kuraldır, kenar değildir.
