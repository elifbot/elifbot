# ACARBOT — FINAL v5.0

> **v5.0** (7 Kasım 2026) — **İKİ HATTIN BİRLEŞİMİ.** v4.0'ın sinyal/analiz
> katmanı (uzmanlar, rejim, MTF, order flow, confluence, DCA, ajanlar, Monte
> Carlo, canlı emir katmanı) + v1.10'un canlıda doğrulanmış risk düzeltmeleri.
>
> **Yeni:** hedef net risk **25 USDT** (nominal tavan kapalı) · **dinamik
> teminat** (nominal/kaldıraç) · **stop fiyat ızgarası hizalama** (BTTC gibi
> kaba ızgaralı coinlerde −28 yerine −25) · **dolum anı teminat kilidi** ·
> bekleyen emir **teminat rezervasyonu** · RVOL **likidite tabanı 5 USDT/sn** ·
> `LİKİDİTE DÜŞÜK` ↔ `RVOL ŞÜPHELİ` ayrımı + sembol başına log kısıtlama ·
> **maker dolum açlığı düzeltmesi** · oturum raporunda `volume_filter` ve
> `target_risk_audit` denetim blokları.
>
> **Test: 549/549 passed.** Ayrıntılı analiz: **`ANALIZ_v5.0_DETAYLI.md`** ·
> Değişiklik günlüğü: **`DEGISIKLIKLER_FINAL_v5.0.md`**
>
> ⚠️ **Dürüst uyarı:** v3.0/v4.0'ın gerçek veri backtest'i zarar ediyor
> (net −6,68 USDT, 8 işlem, PF 0,31). v5.0 risk *hassasiyetini* düzeltir,
> **kâr eden sinyal üretmez**. 25 USDT'ye ölçeklemeden önce analiz dokümanının
> 8.1 bölümünü okuyun.

---

> **v4.0** (7 Kasım 2026): Kullanıcının Faz 2-4 listesinin uygulanması —
> **seçilebilir stratejiler** (`--strategy confluence|rsirev|macd|bollkir|bolldon`;
> Confluence = 10 filtreli ağırlıklı oylama, `--confluence-threshold` eşikli),
> **DCA güvenlik emirleri** (`--dca`; vars. kapalı, yalnız LONG, net risk 25
> USDT tavanı korunur), **seans filtresi** (`--session asia|eu|us|"HH-HH"`),
> **canlı emir sertleştirme** (429/Retry-After yeniden deneme, borsa saat
> senkronu + -1021/50102 otomatik resync, hedge mode/one-way otomatik
> algılama + positionSide/posSide, post-only maker giriş + MARKET yedek),
> **para akışı** (gerçek funding oranı, long/short hesap oranı, Binance
> likidasyon akışı WS; OI+CVD zaten vardı), **ajanlar** (ABD piyasası
> SPX/Nasdaq/DXY/VIX risk-on/off — canlı testte gerçek veriyle çalıştı;
> RSS haber duyarlılığı; kongre ajanı dürüst "uygulanmadı"; analist ajanı
> oturum raporunu yorumlar), **tarihsel funding indirme + çok rejimli
> backtest dökümü**, **24-48h testnet kılavuzu + senaryo** (`docs/
> testnet_oturum_kilavuzu.md`). **483/483 test** (208 v1.2 aynen + 275
> v2/v3/v4). Ayrıntılar: `DEGISIKLIKLER_FINAL_v4.0.md`.
>
> **v3.1** (7 Kasım 2026): Dış v1.3-v1.7 geliştirme hattının **tek kapıda
> birleştirilmesi** (kullanıcı talebi; her özellik v3.0 mimarisine uyarlandı,
> dış sürümden kod kopyalanmadı): **--scan-all** tam pazar taraması (528 OKX
> + Binance feed'leri, paralel tarama + 429 rate pacer + OKX WS 250'lik
> parçalama), **--motors** motor seçimi (pipeline tek kapı: canlı +
> backtest aynı kural), **baz hacim düzeltmesi** (RVOL sahte-hacim hatası:
> fiyat oynaklığı işlem yokken sahte spike üretiyordu — v1.6 vakası),
> **bayat sinyal giriş koruması** (canlı fiyat stopu aşmışsa giriş iptal —
> FTT anında stop-out vakası), **CLI eşikleri** (--min-rvol, --fade-impulse,
> --spike-multiplier) + tam pazar veri bütünlüğü ölçeklemesi. **389/389
> test** (208 v1.2 aynen + 181 v2/v3). Canlı duman testi: OKX 528 feed,
> tam döngü 66 sn, 0 hata/429. Ayrıntılar: `DEGISIKLIKLER_FINAL_v3.1.md`.
>
> **v3.0** (7 Kasım 2026): Bağımsız dış incelemenin 20+ bulgusu tek tek
> kodda doğrulandı ve **doğrulananların tamamı düzeltildi**. En kritikler:
> OKX acil durum flatten yönü, OKX sCode sessiz hata, HTTP hata gövdesi
> kaybı (-4046), koruyucu stop kurulamazsa korumasız pozisyon, borsa
> filtre yuvarlaması, HARD_HALT'ta borsa pozisyonlarının açık kalması,
> stop güncellemelerinin borsaya yansımaması, event loop kilidi,
> RestartRecovery'nin bağlanmaması, OKX `cancel-all-orders` yanlış ucu.
> Ayrıca: OKX'te TAM emir eşlemesi, dead-man's switch (opt-in), log
> rotasyonu, gizli anahtar dosya desteği, backtest kayma/gecikme modeli,
> gerçek veriyle backtest kanıtı + veri indirme aracı. **326/326 test**
> (208 v1.2 aynen + 95 v2/v3). Ayrıntılar: `DEGISIKLIKLER_FINAL_v3.0.md`.
>
> **v2.0** (7 Kasım 2026): 9 maddelik geliştirme paketi + 5 uzman motor
> mimarisi + "A. Zorunlu risk" ve "B. Ölçüm" listeleri — mevcut sistem
> bozulmadan. Akıllı rejim + MTF + order flow + 100 puanlık skorlama +
> Piyasa Hakemi + equity eşiği + BTC şok testi + giriş hız limiti +
> Monte Carlo + kontrol paneli + testnet güvenlik çatısı.
>
> **v1.2** (7 Kasım 2026): Binance otomatik ayna fallback'i + çift borsa
> sembol eşleme. **v1.1**: APEX profili + haber koruması + sweep guard.
> **v1.0**: bot_super tabanı + süreli oturum + oturum raporu.

## Önemli gerçekler (dürüstlük notları)

- **Yalnızca paper trading çalışır.** Gerçek borsaya emir gönderilmez;
  testnet/demo eşleme (`--live-testnet`) ayrıca ve açıkça istenir.
- **Strateji kârlılığı KANITLANMAMIŞTIR.** Gerçek OKX verisiyle (BTC-USDT-SWAP,
  ~7 gün, 2000 5m mum) backtest **8 işlem** üretir — sinyal→emir→pozisyon
  zinciri çalışıyor demektir — ama net sonuç bu örnekte **negatiftir**
  (`docs/backtest_gercek_veri.json`). Parametre kalibrasyonu ve uzun dönem
  testi gerekir. Backtest/paper sonucu gelecek getirinin garantisi değildir.
- **Paket gerçek veriyle gelir:** `data/BTCUSDT_5m.csv` (OKX public uçlardan
  indirildi; kendi veriniz için `tools/download_history.py`).

## Dizin ağacı (v3.0 — güncel)

```
ACARBOT_FINAL_v4.0/
├── core/                  # config, strategy (FADE/TREND), pipeline, regime,
│   │                      # mtf, orderflow, scoring, experts, gates,
│   │                      # portfolio_risk, risk, portfolio, spike, sweep_guard
│   └── symbols.py         # v3.0: kara liste KALDIRILDI (tüm coinler aday)
├── exec/                  # orders (maker kuyruk modeli) + paper broker
├── infra/
│   ├── exchanges/         # Binance + OKX (public veri, reconnect, OI)
│   ├── feed.py            # veri bütünlüğü + güvenli mod
│   └── market_data/       # mum modeli
├── backtest/              # engine (spread/slippage/latency/kısmi dolum)
│                          # + metrics + montecarlo + walkforward + optimization
├── live/                  # v3.0: testnet/demo katmanı
│   ├── clients.py         # imzalı HTTP; hata gövdesi KORUNUR; *_FILE desteği
│   ├── broker_clients.py  # Binance testnet + OKX demo (algo stop, filtreler)
│   └── sync.py            # LiveMirror (Binance+OKX), Emergency, RestartRecovery
├── monitor/               # dashboard (9 bölüm) + rapor + Prometheus formatı
├── state/store.py         # SQLite WAL + mirror_state kalıcılığı (v3.0)
├── safety/                # Telegram + haber koruması + maskeleme
├── app/                   # executor + asyncio CLI (v3.0 görevleri)
├── tools/download_history.py  # v3.0: gerçek mum CSV indirici (imzasız)
├── data/BTCUSDT_5m.csv    # v3.0: örnek GERÇEK veri (OKX, 2000 mum)
├── docs/                  # örnek backtest çıktıları
└── tests/                 # 326 test (208 v1.2 değişmedi)
```

## Hızlı başlangıç

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                  # 483 test

# Paper (canlı veri, simülasyon emirler)
python -m app.main --mode paper --paper --exchange okx --symbols BTCUSDT

# v3.1: TAM PAZAR taraması (--symbols yok sayılır; evren borsadan keşfedilir)
python -m app.main --mode paper --paper --exchange all --scan-all \
    --motors trend --duration-minutes 60

# v3.1: motor seçimi + gevşetilmiş eşikler (kod varsayılanları değişmez)
python -m app.main --mode paper --paper --exchange okx --symbols BTCUSDT \
    --motors trend --min-rvol 1.2 --fade-impulse 0.25 --spike-multiplier 2.5

# v4.0: strateji seçimi + seans + DCA + ajanlar
python -m app.main --mode paper --paper --exchange okx --symbols BTCUSDT \
    --strategy confluence --confluence-threshold 0.6 \
    --session us --dca --us-market flag --news-rss flag

# v4.0: 24-48 saat testnet oturumu (tam kılavuz: docs/testnet_oturum_kilavuzu.md)
./run_testnet_session.sh 1440 binance

# Gerçek veriyle backtest (paketteki örnek veri)
python -m app.main --mode backtest --data-dir data --symbols BTCUSDT

# Kendi verini indir (API anahtarı gerektirmez)
python tools/download_history.py --exchange okx --symbol BTC-USDT-SWAP \
    --out-symbol BTCUSDT --bars 2000

# Kontrollü backtest varyantları (config: core/config.py DataConfig)
#   bt_slippage_bps=5, bt_latency_ms=600000  → kayma + gecikme dayanıklılığı
```

## Testnet eşleme (v3.0)

```bash
# Binance testnet (anahtarlar ortamdan veya *_FILE dosyasından)
export BINANCE_TESTNET_API_KEY=...
export BINANCE_TESTNET_API_SECRET=...
python -m app.main --mode paper --paper --live-testnet --live-exchange binance \
    --symbols BTCUSDT

# OKX demo — TAM eşleme (market giriş + conditional algo stop + reduce-only çıkış)
export OKX_DEMO_API_KEY=... OKX_DEMO_API_SECRET=... OKX_API_PASSPHRASE=...
python -m app.main --mode paper --paper --live-testnet --live-exchange okx \
    --symbols BTC-USDT-SWAP

# Acil durum (dışarıdan tek komutla tümünü kapat)
python -m app.main --emergency-flatten --live-testnet --live-exchange okx
```

v3.0 eşleme güvenlik çatısı:
- Stop kurulamazsa pozisyon **korumasız kalmaz** (3 deneme → reduce-only kapat).
- Paper stop değişimleri (break-even/trailing/TP1) borsadaki stopa **yansır**.
- HARD_HALT tetiklenince borsa pozisyonları da **otomatik flatten** edilir.
- Mirror durumu SQLite'ta: restart → çift emir yok, stoplar geri yüklenir.
- Miktar/fiyat borsa filtrelerine yuvarlanır; OKX kontrat dönüşümü ctVal iledir.
- **Dead-man's switch (opt-in):** `--deadman-seconds N --deadman-confirm`.
  DİKKAT: borsa tarafı countdown koruyucu stopları DA iptal eder; bu yüzden
  varsayılan KAPALIDIR ve çift onay ister. Sunucu tarafı stoplar zaten
  bot ölse bile çalışır.

## Korumalar (özet)

| Katman | Mekanizma |
|---|---|
| Sinyal | 100 puanlık skor ≥ 70, Piyasa Hakemi veto, MTF çelişki kapısı |
| Emir | maker kuyruk modeli, kısmi dolum, TTL, spread/kayma/gecikme |
| Risk | pozisyon başı 25 USDT net risk, portföy tavanları, beta yön tavanı |
| Hesap | equity eşiği -%15 → HARD_HALT (+ borsa flatten), cross likidasyon |
| Akış | giriş 3/dk, stop sonrası 15 dk yeniden giriş beklemesi (soft 5 dk) |
| Veri | forming mum eleme, gap → güvenli mod, RVOL sanity, haber/sweep koruması |
| Borsa | sunucu tarafı stop, reduce-only çıkış, idempotent clientOrderId |
| Bot | deadman (opt-in), restart kurtarma, acil durum komutu, log rotasyonu |
| Giriş | v3.1: bayat sinyal koruması (canlı fiyat stopu aşmışsa giriş iptal) |
