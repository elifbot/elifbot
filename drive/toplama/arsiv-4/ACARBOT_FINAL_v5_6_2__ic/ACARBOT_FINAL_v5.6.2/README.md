# ACARBOT — v5.6.2

Kripto vadeli işlem botu (Binance / OKX). **Yalnızca paper ve testnet/demo
çalışır; gerçek para kapalıdır.** Strateji kârlılığı **kanıtlanmamıştır**.

> Ayrıntılı geçmiş: `DEGISIKLIKLER.md` (dizin) · güncel hüküm:
> `docs/dogrulama_v5.6_final.md` · yol haritası: `V6_GELISTIRME_PLANI.md` ·
> hangi belge güncel: `docs/OKU_BENI_ONCE.md`

## Durum (dürüstlük notları)

- **Giriş kenarı YOK.** Hüküm `NO_EDGE`: 5m ve 15m'de kenar istatistiksel
  olarak elendi, 1h'de örneklem yetersiz. Walk-forward 0/3 pencere kârlı,
  net beklenti −0,32 R, Profit Factor 0,30. Zararın büyük kısmı işlem maliyeti.
- **Gerçek para kapısı iki kilitli:** `live.enabled=False` + boş
  `live_allowed_timeframes` + kenar kanıtı zorunluluğu (`core/gates.py`).
  Kenar kanıtlanmadan açılmamalıdır.
- **Testnet uçtan uca hiç koşulmadı** (API anahtarı yok); koruyucu stop
  testnet'te doğrulanmadı. Canlıya geçiş öncesi `docs/testnet_oturum_kilavuzu.md`.
- **Yapılmayanlar (ağ/zaman gerektirir):** 12 ay × 30-50 sembol veri
  (Faz 1), 300 dolumluk maker markout ölçümü, Binance komisyon ölçümü,
  tarihsel funding CSV'leri. Kongre ajanı bilerek "uygulanmadı" stub'ıdır;
  web paneli yoktur (`monitor/dashboard.py` konsol/veri toplayıcıdır).
- **Haber koruması varsayılan fail-open'dır:** takvim alınamazsa girişler
  engellenmez. v5.6.2'den itibaren `news_guard.status()["degraded"]` bunu
  görünür kılar; canlıya geçilirse `fail_closed=True` değerlendirilmelidir.
- Paket örnek veri **içermez** (`data/` boştur); backtest için önce veri indirin.

## Kurulum

```bash
pip install -r requirements.txt          # yalnız çalışma: websockets
pip install -r requirements-dev.txt      # + pytest, ruff (test/lint)
python -m pytest tests/ -q               # test sayısı için bu komut tek kaynaktır
python -m app.main --help
```

`requirements-lock.txt` geliştirme ortamının tam kilididir (Python 3.12).

**Windows:** `run_paper_windows.bat` (paper), `run_test_15min.bat`,
`run_testnet_session.bat 1440 binance`. Komutlarda `python3` yazan yerlerde
Windows'ta `python` (veya `py -3`) kullanın.

## Hızlı başlangıç

```bash
# 1) Paper (canlı veri, simülasyon emirler)
python -m app.main --mode paper --paper --exchange okx --profile kasa1000 \
    --symbols BTC-USDT-SWAP --balance 1000

# 2) Backtest — ÖNCE veri indir (API anahtarı gerekmez), sonra koş
python tools/download_history.py --exchange okx --symbol BTC-USDT-SWAP \
    --out-symbol BTCUSDT --bars 2000 --data-dir data
python -m app.main --mode backtest --data-dir data --symbols BTCUSDT

# 3) Çok sembollü doğrulama ve hüküm (90+ gün veri gerekir)
python -m tools.validate_strategy --help

# 4) Faz 1 veri bütçesi (çevrimdışı tahmin)
python -m tools.data_budget --symbols 50 --months 12 --intervals 5m
```

Profiller: `guarded`, `kasa1000` (1000 USDT, pozisyon başı 25 USDT zarar
tavanı, günlük fren), `kasa1000_cross` (CROSS marj, 20 pozisyon),
`apex` (**yalnız araştırma**).

Diğer seçenekler (`--strategy`, `--session`, `--dca`, `--scan-all`,
`--motors`, `--us-market`, ...): `python -m app.main --help`.

## Testnet eşleme

```bash
# Binance testnet (anahtarlar ortamdan veya *_FILE dosyasından)
export BINANCE_TESTNET_API_KEY=...  BINANCE_TESTNET_API_SECRET=...
python -m app.main --mode paper --paper --live-testnet --live-exchange binance \
    --symbols BTCUSDT

# OKX demo — market giriş + conditional algo stop + reduce-only çıkış
export OKX_DEMO_API_KEY=... OKX_DEMO_API_SECRET=... OKX_API_PASSPHRASE=...
python -m app.main --mode paper --paper --live-testnet --live-exchange okx \
    --symbols BTC-USDT-SWAP

# 24-48 saatlik oturum (kılavuz: docs/testnet_oturum_kilavuzu.md)
./run_testnet_session.sh 1440 binance        # Windows: run_testnet_session.bat 1440 binance

# Acil durum: tüm pozisyonları kapat
python -m app.main --emergency-flatten --live-testnet --live-exchange okx
```

- Stop kurulamazsa pozisyon korumasız kalmaz (3 deneme → reduce-only kapat).
- HARD_HALT'ta borsa pozisyonları da flatten edilir; mirror durumu SQLite'ta.
- Dead-man's switch opt-in: `--deadman-seconds N --deadman-confirm`
  (borsa tarafı countdown koruyucu stopları da iptal eder; bu yüzden varsayılan kapalı).
- Emir/konum güncellemeleri imzalı HTTP yoklamasıyla yürür; WebSocket yalnız
  piyasa verisi içindir.

## Korumalar

| Katman | Mekanizma |
|---|---|
| Sinyal | 100 puanlık skor ≥ 70, Piyasa Hakemi veto, MTF çelişki kapısı |
| Emir | maker kuyruk modeli, kısmi dolum, TTL, spread/kayma/gecikme |
| Risk | pozisyon başı 25 USDT net risk, portföy tavanları, beta yön tavanı |
| Hesap | equity eşiği −%15 → HARD_HALT (+ borsa flatten), cross likidasyon |
| Akış | giriş 3/dk, stop sonrası yeniden giriş beklemesi |
| Veri | forming mum eleme, gap → güvenli mod, RVOL sanity, haber/sweep koruması |
| Borsa | sunucu tarafı stop, reduce-only çıkış, idempotent clientOrderId |
| Canlı kapı | zaman dilimi izin listesi + kenar kanıtı (çift kilit) |

## Dizin

```
core/      config, strateji, pipeline, rejim, MTF, order flow, skor, kapılar, risk
exec/      emir (maker kuyruk) + paper broker + markout
infra/     borsa istemcileri (Binance/OKX), feed, tick doğrulama, mum modeli
backtest/  motor, maliyet, mum içi yol, walk-forward, Monte Carlo, hüküm, regresyon kapısı
live/      testnet/demo katmanı (imzalı HTTP, LiveMirror, acil durum, restart kurtarma)
safety/    haber koruması, sweep guard, uyarılar, sır maskeleme
agents/    analist, ABD piyasası, RSS haber, kongre (stub)
monitor/   konsol paneli + oturum raporu
state/     SQLite WAL kalıcılık
app/       executor + CLI
tools/     download_history, data_budget, measure_costs, validate_strategy,
           entry_edge, exit_geometry, make_reference, package_release, ...
docs/      güncel doğrulama raporu, maliyet ölçümü, regresyon referansı, kılavuz
tests/     birim ve entegrasyon testleri (ağ gerektirmez)
```

## Araçlar (modül olarak çalıştırın)

`python -m tools.<ad> --help` — `tools/` paket değil dizindir; kök dizinden
`-m` ile çağrılır. Sürüm paketleme: `python -m tools.package_release`.

## Lisans

Bkz. `LICENSE`.
