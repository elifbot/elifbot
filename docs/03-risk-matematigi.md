# 03 · Risk matematiği

Bu doküman görüş içermez; kuraldan türeyen aritmetiği yazar. `python3 -m bot.v8.cli kurallar`
aynı tabloyu canlı üretir.

## 1. Pozisyon

```
notional      = 50 $ × 10 = 500 $
gidiş-dönüş   = 500 × 0.0005 × 2 = 0.50 $
stop fiyatı   = (10 − 0.50) / 500 = %1.90   (+5 bps kayma payı → %1.95)
```

Yani BTC 60.000 $ iken LONG giriş 60.000 ise stop ≈ 58.830; net kayıp −10 $.
**Komisyon, stop bütçesinin %5'i.** Yüksek frekansta bu kalem stratejiyi belirler:
40 işlem/gün × 0.50 $ = 20 $/gün = kasanın %2'si, sadece komisyon.

## 2. Aynı anda kaç pozisyon?

```
kapasite = kasa / teminat = 1.000 / 50 = 20
komisyon sonrası gerçek sınır = 19
```

Bu, borsanın "insufficient margin" reddinin matematiksel karşılığıdır.

## 3. Hesap kaldıracı ve tasfiye

Hesap kaldıracı = `(n × 500) / kasa`. CROSS marjinde tasfiye mesafesi
(bakım marjı %0.5 varsayımı):

| n | notional | hesap kaldıracı | % hareket → tasfiye |
|---|---|---|---|
| 1 | 500 | 0.5x | %199.5 |
| 5 | 2.500 | 2.5x | %39.5 |
| 10 | 5.000 | 5.0x | %19.5 |
| **20** | 10.000 | **10.0x** | **%9.5** |
| 40 | 20.000 | 20.0x | %4.5 |
| 100 | 50.000 | 50.0x | %1.5 |
| 170 | 85.000 | 85.0x | %0.68 |

Orijinal paketin 60 dakikalık koşusunda BOT6 **123 pozisyon / 53x** ile çalıştı:
gerçek borsada %1.9'luk ters hareket kasanın tamamını silerdi. Aynı koşuda en kötü tek
işlem −20 $ (stop −10 olmalıydı) ve tasfiye hiç modellenmiyordu.

## 4. Beklenen değer ve başabaş WR

```
E[işlem] = WR × ort.kazanç − (1−WR) × ort.kayıp − komisyon
başabaş WR = 1 / (1 + ort.kazanç/ort.kayıp)
```

Örnek (maildeki BOT6, 17 işlem): ort. kazanç +7.44, ort. kayıp −13.33 →
K/K 0.56 → **başabaş WR %64**. Gerçek WR %88 olduğu için o örneklemde kârlı; ama 17 işlem
istatistiksel olarak yetersizdir.

## 5. Ardışık kayıp dayanıklılığı

Her işlem kasanın %1'ini riske atıyorsa (10/1000):

| Ardışık kayıp | Kasa | Not |
|---|---|---|
| 10 | 905 $ | normal |
| 30 | 740 $ | ciddi |
| 70 | 500 $ | yarı yarıya |
| 138 | 250 $ | geri dönüş için +300% gerekir |

%88 WR'de 20 ardışık kaybın görülme olasılığı düşüktür ama **sıfır değildir**; yüksek
kaldıraçta küçük olasılıklar hesabı kapatır.

## 6. Gerçek dünyada stop ≠ garanti

- Stop **market** emridir: gap'te tetik fiyatından kötü dolabilir.
- Likit olmayan sembolde kayma %0.5–2 olabilir → −10 $ planlanan işlem −15 $ kapatabilir.
- Bu yüzden v8'de: likidite filtresi (24s hacim ≥ 1 M$), kayma tamponu (5 bps),
  `en kötü tek işlem` raporda zorunlu metrik.

## 7. Kuralın özü

Kural (1000/50/10x/−10) **pozisyon başına riski** sabitler: her işlem kasanın %1'i.
Kasanın ne kadar hızlı eriyeceğini belirleyen şey kaldıraç değil, **eşzamanlı pozisyon sayısı**
ve **işlem sıklığı**dır. Bu yüzden 20 pozisyon sınırı bir "kural ihlali" değil, kuralın
kendi matematiğidir.
