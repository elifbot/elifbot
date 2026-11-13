# ACARBOT — FINAL v1.8

> **v1.8** (7 Kasım 2026): işlem başı **25 USDT HEDEF net risk** — eski 500 USDT
> nominal tavanı varsayılan olarak kaldırıldı, teminat dinamik hesaplanır
> (`notional / kaldıraç`). Dar stoplarda risk artık ~3-5 USDT'ye düşmez;
> her yeni işlem 25 USDT net riske göre boyutlanır. Teminat yetmezse giriş
> açılmaz (risk sessizce küçültülmez). 281/281 test.
> `DEGISIKLIKLER_FINAL_v1.8.md`.
>
> **v1.7** (7 Kasım 2026): bayat sinyal giriş koruması — canlı fiyat zaten
> stopun ötesindeyse giriş iptal (FTT tipi anında stop-out engellendi).
> 264/264 test. `DEGISIKLIKLER_FINAL_v1.7.md`.
>
> **v1.6** (7 Kasım 2026): RVOL sahte-hacim düzeltmesi — baz hacim kullanılır,
> fiyat oynaklığı artık sahte sinyal üretmez (300 sahte engel → 0).
> SQLite thread hatası giderildi. 258/258 test. `DEGISIKLIKLER_FINAL_v1.6.md`.
>
> **v1.5** (7 Kasım 2026): TAM PAZAR TARAMASI `--scan-all` — Binance 518 +
> OKX 528 = 1046 feed aynı anda. Paralel mum taraması (~82 sn/döngü),
> OKX WS parçalama, giriş anında sweep defteri, ölçeklenmiş veri
> bütünlüğü. 250/250 test. Ayrıntılar: `DEGISIKLIKLER_FINAL_v1.5.md`.
>
> **v1.4** (7 Kasım 2026): motor seçimi `--motors trend|fade|both`.
> FADE kapatılınca (TREND-only) backtest kâra geçti: +37,1 USDT, PF 2.20
> (varsayılan eşiklerle, 3,5 gün / 12 sembol). 224/224 test.
> Ayrıntılar: `DEGISIKLIKLER_FINAL_v1.4.md`.
>
> **v1.3** (7 Kasım 2026): sinyal eşikleri CLI'dan ayarlanabilir
> (`--min-rvol`, `--fade-impulse`, `--spike-multiplier`); varsayılanlar
> korunur. 214/214 test. Ayrıntılar: `DEGISIKLIKLER_FINAL_v1.3.md`.
>
> **v1.2** (7 Kasım 2026): Binance otomatik ayna fallback'i (bölgesel engel
> varsa resmî mainnet spot veri aynası) + çift borsa sembol eşleme +
> Binance depth limit düzeltmesi. 208/208 test. `--exchange all` artık
> tek sembol listesiyle çalışır. Ayrıntılar: `DEGISIKLIKLER_FINAL_v1.2.md`.
>
> **v1.1** (7 Kasım 2026): APEX profili geri eklendi (`--profile apex`: sınırsız
> pozisyon + günlük fren yok — kullanıcı tercihi) + gerçek haber koruması
> (FF takvimi) + orderbook tabanlı stop-hunt duvar koruması. 193/193 test.
> Ayrıntılar: `DEGISIKLIKLER_FINAL_v1.1.md`.
>
> **v1.0** (7 Kasım 2026): "son sürümler" klasöründeki 6 sürümün
> karşılaştırması sonucu en güncel ve en kapsamlı sürüm olan **bot_super**
> taban alınarak hazırlandı. Hata düzeltmeleri + süreli oturum (`--duration-minutes`)
> + oturum sonu JSON raporu eklendi. Ayrıntılar: `DEGISIKLIKLER_FINAL.md`.
> Hızlı 15 dk testi: `./run_test_15min.sh` (OKX) — Windows: `run_paper_windows.bat`.

Üç bağımsız inceleme yorumu + önceki kod inceleme raporunun bulguları tek bir
mimaride birleştirildi. **Yalnızca paper trading çalışır; gerçek borsaya emir
gönderilmez** (bu, güvenli test aşamasının bilinçli bir özelliğidir).

Varsayılan hesap parametreleri (v1.8): **1.000 USDT bakiye, 10x kaldıraç,
dinamik teminat (`notional / 10`), işlem başı 25 USDT hedef net risk,
nominal tavanı kapalı.** APEX profilinde pozisyon adedi sınırsızdır; doğal
sınır serbest bakiye/teminat ve drawdown korumasıdır.

---

## 1. Üç yorumun bulguları → çözüm matrisi

| # | Bulgu (kaynak) | Çözüm | Modül | Durum |
|---|---|---|---|---|
| 1 | **RVOL birim hatası**: 1 sn'lik sentetik mum 5 dk'lık mum ortalamasıyla kıyaslanıyordu; 3x patlama RVOL≈0.01 veriyordu (Y2-1) | Pay/payda AYNI ölçekte: saniyelik baz hacim ↔ saniyelik taban. Ayrıca sanity cap (RVOL>100 = şüpheli veri) | `core/spike.py` | ✅ test edildi |
| 2 | **Yön çelişkisi**: canlıda SHORT hiç açılamıyordu (Y2-2) | Her motor LONG+SHORT üretir; spike yalnız tetikleyicidir; çakışmayı rejim çözer | `core/strategy.py` | ✅ test edildi |
| 3 | **FADE'de kâr yolu yok**: trailing %20 hareket istiyordu, time-stop kapalıydı (Y2-3) | TP1 (+1R %50) → ATR trailing (2×ATR, 0.75R erken aktivasyon), zaman stopu (FADE 90 dk), momentum çıkışı | `exec/paper.py` | ✅ test edildi |
| 4 | **25 USDT garanti değil**: kontrol brüt PnL üzerinden, maliyetler sonra ekleniyordu (Y2-4, Y1-B) | Net tavan: boyutlandırma VE acil durdurma ücret+kayma+funding'i ÖNCEDEN düşer | `core/risk.py`, `exec/paper.py` | ✅ test edildi |
| 5 | **Maker dolum iyimserliği**: her emir anında doluyordu + post-only'ye taker kayması (Y2-5, Y1-A) | Emir yaşam döngüsü NEW→PARTIALLY_FILLED→FILLED/CANCELED/EXPIRED; kuyruk modeli, kısmi dolum, TTL, trade-through; ters seçilim doğal olarak modelde | `exec/orders.py` | ✅ test edildi |
| 6 | **Backtest canlıyı test etmiyor**: filtre yok, tek sembol, metrik yok (Y2-6, Y1-D) | Canlıyla AYNI katmanlar; çoklu sembol portföy simülasyonu; sinyal mumunda giriş YOK, limit sonraki mumda değerse dolar | `backtest/engine.py` | ✅ test edildi |
| 7 | **Eksik metrikler**: MaxDD, PF, Sharpe, beklenti, ardışık kayıp yoktu (Y1-D) | Tam metrik paketi + maliyet ayrıştırması + motor/sembol/yön kırılımı | `backtest/metrics.py` | ✅ test edildi |
| 8 | **Funding/likidasyon yoktu** (Y1-C) | 8 saatlik funding ödemeleri (yön duyarlı), izole teminat likidasyon fiyatı, likidasyon cezası, %80 teminat uyarısı | `core/risk.py`, `core/portfolio.py` | ✅ test edildi |
| 9 | **Korelasyon ve kill switch yoktu**; günlük limit yalnız girişi durduruyordu (Y2-7, Y1-G) | Korelasyon grupları (major/L1/meme/DeFi), grup başına pozisyon+nominal tavanı, toplam açık risk tavanı, yönsel denge, portföy drawdown koruması, SOFT_STOP / HARD_HALT kill switch (hard → hepsi kapatılır) | `core/risk.py` | ✅ test edildi |
| 10 | **~18 eşzamanlı pozisyon açılabiliyordu** (Y2-7) | `max_positions=6` varsayılanı; `--max-positions 1` ile ACARBOT'un "tek aktif işlem" ilkesi | `core/config.py` | ✅ |
| 11 | **Veri bütünlüğü zayıftı** (Y1-F) | Mum boşluğu tespiti + geri doldurma; bayat tick engeli; borsalar arası sapma (%0.5); yeniden başlatma ısınması; global GÜVENLİ MOD (giriş yok, bekleyen emirler iptal, stoplar çalışmaya devam) | `infra/feed.py` | ✅ test edildi |
| 12 | **Her tick'te FULL fsync** (Y2) | `synchronous=NORMAL` + WAL; kayıt 1 sn'de bir kısılmış (`save_state_if_due`); kritik olayda elle checkpoint | `state/store.py` | ✅ test edildi |
| 13 | **Günlük PnL tüm tabloyu tarıyordu** (Y2) | `ts_ms` sütunu + indeks ile SQL SUM | `state/store.py` | ✅ test edildi |
| 14 | **Senkron Telegram event loop'u blokluyordu** (Y2) | asyncio kuyruğu + arka plan görevi + dakikalık hız limiti | `safety/alerts.py` | ✅ test edildi |
| 15 | **OKX kontrat / Binance baz birim doğrulaması yoktu** (Y2) | `contract_size` çevirici + RVOL sanity cap | `core/spike.py` | ✅ test edildi |
| 16 | **Loglama/yedekleme/Docker/CI yoktu** (Y3) | Dosya+konsol loglama, başlangıçta otomatik SQLite yedeği (son 5 saklanır), Dockerfile, docker-compose (restart: unless-stopped), GitHub Actions CI | kök dizin | ✅ |
| 17 | **Yeniden bağlanma/dayanıklılık** (Y3) | Borsa istemcilerinde `stream_tickers_reconnecting` (üstel geri çekilme) korunup kullanıldı | `infra/exchanges/*` | ✅ (devralındı) |
| 18 | **Yatay piyasa/sahte kırılım/BTC filtresi yoktu** (Y1-E) | ADX+EMA rejim dedektörü, fitil oranlı sahte kırılım filtresi, BTC 15 dk yön filtresi, düşen/yükselen bıçak koruması | `core/strategy.py` | ✅ test edildi |
| 19 | **Walk-forward yoktu** (Y1-D) | Veriyi k pencereye böler, pencere bazlı OOS raporu | `backtest/walkforward.py` | ✅ test edildi |
| 20 | **Günlük rapor / motor karşılaştırma / R-çarpanı yoktu** (Y1-5. aşama) | UTC günü raporu, motor/sembol tabloları, işlem başı R | `monitor/report.py` | ✅ |

## 2. Mimari

```
bot_super/
├── core/
│   ├── config.py          # TÜM eşikler tek yerde (canlı = backtest = test)
│   ├── spike.py           # Birim-tutarlı RVOL + birim doğrulama
│   ├── strategy.py        # FADE(L/S) + TREND(L/S) + rejim/BTC/sahte-kırılım
│   ├── indicators.py      # EMA, MACD, ATR, ADX... (eski güçlü kütüphane)
│   ├── portfolio.py       # Pozisyon: funding, likidasyon, R, TP1 durumu
│   └── risk.py            # Boyutlandırma + portföy limitleri + kill switch
├── exec/
│   ├── orders.py          # Emir yaşam döngüsü + kuyruklu maker dolum
│   └── paper.py           # Paper broker: tüm çıkış yolları, net zarar tavanı
├── infra/
│   ├── feed.py            # Veri bütünlüğü + güvenli mod
│   ├── exchanges/         # Binance + OKX (public veri, reconnect)
│   └── market_data/       # Mum modeli
├── state/store.py         # SQLite WAL, ts indeksli, yedeklemeli
├── safety/                # Asenkron Telegram + gizli bilgi maskeleme
├── backtest/              # engine + metrics + walkforward
├── monitor/report.py      # Günlük rapor + Prometheus formatı
├── app/                   # executor + asyncio CLI
└── tests/                 # 145 test
```

## 3. Çalıştırma

```bash
# Testler
python -m pytest tests/ -q

# Backtest (CSV: data/BTCUSDT_5m.csv → timestamp,open,high,low,close,volume)
python -m app.main --mode backtest --data-dir data --balance 1000 --max-positions 4

# Paper (canlı public veri, simüle emirler)
python -m app.main --mode paper --paper --exchange binance \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT --balance 1000 --max-positions 6

# ACARBOT katı mod: tek aktif işlem + kill switch
python -m app.main --mode paper --paper --max-positions 1

# Docker
docker compose up -d
```

Telegram bildirimleri için `.env` (örnek: `.env.example`):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## 4. Risk modeli özeti

- **Boyutlandırma (v1.8):** `notional = 25 / (stop% + ücretler + kayma + funding_oranı)`,
  `margin = notional / kaldıraç`. Hedef: her yeni işlemde stop'a gidilirse
  beklenen net zarar **25 USDT**. Eski 500 USDT nominal tavanı varsayılan
  olarak kapalıdır; pozitif legacy tavan verilirse üst sınır olarak uygulanır.
- **Stop:** ATR tabanlı (1.5×ATR), %0.3-%2.5 aralığına kelepçeli.
- **Çıkışlar:** TP1 (+1R, %50) → trailing (2×ATR); momentum çıkışı (≥0.75R);
  zaman stopu (FADE 90 dk, TREND 24 saat); acil net-zarar stopu (≤ -25);
  likidasyon (izole teminat yaklaşımı).
- **Portföy:** maks 6 pozisyon, grup başına 2, toplam açık risk ≤ 150 USDT,
  brüt nominal ≤ 3.000, yönsel denge ≤ 1.000, günlük -100 soft / -150 hard,
  equity tepe-dipte %8 → güvenli mod.
- **25 USDT bir GARANTİ değil, HEDEF net risktir:** stop'a normal koşullarda
  gidilirse beklenen net zarar 25 USDT'dir. Gap/aşırı kayma/funding gerçek
  zararı büyütebilir; model bunu şeffaf biçimde raporlar. Teminat yetmeyen
  işlemler açılmaz, risk sessizce küçültülmez.

## 5. Bilinen sınırlar / sonraki adımlar

1. Backtest maker dolumu mum ölçeğinde muhafazakârdır (tek mum dokunma şartı);
   tick geçmişiyle kalibre edilmeli.
2. Funding oranı varsayılan %0.01/8s; gerçek tarihsel oranlar
   `funding_rates` parametresiyle beslenebilir.
3. Eşik parametreleri veriyle doğrulanmalı: 4. aşama walk-forward +
   farklı rejimlerde (2021 boğa, 2022 ayı, 2023 yatay) ayrı çalıştırma.
4. Gerçek emir gönderimi KASTEN yoktur; canlıya geçiş ayrı bir güvenlik
   tasarımı gerektirir (API anahtarı, emir mutabakatı, kill switch devri).
