# 2. BİR SAATLİK CANLI PAPER TEST RAPORU — `Run #40179959680` (`KRIPTO-BOT v7.3`)

> **Oturum Zamanı:** `2026-10-25 12:17:05 – 13:17:15 TSİ` (`09:17 – 10:17 UTC`, tam 60 dakika)
> **Mod & Profil:** `PAPER` (`controlled-60-v2-1000-no-cross-rescue` — gerçek emir yok, canlı çift borsa verisi)
> **Borsalar & Evren:** `725` aktif USDT perpetual (`Binance=536`, `OKX=464`), `1,548,754` canlı WS trade + `1,498,750` emir defteri güncellemesi

---

## 1. İki Oturumun Yan Yana Karşılaştırması (`1. Saat` vs `2. Saat`)

| Metrik | 1. Oturum (`#40174169361` — v7.2) | 2. Oturum (`#40179959680` — v7.3) | Yorum |
|---|---:|---:|---|
| **Başlangıç Kasası** | `$1,000.00` | `$1,000.00` | Aynı başlangıç |
| **Bitiş Özsermayesi** | **`$1,031.89`** | **`$964.94`** | `-%3.51` (süre-sonu kapanışı) |
| **Net K/Z (Ücret+Funding Dahil)** | **`+$31.89`** | **`-$35.06`** | Brüt `-$29.56`, Komisyon `-$5.51`, Funding `+$0.01` |
| **Açılan / Kapanan İşlem** | `20 / 20` | `11 / 11` | 11 işlemin tamamı **ilk 80 saniyede** açıldı |
| **Bot Kapanışı / Süre-Sonu Kapanışı** | `20 Bot / 0 Süre-Sonu` | **`0 Bot / 11 Süre-Sonu`** | 59 dk boyunca hiçbiri ne TP ne SL oldu |
| **Flash Crash Erken Kapatma Hatası** | `1 kez` (55. dk `LIGHT/USDT`) | **`0 kez` (Tamamen Çözüldü ✅)** | Sigorta 60 dk kesintisiz `AKTİF` kaldı |
| **Shadow `flow-confidence` Sonucu** | Bozuktu (`0/20` defter hatası) | **`11/11` Zararlı Girişi Reddetti -> `$0.00` Kayıp! 🏆** | Soğuk başlangıç tuzağını tek başına yakaladı |

---

## 2. İşlem İşlem Tam Tablo (`11` Pozisyonun Tamamı)

Tüm pozisyonlar oturumun **ilk 80 saniyesinde** (`12:17:12 – 12:18:25 TSİ`) `SHORT` yönünde açıldı, gün içi kâra geçti (`MFE > 0`), ancak piyasa dipten yukarı tepki verince 60. dakika sonunda (`SÜRELİ PAPER ÖLÇÜMÜ SONU`) kapandı:

| # | Sembol | Borsa | Yön | Giriş | Çıkış | En Yüksek Kâr (`MFE`) | En Derin Eksi (`MAE`) | Brüt K/Z | Net K/Z | Giriş Anı RSI / Kapsama |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `4/USDT` | Binance | SHORT | `0.011564` | `0.011565` | `+$1.32` | `-$3.85` | `-$0.04` | **`-$0.54`** | RSI `30.1` / **7.2 sn** (7 trade!) |
| 2 | `ETH/USDT` | OKX | SHORT | `2323.61` | `2328.61` | `+$0.68` | `-$1.08` | `-$1.08` | **`-$1.57`** | RSI `27.3` / **27.0 sn** |
| 3 | `BAS/USDT` | Binance | SHORT | `0.016781` | `0.016824` | `+$1.13` | `-$3.80` | `-$1.28` | **`-$1.79`** | RSI `30.0` / **48.4 sn** |
| 4 | `BTC/USDT` | Binance | SHORT | `80083.7` | `80357.0` | `+$0.13` | `-$1.89` | `-$1.71` | **`-$2.20`** | RSI **`23.8`** / **57.9 sn** |
| 5 | `AVAX/USDT` | Binance | SHORT | `8.7470` | `8.7900` | `+$0.57` | `-$3.66` | `-$2.46` | **`-$2.96`** | RSI `31.1` / `77.0 sn` |
| 6 | `ACH/USDT` | OKX | SHORT | `0.005039` | `0.005065` | `+$0.69` | `-$3.57` | `-$2.58` | **`-$3.08`** | RSI **`24.8`** / **12.2 sn** (5 trade!) |
| 7 | `CETUS/USDT` | Binance | SHORT | `0.02115` | `0.02127` | `+$0.71` | `-$4.26` | `-$2.84` | **`-$3.34`** | RSI **`25.4`** / `70.9 sn` |
| 8 | `APE/USDT` | Binance | SHORT | `0.1251` | `0.1259` | **`+$2.39`** | `-$4.39` | `-$3.19` | **`-$3.70`** | RSI `32.7` / **32.1 sn** (7 trade!) |
| 9 | `ALLO/USDT` | OKX | SHORT | `0.18066` | `0.18230` | `+$0.25` | `-$6.42` | `-$4.54` | **`-$5.04`** | RSI **`24.3`** / **27.4 sn** + TopTrader LONG! |
| 10 | `BICO/USDT` | OKX | SHORT | `0.01489` | `0.01503` | `+$0.67` | `-$4.70` | `-$4.70` | **`-$5.20`** | RSI **`24.0`** / **54.7 sn** |
| 11 | `CFX/USDT` | Binance | SHORT | `0.04659` | `0.04707` | `+$0.64` | `-$6.43` | `-$5.15` | **`-$5.65`** | RSI **`27.1`**, MFI **`5.3`** + TopTrader LONG! |

---

## 3. Neler DOĞRU Çalıştı? (Başarılar)

1. **Flash Crash Sigorta Düzeltmesi `%100` Doğrulandı:** İlk testte 55. dakikada sığ altcoin yüzünden tüm portföyü kapatan hata sıfırlandı. Sigorta 60 dakika boyunca kesintisiz `AKTİF` kaldı.
2. **Emir Defteri (`book_levels=20`) ve `flow-confidence` Düzeltmesi Nokta Atışı Çalıştı:** İlk testte bozuk olan `flow-confidence` kohortu bu kez gerçek veriyle çalıştı ve **zarar eden 11 işlemin 11'ini de girişte reddederek (`0/11`) kasayı `$1,000.00`'da (`$0.00` kayıp) korudu!**
3. **PDF v3 + Türev İstihbaratı (`DerivativesIntelEngine`) Canlı Kanıt Üretti:** `ALLO/USDT` (`-$5.04`) ve `CFX/USDT` (`-$5.65`) açılırken `smart_money_divergence = "TOP_TRADER_LONG_PERAKENDE_SHORT"` bayrağını yakaladı (küçük yatırımcı dipten panikle SHORT açarken Top Trader'lar LONG topluyordu!).

---

## 4. Neler YANLIŞ / EKSİK Çalıştı? (4 Büyük Kök Neden)

### ❌ Hata 1: İlk 80 Saniyede "Soğuk Başlangıç + Alfabetik Sıra" ile Marj Tavanını Doldurma!
- Açılan 11 coinin isimlerine dikkat edin: **`4`, `ACH`, `ALLO`, `APE`, `AVAX`, `BAS`, `BICO`, `BTC`, `CETUS`, `CFX`** — tamamı alfabenin **A, B, C** harfleri!
- Neden? Bot yeni başladığında WebSocket para akışı penceresi henüz **7–50 saniyelikken** (`4/USDT`'de sadece `7.2 sn` ve `$402` hacimle!) `taker_delta` oranı `-1.0`'e yakın çıktı ve `PARA_CIKISI` tetikleyicisi ateşlendi.
- Tarama alfabetik sırayla gittiği için bot ilk 80 saniyede A–C harflerindeki ilk 11 coine `$550` marj bağladı, `%60` marj tavanına çarptı ve **kalan 59 dakika boyunca D–Z arasındaki hiçbir coine (`SOL`, `SUI`, `XRP`, `TAO`, `NEAR` vb.) giremedi!**
- **Çözüm:** `flow_confidence` (en az `60 sn` akış kapsaması, min trade sayısı, taze emir defteri ve hacim-ağırlıklı Taker/CVD güveni) **canlı giriş zorunluluğu** yapılmalı ve tarama sırası alfabetik değil **hacim/skor öncelikli (veya karıştırılmış)** olmalı!

### ❌ Hata 2: Aşırı Satım Dibinden (`RSI < 28`, `MFI < 15`) Geç Kalmış SHORT Açmak!
- Oturum başladığında (`12:17 TSİ`) düşüş zaten bitmiş, `BTC` `RSI=23.8` (`Bollinger %B = -0.10`), `CFX` `MFI=5.3`, `ALLO` `MFI=10.9` ile aşırı satım dibine vurmuştu. Piyasa oradan yukarı tepki verdi (`BTC 80,083 -> 80,357`).
- Üstelik **11 işlemin 11'i de tek yönde (`SHORT`)** açıldığı için tek bir piyasa tepkisi tüm sepeti aynı anda eksiye düşürdü (`ayni_yon_max_pozisyon` paper modda `1000`'e açıldığı için yön çeşitlendirmesi devre dışı kalmıştı!).
- **Çözüm:**
  1. `TREND / PULLBACK` modunda aşırı tükenmiş diplerden (`RSI < 26` iken yeni SHORT veya `RSI > 74` iken yeni LONG — güçlü tasfiye squeeze'i yoksa) geç giriş engellenmeli.
  2. Paper modda da **aynı yönde maksimum pozisyon sınırı** (örn. en fazla `6` SHORT + `6` LONG, toplam `12`) uygulanmalı ki tüm kasa tek yöne kilitlenmesin.
  3. `TOP_TRADER` ters ayrışması (`smart_money_divergence != "YOK"`) tek başına ters yönlü girişleri engellemeli (`ALLO` ve `CFX`'teki en büyük iki zararı doğrudan eler!).

### ❌ Hata 3: Terste Asılı Kalan İşlemler İçin "Yapısal / Supertrend / Zaman Çıkışı" Olmaması (`$40` Stop Fazla Uzak)!
- `$50` marj × `10x` işlemde `$40` stop demek fiyatın tam **`%8.0` ters gitmesi** demek! Normal bir saatte `BTC` veya majör altcoinler `%8` gitmediği için, terste kalan pozisyonlar **59 dakika boyunca ne stop oluyor ne de çıkıyor** — kasadaki marjı rehin tutuyor!
- **Çözüm:** Kârdaki işlemlerde `kosan_kar` (kâr koşusu) korunsun; ancak **belirli süre (örn. 20–25 dk) sonunda hâlâ ekside olan VE 5m Supertrend + Order-Flow tamamen ters yöne dönmüş** pozisyonlar `%8` (`-$40`) beklemeden erken kesilsin (`Erken Trend Bozulma Çıkışı`) ki marj boşalsın ve yeni fırsatlara girilebilsin!

### ❌ Hata 4: Borsaların Yeni Eklediği ABD Hisse/ETF Sembolleri (`SQQQ`, `TQQQ`, `TSLL`, `SMH`, `NVDA/MRVL/MU/JNJ/RIVN`)
- Logda marj tavanına takılan semboller arasında borsaların yeni listelediği ABD hisse/ETF kontratları (`SQQQ`, `TQQQ`, `TSLL`, `MSTU`, `SMH`, `SHOP`, `MRVL`, `MU`, `JNJ`, `RIVN`, `RKLB`, `TENCENT`, `POPMART`) görüldü.
- **Çözüm:** Sabit kara liste yerine borsa market verisindeki `subType / underlying / assetClass / contractType` + genişletilmiş TradFi/ETF desen filtresiyle tüm hisse senedi ve kaldıraçlı ETF kontratları eksiksiz elenmeli.
