# v12 — 10 Saniyelik Açılış Freninin Kaldırılması

Tarih: 28 Ekim 2026  
Mod: paper / araştırma; canlı emir gönderimi yoktur.

## Kullanıcı kararı ve kapsam

Kullanıcı, açılmayan 12 sinyal incelendikten sonra **yalnızca 10 saniyede en fazla 3 yeni pozisyon (korelasyon freni) sınırının kaldırılmasını** seçti.

v12'de:

- `OLAY_AZAMI_ACILIS = 0`
- `Bot.acilis_freni = 0` varsayılanı
- 10 saniye / 3 açılış kontrolü yalnızca `acilis_freni > 0` ise uygulanır.

Böylece aynı 10 saniyelik pencerede 3'ten fazla farklı sembolde pozisyon açılabilir.

## Korunan kontroller

Bu değişiklik bütün sınırların kaldırılması değildir. Aşağıdakiler korunmuştur:

- Aynı base varlığın OKX/Binance üzerinde ikinci kez açılmasını engelleyen `engel:cift_borsa` kontrolü,
- Aynı sembolde açık veya bekleyen pozisyon kontrolleri,
- Toplam ve aynı-yön pozisyon limitleri,
- Marj yeterliliği, bakiye tabanı ve marj kullanım kontrolleri,
- Yön, cascade, piyasa genişliği ve diğer sinyal filtreleri,
- v11'in izole çıkış ve CSV mutabakat düzeltmeleri.

Dolayısıyla “bütün sinyaller değerlendirilir” doğrudur; “her sinyal kesin pozisyon açar” denemez. Önceki 12 sinyalin 4 korelasyon reddi bu engel olmadan değerlendirilecek, 8 aynı-varlık reddi ise korunacaktır.

## CLI

Varsayılan, fren kapalı:

```bash
python3 ws_bot.py --sure-dk 15
# veya açıkça
python3 ws_bot.py --sure-dk 15 --acilis-freni 0
```

Eski 10 saniye / 3 açılış davranışını yeniden etkinleştirmek için:

```bash
python3 ws_bot.py --sure-dk 15 --acilis-freni 3
```

`ws_durum.json` içindeki `acilis_freni_10sn` alanı etkin değeri gösterir.

## Testler

**195 test geçti.**

Yeni regresyon testleri:

- Varsayılan `acilis_freni=0` iken aynı kısa pencerede 4 farklı sembolün 4'ü de açılır.
- `acilis_freni=3` verilirse dördüncü açılış yeniden `engel:korelasyon_freni` olur.
- Fren kapalıyken aynı varlığın diğer borsada açılması hâlâ engellenir.
- Negatif fren değeri `ValueError` ile reddedilir.
- CLI yardımında `--acilis-freni` ve `0 = kapalı` açıklaması doğrulanır.

## Risk ve örneklem notu

Aynı makro hareket sırasında artık daha fazla korelasyonlu pozisyon üst üste açılabilir; toplam risk ve eşzamanlı zarar olasılığı yükselir. Bu değişiklik performansın iyileştiğini kanıtlamaz.

Bu yeni davranış, önceki v11 ve daha eski işlem örnekleriyle aynı yapılandırma değildir. 300+ işlem hedefi için v12 ayarlarıyla yeni ve ayrı bir örneklem tutulmalıdır. Bu paket yalnızca birim/regresyon doğrulaması içerir; yeni 15 dakikalık veya 300+ işlemlik performans testi tamamlanmış sayılmaz.
