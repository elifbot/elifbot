# 07 · 60 dakikalık 6-bot koşusu — detaylı rapor

**Tarih:** 13.11.2026 · **Etiket:** `2026-11-13_6bot_60dk` · **Seed:** 20261113
**Çıktılar:** `runs/2026-11-13_6bot_60dk/` (rapor.json, jurnal.csv, metrikler.txt, ozet.md)
**Panel:** `panel/server.py` (6 dikey kart, 3 sn yenileme)

---

## 0. Tek paragraf özet

Altı bot, 510 sembollük evrende 60 dakikalık piyasa zamanında koştu: 1.480.892 tick satırı,
**211 kapanan işlem**. Yama öncesi koşuda **−20.00 $** olan en kötü tek işlem, stop −10 $'a
çekildikten sonra **−10.44 $**'a indi; BOT6'nın 123 açık pozisyon / 6.150 $ teminat /
**53x hesap kaldıracı** tablosu **21 pozisyon / 1.050 $ / 9.5x**'e oturdu. BOT6 +55.26 $,
BOT4 +35.73 $, BOT3 +23.02 $, BOT5 +15.48 $ realize etti; BOT1 −28.87 $, BOT2 ise **hiç
işlem kapatmadı**. **Bu koşu sentetik besleme ile yapıldı** — kenar (edge) ölçümü değil,
kural uyumu ve motor davranışı ölçümüdür.

---

## 1. Ne koştu, ne koşmadı

| | |
|---|---|
| Besleme | **SENTETİK** (deterministik üreteç) |
| Neden | Bu ortamda Binance/OKX/Bybit/Kraken ve `data.binance.vision` **tamamen kapalı** (HTTP 000). Yalnızca GitHub/pypi/npm açık. |
| Piyasa zamanı | 60 dk · bucket 0.5 sn · 7.200 adım |
| Evren | 510 sembol (gerçek OKX sembol adları), ilk 30 → BOT1-5, hepsi → BOT6 |
| Duvar süresi | 276 sn (hızlandırılmış replay) |
| Kural | 1.000 $ kasa · 50 $ teminat · 10x · CROSS · pozisyon limiti yok · −10 $ stop |

> Gerçek veriyle koşmak için: `replay_6bot.py --besleme csv --ticks <arsiv.csv>`.
> Kod hazır; eksik olan tek şey arşiv.

---

## 2. Kural uyumu — yama öncesi / sonrası

| Kontrol | Yama öncesi | Yama sonrası | Durum |
|---|---|---|---|
| Stop (kural −10 $) | **−20.00 $** | **−10.44 $** (en kötü 5: −10.44 … −10.23) | ✅ |
| En kötü 5 işlem | −20, −20, −20, −20, −18.4 | −10.44, −10.44, −10.35, −10.23, −10.23 | ✅ |
| BOT6 açık pozisyon | 123 | 21 | ✅ |
| BOT6 kullanılan teminat | 6.150 $ (kasa 1.160 $) | 1.050 $ (kasa 1.105 $) | ✅ |
| BOT6 hesap kaldıracı | **53.0x** | **9.5x** | ✅ |
| Pozisyon başına notional | 500 $ | 500 $ | değişmedi |
| Marjin modu | CROSS | CROSS | değişmedi |
| Pozisyon limiti | yok | yok | değişmedi |
| "Kâr koruma" zararla kapanan işlem | 7 | **0** | ✅ |

Yama: `yamalar/01-stop10-ve-teminat-fizigi.patch` (153 satır diff, denetlenebilir).

---

## 3. Sonuçlar

| # | Bot | Kural seti | Kasa | Realize | Açık PnL | Açık | Kapanan | WR | Başabaş WR | PF | Teminat | Hesap kal. | MaksDD | En kötü |
|---|-----|-----------|------|---------|----------|------|---------|----|-----------|----|---------|-----------|--------|---------|
| 1 | TURBO v1 | v1 | 952.95 | −28.87 | −18.18 | 9 | 46 | 65% | 70% | 0.82 | 450 | 4.7x | −69.06 | −10.00 |
| 2 | OMEGA v1 | v1 | 990.51 | 0.00 | −9.49 | 19 | **0** | — | — | — | 950 | 9.6x | −9.49 | — |
| 3 | ÜÇ-R | v5.1 | 1023.02 | +23.02 | 0.00 | 0 | 22 | 82% | 74% | 1.59 | 0 | 0.0x | −36.60 | −10.23 |
| 4 | DÖRT | v6 | 1035.31 | +35.73 | −0.42 | 2 | 36 | 78% | 70% | 1.48 | 100 | 1.0x | −28.41 | −10.44 |
| 5 | BEŞ | v7 | 1015.22 | +15.48 | −0.26 | 1 | 37 | 57% | **52%** | 1.22 | 50 | 0.5x | −35.61 | −10.44 |
| 6 | ALTI | v1 (tüm piyasa) | 1105.12 | +55.26 | +49.86 | 21 | 70 | 70% | 65% | 1.26 | 1.050 | 9.5x | −41.84 | −10.00 |

**Okuma notları**

- **BOT6** en yüksek realize (+55.26 $) ama **açık PnL +49.86 $** ile kasanın %10'u
  hâlâ piyasada. 21 pozisyon × 500 $ = 10.500 $ notional → hesap kaldıracı 9.5x.
- **BOT1** gerçekten zarar etti (−28.87 $). 46 işlemde WR %65, başabaş WR %70 → **kenar
  negatif**. PF 0.82. Bu, "TURBO v1 kârlı" varsayımını çürütür (en azından bu senaryoda).
- **BEŞ (v7)** en iyi risk profilini üretti: ort. kayıp **−4.35 $** (diğerleri −9.3…−10.0),
  başabaş WR **%52** — yani düşük WR'ye rağmen en kolay kâra geçen bot. Kovalama yasağı
  kayıpları erken kesiyor.
- **OMEGA** 0 işlem kapattı: 19 pozisyon açık, −9.49 $ açık PnL. Çıkış motoru pratikte
  çalışmıyor; bu bir kod hatası, ölçüm değil.

---

## 4. Çıkış nedeni dağılımı (211 işlem)

| Neden | Adet |
|---|---|
| BE_KAR_KORUMA | 61 |
| ZARAR_KES_−10$ | 49 |
| AI_TRAILING_KAR_AL | 35 |
| TRAILING_KAR_AL | 27 |
| HUSRAN_CIKIS | 13 |
| AI_ANLIK_TUKENIS_KAR_AL | 11 |
| TUKENIS_KAR_AL | 9 |
| ZOMBI_CIKIS | 6 |

- Kâr koruma çıkışlarının **tamamı kârlı** (yama öncesi 7 tanesi zarardı).
- 49 stop çıkışının tamamı −10.00 ile −10.44 arasında.
- En iyi 5 işlem: +18.44, +18.26, +15.61, +11.78, +10.73 → kazanç kuyruğu stop'un 1.5–1.8 katı.

---

## 5. v8 motoru (yeni)

Aynı kurala sabitlenmiş v8, 15 dakika / 120 sembol simülasyonunda:

| Metrik | v8 | Eski motorlar |
|---|---|---|
| En kötü tek işlem | **−10.95 $** | −10.44 $ (yamalı) / −20.00 $ (orijinal) |
| Teminat reddi | 90 giriş engellendi | yok (hayalî teminat) |
| Eşzamanlı pozisyon | 19 (kapasite sınırı) | 123 |
| Hesap kaldıracı | 9.46x | 53x |
| Tasfiye | 0 | modellenmiyor |
| Stop | **borsada duran reduceOnly emir** | Python tick kontrolü |

v8'in farkı: stop borsada durduğu için gap'te zarara dönüşemez; teminat yetmezse emir
hiç gitmez; her an tasfiye mesafesi raporlanır.

---

## 6. Bulgular (kanıt sırasıyla)

1. **Kod, belgeyi tutmuyordu.** OKUBENI "−10 $ net" diyor, üç motorda `hard_stop_loss_usd = 20.0`
   yazıyordu. 60 dakikalık koşuda 49 stop çıkışı −20 $'lık bütçeyle yapıldı; yama sonrası
   −10 $'a indi. → `yamalar/01-...patch`
2. **Teminat fiziği kapalıydı.** `enforce_free_equity_check = False` yüzünden 1.000 $ kasa
   6.150 $ teminat "kullanabiliyordu". Gerçek borsa bu emirlerin ~%85'ini reddeder. Açıldı.
3. **Kâr koruması borsada değildi.** 25 dakikalık gerçek dökümde 7 kez "BE kâr koruma"
   **zararla** kapandı (ör. tepe +6.46 $ → net −1.76 $). Yamalı koşuda bu sayı **0**.
   Kalıcı çözüm v8'de: stop emri.
4. **OMEGA çıkış üretmiyor.** 60 dakikada 0 kapanan işlem. Çıkış motoru ya hiç
   tetiklenmiyor ya kilitli. → `kadro/ROUTING.md` üzerinden İcra Mühendisi işi.
5. **TURBO v1 bu senaryoda kenar üretmedi.** WR %65 < başabaş WR %70, PF 0.82. Maildeki
   25 dakikalık koşuda +31 $ görünmesi örneklem gürültüsüydü (3 işlem).

---

## 7. Sınırlar (dürüst kısım)

- **Sentetik veri.** Bu sonuçlar "hangi bot para kazandırır" sorusunu **yanıtlamaz**.
  Yalnızca motor davranışını, kural uyumunu ve kaldıraç dinamiğini ölçer.
- **Sentetik sinyal yoğunluğu** gerçek piyasadan yüksek tutuldu ki 60 dakikada anlamlı
  örneklem oluşsun. İşlem sayıları gerçek frekansın üstünde.
- **Örneklem** 211 işlem; bot başına 0–70. "En iyi bot" ilan etmek için yetersiz.
- **Funding ve likidasyon cezası** simülasyonda basitleştirilmiş.
- **BOT2'nin 0 işlemi** ölçüm değil, hata.

---

## 8. Sıradaki tek adım

Gerçek tick arşivi (≥ 30 gün, ≥ 30 sembol) → tek komut:

```bash
python3 bot/tools/replay_6bot.py --besleme csv --ticks arsiv.csv \
        --dakika 43200 --etiket gercek_30g
```

Bu koşunun raporu `besleme: GERCEK PIYASA VERISI` + veri sha256 taşır ve **ilk kez**
"kenar var mı" sorusuna cevap verir.
