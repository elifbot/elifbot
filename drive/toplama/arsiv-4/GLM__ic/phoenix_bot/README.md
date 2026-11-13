# 🚀 Phoenix Bot v2 — Kripto Futures İşlem Botu

Binance USDT-M Perpetual (ve Bybit) için modüler, risk-öncelikli, çift yönlü (Long/Short)
futures işlem botu. **API anahtarı olmadan sinyal üretir ve paper test yapar** — anahtar
yalnızca canlı işlemler için gereklidir.

Eski AcarBot/KRIPTO-BOT v7.8 kod tabanının doğrulanmış mekanizmaları (TP1/TP2 R-planı,
ATR+swing stop planı, kaldıraç merdiveni, MFE kilit merdiveni, tükenme filtresi, devre
kesiciler) yeni, sade ve modüler bir mimariye taşınmıştır.

---

## 1. Hızlı Başlangıç

```bash
# 1) Kurulum
pip install -r requirements.txt

# 2) Sistem sağlık kontrolü — tümü [OK] olmalı
python selftest.py

# 3) Sinyal taraması — API ANAHTARI GEREKMEZ
python main.py scan --watch

# 4) Paper test — sanal para, gerçek veri, anahtar gerekmez
python main.py trade

# 5) Geçmiş veri testi
python backtest.py --symbol BTC/USDT:USDT --timeframe 15m --bars 1000
```

**Paralel paper test (sizin planınız: 15m + 30m + 1h birkaç gün):**
- Windows: `start_paper.bat` çift tık → 3 zaman dilimi + tarayıcı ayrı pencerelerde açılır
- Linux/Mac: `bash start_paper.sh`

Her oturum kendi `state_<tf>.json`, `trades_<tf>.csv`, `bot_<tf>.log` dosyasını tutar.

## 2. Modlar

| Mod | Komut | API anahtarı | Açıklama |
|---|---|---|---|
| **scan** | `python main.py scan [--watch]` | ❌ Gerekmez | Anlık sinyal tablosu; sinyaller `signals.csv`'ye yazılır, Telegram'a gider |
| **paper** | `python main.py trade` | ❌ Gerekmez | Gerçek veriyle sanal para; dolgular SL/TP simülasyonuyla işlenir |
| **testnet** | anahtar + `config: testnet: true` | Testnet anahtarı | `testnet.binancefuture.com` anahtarıyla borsa-native emirler |
| **canlı** | `python main.py trade --live --yes` | Gerçek anahtar | Gerçek para. **Önce paper 1+ hafta!** |

Güvenlik: `config.yaml`'da `mode: live` yazsa bile `--live --yes` bayrakları olmadan
bot paper modda çalışır.

## 3. Sinyal Motoru (7 faktör + veto zinciri)

**Konflüans puanı (0-7):** giriş için `score ≥ score_threshold (vars. 4)` VE diğer yöne
karşı **+2 puan fark** gerekir.

| # | Faktör | LONG puanı koşulu | SHORT puanı koşulu |
|---|---|---|---|
| 1 | Yerel trend | EMA21>EMA55 ve fiyat>EMA200 | tersi |
| 2 | MTF trend (1h) | 1h EMA50>EMA200, fiyat üstünde | tersi |
| 3 | MACD | histogram >0 ve güçleniyor | <0 ve güçleniyor |
| 4 | RSI bandı | 45-68 (aşırı değil) | 32-55 |
| 5 | ADX rejimi | ADX≥20 ve +DI>-DI | ADX≥20 ve -DI>+DI |
| 6 | Hacim | hacim > 1.2×ort ve yeşil mum | ... ve kırmızı mum |
| 7 | Bollinger | fiyat üst bandın üstünde | alt bandın altında |

**Sert vetolar (puan ne olursa olsun engeller):**
- 🧟 **Ölü pazar:** ATR/fiyat % < `min_atr_pct` (0.12) → hareket komisyonu karşılamıyor
- 🥵 **Tükenme:** RSI ≥ 73 (veya ≤ 27) VE Bollinger kırılımı yoksa geç giriş reddi
- 💸 **Funding:** |funding| > %0.05 ise ödeyen tarafa giriş yok
- 📉 **OI vetosu:** açık pozisyonlar 4 saatte %5+ çöktüyse veya %10+ kaotikse giriş yok
- 🚫 **MTF uyumsuzluğu:** üst zaman dilimi trendine ters yönde sinyal puan almaz

## 4. Risk Sistemi (botun kalbi)

```
giriş sinyali
   │
   ├─ limitler: max 3 pozisyon · aynı yön ≤ 2 · günlük zarar ≤ %5 · haftalık ≤ %12
   ├─ soğuma: zarar sonrası aynı sembolde 3 mum bekleme
   ├─ devre kesici: 3 art arda emir hatası → tüm girişler kilitlenir
   │
   ├─ STOP PLANI: sl = ATR×1.5 ile swing±0.2×ATR arasından DAHA GENİŞ olanı
   │     · mesafe fiyatın %8'ini aşarsa İŞLEM REDDEDİLİR
   │     · kaldıraç merdiveni: likidasyon mesafesi stop×1.4'ten küçükse kaldıraç düşer
   ├─ BOYUT: qty = sermaye×%1 / stop mesafesi   (notional = sermaye×kaldıraç ile sınırlı)
   │
   ├─ GİRİŞ: market + koruma emirleri (SL tam miktar, TP1 %50, TP2 %50 — reduceOnly)
   │
   └─ YÖNETİM:
         +1R  → TP1: %50 kapat, stop başabaşa
         +1R  → kilit merdiveni: stop başabaşa [1.0, 0.0]
         +1.5R → kilit: +%0.5R sabitlenir [1.5, 0.5]
         her mum → ATR×1.5 trailing (kilitleri aşabilir)
         +2R  → TP2: kalanı kapat
```

Isolated margin: sıvılaşma yalnız o pozisyonun marjını yakar, hesabı değil.

## 5. Paper Testi Nasıl İzlenir?

| Dosya | İçerik |
|---|---|
| `bot_<tf>.log` | Her karar, açılış/kapanış, engellenen girişler + nedenleri |
| `trades_<tf>.csv` | Kapanan her parça: yön, miktar, giriş/çıkış, PnL, sebep (SL/TP1/TP2) |
| `state_<tf>.json` | Sermaye + açık pozisyonlar (restart'ta otomatik geri yüklenir) |
| `signals.csv` | scan modunda ateşlenen tüm sinyaller |

**Değerlendirme kriterleri (birkaç günlük koşudan sonra):**
- Kazanma % + kar faktörü > 1.2 hedeflenir; TP1'ler PF'yi yukarı taşır
- Max düşüş %5-8 içinde mi? Devre kesiciler tetiklendi mi?
- Hangi sembol/zaman dilimi sinyalleri kaliteli? `signals.csv`'deki gerekçe dağılımına bakın

## 6. Parametre Kalibrasyonu (DÜRÜST UYARI)

**Ölçülen gerçek sonuç (raporlanması için):** varsayılan parametrelerle 2026-11
itibarıyla son ~10 günlük BTC 15m verisinde backtest **negatiftir** (1000 mum, 66 işlem,
PF 0.63, -%6.1). Eşik 6'ya çekilince PF 0.72, kayıp -%0.9'a düşer.

Bu **normal ve beklenen bir durumdur**: hiçbir varsayılan parametre seti her pazar
döneminde kâr etmez. Botun değeri sağlam risk iskeletidir — parametreleri SİZ calibrate
edersiniz:

1. `backtest.py --folds 4` ile böl-basit walkforward: her fold ayrı raporlanır; bir
   fold'da kâr diğerinde zarar → parametre dayanıksız demektir
2. `score_threshold` 4→6 arası, `adx_min` 20→25 arası, `sl_atr_mult` 1.2-2.0 arası tarayın
3. Farklı sembol/zaman diliminde AYNI sonucu alın (overfit işareti)
4. Sonra paper moda geçin: backtest ≠ canlı; paper'da da onaylaysınız

⚠️ Aşırı kalibrasyon (overfit) en büyük tehlikedir: AcarBot'ta gördüğümüz gibi geçmiş
kazanan listesine göre incelenmiş eşikler canlıda bozulur. Az sayıda parametreyi,
uzun pencerede, mantıkla kalibre edin.

## 7. API Bağlantısı (SON ADIM — tek eksik bu)

Paper testleri bitip canlıya geçeceğinizde:

1. `.env.example` → `.env` kopyalayın
2. **Önce testnet:** https://testnet.binancefuture.com → anahtar alın → `.env`'e yazın
   (`testnet: true` kalsın) → `python main.py trade --live --yes`
3. Testnet 1+ hafta sorunsuzsa gerçek anahtar: Binance → API Management →
   **Futures izinli** anahtar (yalnız trade izni, para çekme izni YOK, IP beyaz listesi)
   → `config.yaml`'da `testnet: false` → `python main.py trade --live --yes`
4. İsteğe bağlı Telegram: @BotFather'dan token alın, `.env`'e girin

`.env` dosyasını ASLA paylaşmayın, git'e koymayın, ekran görüntüsüne almayın.

## 8. Mimari

```
main.py            CLI: scan / trade
backtest.py        geçmiş veri testi (fold raporlu) + öz-test
selftest.py        40+ kontrol: göstergeler, risk matematiği, paper yaşam döngüsü
core/
  config.py        YAML yükleme + doğrulama + güvenli varsayılanlar
  indicators.py    EMA RSI ATR ADX MACD BB — bağımlılıksız
  strategy.py      7 faktör konflüans + vetolar + MTF serisi (lookahead'siz)
  risk.py          boyutlandırma, stop planı, kaldıraç merdiveni, TP/kilit, vetolar
  exchange.py      ccxt sarmalayıcı: retry, testnet, stop emirleri, funding/OI
  trader.py        pozisyon yaşam döngüsü, kısmi TP, mutabakat, kalıcılık, günlük
  scanner.py       anahtarsız sinyal tarayıcı (tablo + CSV + Telegram)
  notify.py        isteğe bağlı Telegram
```

Tasarım ilkeleri (eski bottan alınan dersler): executor "god-object" yok; her modül tek
sorumlu; kalıcılık bozulursa bot yedeğe alıp temiz başlar (kilitlenmez); mutabakatta
hayalet pozisyon silinir, yetim pozisyon SAHİPLENİLİR ve koruma emri takılır; borsa
zaman damgasına güvenilmez, yalnız kapalı mumla karar verilir.

## 9. Sorun Giderme

| Sorun | Çözüm |
|---|---|
| `Way too many requests / IP banned` | Paylaşılan IP rate-limiti; bekleyin. Kendi makinenizde görmezsiniz |
| `-4046` log uyarısı | Lev/margin zaten ayarlı — zararsız |
| Backtest `fetch_ohlcv` limiti | Binance/Bybit tek çağrıda ~1000-1500 mum verir; `--bars` üst sınırlıdır |
| Pozisyon uyuşmazlığı uyarısı | Elle müdahale ettiyseniz normal; log'u kontrol edin |
| state dosyası bozuk | `.bozuk` uzantısıyla yedeklenir, bot temiz başlar |

## 10. Yol Haritası (sonraki sürümler)

- WebSocketa geçiş (REST poll yerine canlı akış, AcarBot'taki 5 sn fiyat yaşı kuralı)
- Order-flow (CVD/taker delta) ve haber skorlarının konflüansa ekleme
- Korelasyon temelli portföy koruması (Pearson ≥ 0.80 aynı yön filtresi)
- Tam walkforward optimizasyon + parametre dayanıklılık haritası
- Bybit/OKX çift borsa arbitraj katmanı

---

⚠️ **YASAL UYARI:** Kripto futures yüksek kaldıraçlı, yüksek riskli ürünlerdir.
Bu yazılım eğitim ve araştırma amaçlıdır; yatırım tavsiyesi değildir. Geçmiş
performans gelecek getirinin göstergesi değildir. Kaybedebileceğinizden fazla
para riske atmayın.
