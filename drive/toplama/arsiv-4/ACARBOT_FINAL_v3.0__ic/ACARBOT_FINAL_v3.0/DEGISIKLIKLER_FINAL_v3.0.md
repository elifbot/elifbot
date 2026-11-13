# ACARBOT v3.0 — Değişiklik Günlüğü (7 Kasım 2026)

Girdi: kullanıcının ilettiği bağımsız dış inceleme raporu (20+ bulgu).
Yöntem: **her bulgu kodda tek tek doğrulandı**; doğru olanların tamamı
düzeltildi, yanlış olanları gerekçesiyle belgelendi. Sıfırdan yazım yok;
mevcut davranış korunmuş, test paketi büyümüştür: **326/326**
(208 v1.2 aynen + 118 v2/v3).

---

## 1. Doğrulanan ve düzeltilen KRİTİK bulgular

| # | Bulgu | Doğrulama | Düzeltme |
|---|---|---|---|
| 1 | OKX acil durum flatten LONG için `buy` gönderiyor — kapatmıyor | ✅ DOĞRU (`EmergencyController` pozisyonun kendi yönünü geçiyordu) | `OkxDemoTrading.place_reduce_only_exit`: LONG→sell, SHORT→buy; acil durum bunu kullanır |
| 2 | OKX hataları HTTP 200 + sCode≠0 → sessizce başarı sayılıyor | ✅ DOĞRU | `_check_scode`: sCode≠0 → `LiveClientError` (sMsg dâhil) |
| 3 | urllib HTTP 400 gövdesini atıyor → -4046 vs. tüm borsa hata kodları kayıp | ✅ DOĞRU | `urllib_transport` `HTTPError` gövdesini okuyup mesaja ekler; `set_margin_type` -4046'yı gerçek ağda da sessiz geçer (regresyon testi: gerçek yerel HTTP 400 sunucusuyla) |
| 4 | Stop kurulamazsa pozisyon korumasız kalıyor | ✅ DOĞRU | `LiveMirror.mirror_open`: 3 deneme → başarısızsa pozisyon reduce-only **kapatılır** + CRITICAL log; `unprotected_flattened` kaydı |
| 5 | tickSize okunup kullanılmıyor; stepSize/minNotional yok | ✅ DOĞRU | Binance: `fetch_symbol_filters` (public exchangeInfo) + fiyat/tik & miktar/adım yuvarlama + minNotional kontrolü (emir GİTMEZ). OKX: lotSz/minSz/tickSz/ctVal |
| 6 | HARD_HALT borsa pozisyonlarını kapatmıyor | ✅ DOĞRU | `emergency_watch_task`: kill switch HARD_HALT'a geçince testnet/demo **otomatik flatten** (paper tarafı zaten kapatıyordu) |
| 7 | Borsa stopu güncellenmiyor (paper BE/trailing/TP1 borsaya yansımıyor) | ✅ DOĞRU | Executor STOP_UPDATE kuyruğu (`_detect_stop_change`, tick+mum yolları) → `live_mirror_task` → `mirror_stop_update`: eski stop iptal + yeni stop; yeni kurulamazsa eski geri konur, o da olmazsa flatten |
| 8 | Senkron urllib async görevde event loop'u kilitleyebilir | ✅ DOĞRU | Tüm borsa çağrıları `asyncio.to_thread` içinde |
| 9 | OKX'te otomatik emir eşlemesi yok | ✅ DOĞRU (bilinçli kısıttı) | **Kaldırıldı:** OKX demo TAM eşleme (market giriş + conditional algo stop + reduce-only çıkış + stop güncelleme); baz↔kontrat dönüşümü ctVal iledir |
| 10 | OKX `POST /api/v5/trade/cancel-all-orders` ucu v5'te yok | ✅ DOĞRU (ccxt uç listesiyle teyit) | `cancel-batch-orders` (sıradan) + `cancel-algos` (conditional); var olmayan uca çağrı yok (regresyon testi) |
| 11 | RestartRecovery bağlı değil; mirror durumu yalnız bellekte | ✅ DOĞRU | `restart_recovery_task` başlangıçta çalışır (bayat emir iptali + stop restore, Binance + OKX); mirror durumu SQLite `mirror_state` tablosunda → restart'ta çift emir yok, stop fiyatları korunur |
| 12 | Pakette 0 işlemli backtest artefaktı (571× "dusuk_hacim") + 2 dk log | ✅ DOĞRU | Artefaktlar paketten çıkarıldı (.gitignore'a eklendi); **gerçek veriyle backtest kanıtı** pakete kondu (aşağıda) |
| 13 | data/ klasörü ve örnek CSV yok; backtest gerçek veriyle çalıştırılmamış | ✅ DOĞRU | `tools/download_history.py` (OKX/Binance, imzasız) + `data/BTCUSDT_5m.csv` (OKX BTC-USDT-SWAP, 2000 5m mum ~7 gün) + `docs/backtest_gercek_veri.json`: **8 işlem** (7 trend, 1 fade), kısmi dolum 4, Monte Carlo dâhil |
| 14 | executor `contract_size=1.0` sabit; OKX volCcy24h yedeği yanlış birim | ✅ DOĞRU | Ticker yolu USDT-ciro deltası kullanır (1.0 o yolda doğrudur — açıklama kodda); OKX yedek hesap artık `vol24h × ctVal × last` |
| 15 | OKX `pos` alanı kontrat cinsinden ama baz sanılıyordu (flatten 100x!) | ✅ (incelemede ayrıntı olarak çıktı) | `fetch_positions` pozisyon miktarını ctVal ile baz varlığa çevirir |
| 16 | requirements sabitlenmemiş; Docker root; CI lint yok + bozuk YAML; LICENSE yok | ✅ DOĞRU (CI'da ayrıca `branches: ain, master]` yazım hatası) | Hepsinin == pini; Docker non-root `botuser`; CI: lint (ruff E9/F63/F7/F82) + compileall + pytest; MIT LICENSE |
| 17 | README dizin ağacı eski (bot_super/, "145 test") | ✅ DOĞRU | README v3.0 için yeniden yazıldı |
| 18 | Zip'te paper_bot.log + backtest_result.json | ✅ DOĞRU | Paketten çıkarıldı; .gitignore kapsamı genişletildi |

## 2. Kısmen doğru bulgular ve yapılanlar

- **"Spread uygulanmadı, funding sabit"** → doğru. Spread yalnız ölçülmüş
  veri verilirse uygulanır (dürüstlük ilkesi); **v3.0 ek olarak
  `bt_slippage_bps` ve `bt_latency_ms`** eklendi (DataConfig) — kayma
  dolumu aleyhte kaydırır, gecikme dolumu mum atlatır; ikisi de testli.
- **Kısmi dolum muhasebesi** → inceleme önerisinin üzerinde bir hata
  bulundu: paper'da TTL'de kısmen dolan emrin dolan kısmı pozisyona
  dönüşmüyordu (yalnız ücret düşüyordu). Düzeltildi: dolan kısım pozisyon
  olur, `partial` bayrağı dolum oranına göre doğru işaretlenir.
- **Log rotasyonu** → `RotatingFileHandler` (5 MB × 5).
- **API anahtarı güvenliği** → `*_FILE` ortam değişkeni desteği eklendi
  (docker secrets / vault-agent / k8s mount uyumlu). Vault entegrasyonu
  kapsamda değil (aşağıda).

## 3. Yeni özellikler (inceleme talepleri)

- **Dead-man's switch (opt-in):** Binance `countdownCancelAll` +
  OKX `cancel-all-after`. Varsayılan KAPALI ve çift onay
  (`--deadman-seconds N --deadman-confirm`) ister — çünkü countdown
  koruyucu stopları DA iptal eder; sunucu tarafı stoplar zaten bot
  ölse bile çalışır. Bu bilinçli mühendislik tercihi belgelenmiştir.
- **OKX sunucu tarafı koruyucu stop:** `order-algo` conditional +
  `closeFraction=1` (Binance `closePosition=true` eşdeğeri; ccxt hata
  kodları 51327-51330 ile teyitli) + `orderPx=-1` (market tetikleme).
- **Mirror setup:** sembol başına tek seferlik kaldıraç + marj tipi
  (-4046 artık gerçek ağda da sessiz geçilir).
- **Kapanış sonrası stop temizliği:** mirror kapanışta kalan koruyucu
  stopu iptal eder.
- **Veri aracı:** `tools/download_history.py`.

## 4. Test paketi (326)

- Yeni `tests/test_v3_live_fixes.py` (23 test): HTTP gövde kaybı (gerçek
  HTTP 400 sunucusuyla), -4046 toleransı, OKX sCode, çıkış yönleri (LONG→
  sell / SHORT→buy), kontrat dönüşümü, conditional stop gövdesi, geçerli
  cancel uçları, stop-failure→flatten, stop güncelleme + geri alma,
  mirror durum kalıcılığı, kapanışta stop temizliği, acil durum yön
  düzeltmesi + pozisyon başına hata izolasyonu, OKX kurtarma, backtest
  kayma/gecikme, flash crash (tek stop, panik yok), kısmi dolum→pozisyon.
- Ayrıca `test_live_sync.py`'ye filtre yuvarlama + minNotional testleri.
- 208 v1.2 testi hiç değişmeden aynen geçer.

## 5. Bilinçli olarak KAPSAM DIŞI bırakılanlar (gerekçeleriyle)

- **PostgreSQL/TimescaleDB/Redis:** tek süreçli bir bot için SQLite (WAL,
  600 yetkili dosya, yedekleme + mirror_state) yeterli ve paketin
  "sıfırdan yazım yok" ilkesine uyar. Çok süreçli/çok makinalı mimariye
  geçilirse ilişkisel DB katmanı ayrı bir v4 konusudur.
- **ELK/Grafana/Prometheus sunucusu:** Prometheus METİN formatı sayaçlar
  zaten mevcut (`monitor/report.py render_prometheus`); merkezi log
  altyapısı kurulum bağımlı bir operasyon tercihidir, pakete zorlanmaz.
  Log rotasyonu v3.0'da eklendi.
- **Vault/AWS Secrets Manager:** `*_FILE` deseni standart secret-mount
  yollarını kapsar; bulut sağlayıcı bağlantısı kullanıcı ortamına bırakılır.
- **News guard canlı senaryo testi:** `test_news_guard.py` mevcut ve
  geçerli; "haber anı canlı testi" gerçek veri/haber servis koşulu gerektirir
  (bu sandbox'ta haber servisi 429 döndü — bot fail-open devam etti;
  davranış tasarım gereğidir).

## 6. Gerçek veriyle backtest kanıtı

`docs/backtest_gercek_veri.json` — OKX BTC-USDT-SWAP, 2000 adet 5m kapanmış
mum (~7 gün, 2026-10-31 → 2026-11-07):

- **8 işlem** (trend 7, fade 1), kısmi dolum 4, dolmayan emir 1
- Red dağılımı gerçekçi: dusuk_hacim 1531, fade_kosulu_yok 170,
  guclu_trend_fade_kapali 79, rejim_uyumsuz 30, ... (571/571 tek kod DEĞİL)
- Monte Carlo: ruin %0.0; zarar olasılığı %92.3 (kısa örneklem —
  **kârlılık iddiası YOK**; strateji davranışı gözlemlenebilir hâldedir)

Komut: `python -m app.main --mode backtest --data-dir data --symbols BTCUSDT`

## 7. Sürüm

- `app.__version__` = **3.0-final**
- Zip: `ACARBOT_FINAL_v3.0.zip` (bağımsız ortamda 326/326 tekrar doğrulandı)
