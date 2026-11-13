# 02 · Maildeki 25 dakikalık gerçek koşunun analizi

Kaynak: `bot/acarbot_6bot/loglar/islem_jurnali_6bot_ILK25DK.csv` — **26 kapanan işlem**,
18:05–18:26 arası, gerçek OKX verisi. Az ama gerçek.

## Bot bazında

| Bot | İşlem | Net $ | WR | Çıkış nedenleri |
|---|---|---|---|---|
| BOT1 TURBO | 3 | **+31.19** | 2/3 | AI_TRAILING ×2, BE_KAR_KORUMA ×1 |
| BOT2 OMEGA | 3 | **+40.08** | 2/3 | AI_PARABOLIK ×2, BE_KAR_KORUMA ×1 |
| BOT6 ALTI | 17 | **+106.16** | 15/17 | TRAILING ×9, BE ×6, ZARAR_KES_-20$ ×1, TÜKENİŞ ×1 |
| BOT5 BEŞ | 3 | **−6.72** | 0/3 | HUSRAN_CIKIS ×3 |

BOT3/BOT4 25 dakikada **hiç kapanan işlem** üretmedi (3'er pozisyon açık).

## Bulgu 1 — "kâr koruma" zarara dönüşüyor (7 işlem)

Örnek (AKE, 18:05:40):

```
giriş 0.011500 → çıkış 0.011471   net −1.76 $   ama tepe kâr +6.46 $
çıkış nedeni: BE_KAR_KORUMA
```

Sebep: kâr tabanı her tick'te Python'da kontrol ediliyor. Likit olmayan sembolde tek print
boşluk bırakınca kontrol, tabanın çok altında tetikleniyor. **Borsada duran emir olsaydı**
fiyat ilk taban seviyesinden geçerken kapanırdı.

Aynı satır BOT1, BOT2 ve BOT6'da birebir tekrar ediyor (aynı sembol, aynı saniye) — üç motor
aynı veriyi görünce aynı hatayı yapıyor.

## Bulgu 2 — stop −20 $, kural −10 $

`INIT-USDT-SWAP` 18:20:59: net **−20.00 $**, çıkış `ZARAR_KES_-20$`.
Kodda `hard_stop_loss_usd = 20.0` (turbo_engine, cekirdek, omega config). OKUBENI ise
"−10 $ net" yazıyor. **Belge ile kod çelişiyordu**; kod düzeltildi.

## Bulgu 3 — hayalî teminat, 53x hesap kaldıracı

`durum_6bot_ILK25DK.json` (18:27): BOT6 kasa **1.053,79 $**, teminat **1.250 $**,
25 açık pozisyon. Yani kasa 1.054 $ iken 1.250 $ teminat kullanılmış — **mümkün değil**.
Tam koşuda bu 6.150 $ teminata (123 pozisyon) çıktı.

Sebep: `enforce_free_equity_check = False`.

## Bulgu 4 — OMEGA çıkış üretmiyor

BOT2'nin 3 işlemi de ilk 25 dakikada; sonrasında 19 pozisyon açık kalıp hiçbiri kapanmıyor.
60 dakikalık koşuda da **0 kapanan işlem** üretti. Çıkış motoru pratikte çalışmıyor.

## Bulgu 5 — örneklem yetersiz

26 işlemle "en iyi bot" ilan edilemez. Mailin kendisi de bunu söylüyor ("tam bir ölçüm
değildir"). WR %88 görünen BOT6'nın açık PnL'i −52 $ idi; realize kâr açık zararla
dengeleniyordu. **WR tek başına okunamaz**; başabaş WR ve PF ile birlikte bakılmalı.

## Ne yapıldı

1. Üç motorda stop −20 → −10, teminat kontrolü açıldı (`yamalar/01-...patch`).
2. Replay koşucusu 60 dakikalık piyasa zamanına genişletildi (sentetik + gerçek CSV).
3. v8 motoru yazıldı: stop borsada duruyor, teminat fiziği uygulanıyor.
