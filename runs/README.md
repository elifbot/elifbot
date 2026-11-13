# Koşu artefaktları

Her koşu kendi klasöründe:

| Dosya | Ne |
|---|---|
| `durum.json` | Panelin okuduğu canlı durum (botlar, tick, süre) |
| `rapor.json` | Tam rapor: sonuçlar, kasa eğrisi, maksDD, besleme tipi, seed |
| `islem_jurnali_<etiket>.csv` | Kapanan her işlem (zaman, bot, sembol, net, çıkış nedeni) |
| `metrikler.txt` | WR, başabaş WR, PF, maksDD, en kötü işlem |
| `ozet.md` | İnsan okunur tablo |

> `rapor.json.besleme` alanı **zorunlu** okuma: `SENTETIK` ise sonuç kenar ölçümü değildir.
