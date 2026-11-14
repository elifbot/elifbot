# Canlı test — OKX gerçek verisi (14 Kasım 2026)

**Koşu:** GitHub Actions, 25 sembol (USDT-M vadeli, 24s USD hacme göre en likit), 1 dk bar,
840 bar (14 saat), ısınma 600 bar. Veri: `www.okx.com/api/v5/market/candles` (public, anahtarsız).

**Binance neden yok:** `fapi.binance.com` → **HTTP 451** — *"Service unavailable from a restricted
location"*. GitHub koşucuları kısıtlı bölgede. OKX **200** döndü, test OKX ile yapıldı.

## 1. Üç bot, gerçek veri
| Sürüm | İşlem | WR | PF | Net | Çıkış dağılımı |
|---|---:|---:|---:|---:|---|
| v1 kbot (EMA9/21+hacim) | 70 | %34,3 | **0,55** | **−144,38 $** | stop 27 · süre 43 |
| v2 kbot2 (rejim+komite) | 98 | %28,6 | **0,47** | **−230,72 $** | stop 39 · süre 59 |
| v3 kbot3 (kanıt eşikleri) | 190 | %32,6 | **0,48** | **−548,88 $** | stop 100 · izli kâr 52 · süre 38 |

**Üçü de kaybediyor.** Sentetik verideki PF 10–15 tamamen yanıltıcıydı.

## 2. Eşiklerin gerçek öngörü gücü (en değerli ölçüm)
Her bar için yön (EMA9 vs EMA21) ve 30 bar sonraki yönlü getiri, %0,2 gidiş-dönüş maliyet düşülerek:

| ADX kovası | n | ortalama getiri | isabet |
|---|---:|---:|---:|
| <20 | 5.606 | −0,224% | %30 |
| 20–25 | 1.345 | −0,292% | %27 |
| 25–30 | 1.273 | −0,346% | %28 |
| 30–35 | 1.303 | −0,334% | %27 |
| 35+ | 9.223 | −0,329% | %26 |

| BB genişliği | n | ortalama | isabet |
|---|---:|---:|---:|
| <0,3 | 4.070 | −0,206% | %13 |
| 0,3–0,5 | 3.689 | −0,220% | %27 |
| 0,5–1 | 6.317 | −0,220% | %29 |
| 1–2 | 2.491 | −0,267% | %35 |
| 2+ | 2.183 | −0,849% | %40 |

| \|RSI−50\| | n | ortalama | isabet |
|---|---:|---:|---:|
| <6 | 4.594 | −0,264% | %29 |
| 6–12 | 4.260 | −0,268% | %28 |
| 12–18 | 3.588 | −0,315% | %26 |
| 18+ | 6.308 | −0,329% | %26 |

**Okuma:** Hiçbir kova pozitif değil ve kovalar arasında anlamlı fark yok. En iyi kova (−0,206%)
tam olarak "maliyet kadar kayıp" demek → **EMA yönü bu veride sıfır öngörü**.
Ham yönlü kenar ≈ −0,13%/30 dk; ters çevirmek de maliyeti karşılamıyor (−0,07%).

## 3. Neden sentetik yanılttı
Sentetik veri rejim değişimli rastgele yürüyüş: trendler yapay olarak pürüzsüz ve uzun.
1 dk gerçek kriptoda 30 barlık ufuk gürültü + %0,2 maliyet. Trend takibi burada çalışmıyor.

## 4. Buradan çıkan üç zorunlu değişiklik
1. **Ufuk:** 1 dk yerine 15 dk / 1 saat bar, 30–60 bar ufuk (kenarın maliyete oranı 5–10 kat artar).
2. **Maliyet:** taker %0,05 yerine maker %0,02 → gidiş-dönüş 0,2% → 0,08%.
3. **Sinyal kaynağı:** fiyat türevi göstergeler değil, repodaki **funding / OI / likidasyon** akışı.
   Gerçek raporda para kazandıran tek şey buydu (coin dışı %65 katkı, hacim patlaması).

## 5. Tekrar üretme
```bash
gh workflow run canli_test.yml --ref main -f borsa="okx" -f sembol="25" -f dakika="240" -f ileri="30"
```
Sonuç: `canli/<zaman>` dalında `runs/canli_*/ozet.json` + `runs/tani.txt`.
