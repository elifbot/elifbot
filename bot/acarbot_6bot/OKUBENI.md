# ACARBOT · 6 BOT TEK AKIŞ — kod paketi

Tarih: 2026-11-13 · Paket: `ACARBOT_6BOT.zip`

Altı bot **tek süreçte, tek WebSocket akışında** aynı anda çalışır. Amaç: hangi kural setinin
gerçek piyasada para kazandığını **aynı veri, aynı saniye** ile ölçmek. Botlar birbirinin
kararını etkilemez (her biri bağımsız kasa, bağımsız poz).

## Botlar

| # | Ad | Kural seti | Evren |
|---|----|-----------|-------|
| 1 | TURBO v1 | orijinal v1 motoru — **kodu değiştirilmedi** | ilk 30 sembol |
| 2 | OMEGA v1 | orijinal v1 motoru — **kodu değiştirilmedi** | ilk 30 sembol |
| 3 | ÜÇ-R (v5.1) | ÜÇ + LONG hacim eşiği 3,5x + zombi 20 dk | ilk 30 sembol |
| 4 | DÖRT (v6) | zayıf-long analizinden süzülen kazanan indikatör listesi | ilk 30 sembol |
| 5 | BEŞ (v7) | DÖRT-R + **kovalama yasağı** (son 30 sn'de %1,2'den fazla hareket → giriş yok) | ilk 30 sembol |
| 6 | ALTI | **TURBO v1 kodu birebir**, tek fark: 30 sembol sınırı yok | **510 sembol (tüm piyasa)** |

Evren tek: 510 OKX USDT-SWAP sembolü abone edilir. Besleme **motor bazlı filtreli** —
BOT 1-5 yalnızca ilk 30 sembolün tick'ini görür (eski koşularla birebir aynı kimlik),
BOT 6 hepsini görür. Yani "30 sembol mü, tüm piyasa mı" sorusu aynı veriyle ölçülür.

## Boyutlandırma (tüm botlarda aynı)

- Her pozisyon: **50 $ teminat × 10x = 500 $ notional**
- Zarar kes: pozisyon başına **−10 $ net** (hard stop)
- **İşlem/pozisyon limiti yok** (portföy stopu yok, pozisyon sayısı sınırı yok)
- Kasa muhasebesi 1.000 $ üzerinden yürür; kasa = 1.000 + realize + açık PnL

## Çalıştırma

```bash
pip install websockets aiohttp          # gereken tek dış bağımlılık
python3 canli_6bot.py --dakika 60 --sembol 999 --etiket 6bot --json logs/rapor_6bot.json
python3 panel_server.py --port 8000 --etiket 6bot      # ayrı terminalde: canlı panel
python3 metrikler.py logs/islem_jurnali_6bot.csv        # işlem sonrası metrikler
```

Süreyi **koşarken** uzatmak (restart gerekmez):

```bash
echo "30" > logs/uzat_6bot.txt     # +30 dakika; koşucu 2 saniye içinde uygular
```

`--sembol 30` verilirse BOT 6 da 30 sembole düşer; tüm piyasa için `999`.

## Testler

```bash
python3 test_v7_bes.py       # BEŞ (v7) kural testleri: 9/9
python3 test_v6_dort.py      # DÖRT (v6): 11/11
python3 test_v61_dort_r.py   # DÖRT-R (v6.1): 9/9
```

## Dürüst durum (13.11.2026, 18:30)

- **Kod paketi çalışır durumda**: koşu 18:27'de başladı, 60 dakika hedefli, kopma 0.
- **Sonuç henüz yok**: 25 dakikalık ilk koşuda ALTI öndeydi, ama bu **tam bir ölçüm değildir**
  ve saatlik koşu bitmeden hiçbir bot "kazanan" ilan edilmemelidir.
- İlk 25 dakikanın dökümü `loglar/` içinde (`islem_jurnali_6bot_ILK25DK.csv`,
  `durum_6bot_ILK25DK.json`) — ham veri, yorum katılmadı.
- Bilinen zaaf: BEŞ'in kovalama filtresi hızlı ama meşru hareketleri de eler; v6 ailesi
  30 sembolde nadiren sinyal üretir (25 dakikada 0 işlem). Bu iki davranış ölçülmeden
  "iyileşme" sayılmaz.
- WR tek başına anlamlı değildir; **başabaş WR / PF / maks düşüş** ile birlikte okunmalıdır
  (`metrikler.py` bunları basar).

## Dosya yapısı

```
canli_6bot.py       6 botu tek akışta çalıştıran koşucu (asıl dosya)
panel_server.py     canlı panel (HTML, 2 sn yenileme)
metrikler.py        WR / başabaş WR / PF / maks düşüş
jurnal.py           işlem jurnalı (CSV)
turbo_engine.py     TURBO v1 motoru        } v1 — orijinal, değiştirilmedi
cekirdek.py         OMEGA v1 çekirdeği     }
ai_models.py, apex_bot.py, golge_uc.py, hybrid_bot.py, test_4bot.py   yardımcı modüller (import zinciri)
motorlar/acarbot_omega/      OMEGA v1 paketi
motorlar/v2, v3, v4          eski sürüm modülleri (import zinciri için)
motorlar/v5/birlesik.py      ÜÇ (v5)
motorlar/v51/birlesik_v51.py ÜÇ-R (v5.1)
motorlar/v6/dort.py          DÖRT (v6)
motorlar/v7/bes.py           BEŞ (v7)
test_v7_bes.py / test_v6_dort.py / test_v61_dort_r.py   kural testleri
loglar/              ilk 25 dakikanın ham dökümü
```

> Not: Bu bir **test** sistemidir, canlı para ile çalıştırılmamalıdır. Emirler simüle edilir;
> gerçek emir gönderilmez. Piyasa verisi OKX SWAP kamuya açık WebSocket'inden alınır.
