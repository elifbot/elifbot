# ACARBOT v3.1 — Değişiklik Günlüğü (7 Kasım 2026)

Girdi: kullanıcı, bağımsız geliştiricinin hazırladığı `ACARBOT_FINAL_v1.7.zip`
paketini iletti ve şunu istedi: **"bu söyledikleri bu versiyonda var burada
olup bizim v3 de olmayanları alıp birleştirin."** Birleştirme hedefi, dış
sürümün v1.3-v1.7 hattındaki beş özellik idi: *scan-all, --motors, baz hacim
düzeltmesi, bayat sinyal koruması, CLI eşikleri*.

Yöntem: dış sürümün kodu dosya dosya inceledi; özellikler **dış koddan
kopyalanmadan**, v3.0 mimarisine (SignalPipeline tek boru hattı, v2 uzmanlar
+ Hakem, canlı eşleme yığını) **uyarlanarak** yazıldı. Tek kapı ilkesi:
canlı (Executor) ve backtest (BacktestEngine) AYNI pipeline'ı kullandığı
için motor/eşik kuralları tek yerde tanımlandı ve iki katmanda birden
geçerli oldu. Mevcut davranış korunmuştur: **208 v1.2 testi hiç
değişmeden aynen geçer**; toplam **389/389 test** (208 v1.2 + 118 v2/v3 +
63 v3.1).

---

## 1. Birleştirilen özellikler (dış v1.3 → v1.7)

### 1.1 CLI sinyal eşikleri (dış v1.3) — `--min-rvol`, `--fade-impulse`, `--spike-multiplier`

- Kod varsayılanları DEĞİŞMEDİ (RVOL 1.5 / impuls 0.35 / spike 3.0);
  bayrak verilmezse davranış birebir aynıdır.
- Başlangıç afişinde aktif eşikler loglanır; oturum JSON raporuna
  `signal_thresholds` alanı eklendi (motorlar dâhil).
- Doğrulama: pozitif değerler zorunlu (spike çarpanı > 1).
- Paper ve backtest modlarında geçerlidir (config tek yerden akar).

### 1.2 Motor seçimi (dış v1.4) — `--motors both|trend|fade`

- Kapalı motor **hiç DEĞERLENDİRİLMEZ**: kapı `SignalPipeline.evaluate`
  içine kondu (v1.4'ün executor+backtest çift kapısı yerine TEK kapı —
  v3.0 mimarisinde ikisi aynı pipeline'ı çağırdığı için kural otomatik
  olarak iki katmanda da geçerlidir; testle kilitli).
- Kapalı motor HOLD üretir ve red kodu TAŞIMAZ → açık motorun
  açıklayıcı red kodu görünür kalır (`rejim_uyumsuz` vb. korunur).
- Afişte ve raporda aktif motorlar görünür.
- Dış v1.4'ün backtest bulgusu bilgidir: örneklemde TREND-only +
  varsayılan eşikler en iyi sonuçtu (39/32 işlem, PF 1.55/2.20); FADE'i
  kapatmak isteyen için yol `--motors trend`'dir. Kâr garantisi değildir.

### 1.3 Tam pazar taraması (dış v1.5) — `--scan-all`, `--scan-cycle-seconds`

- **Evren keşfi:** `fetch_top_usdt_futures(10_000)` (v2.0'dan) tüm canlı
  USDT enstrümanlarını verir; `--scan-all` bunlardan **yalnız perpetual'ları**
  alır (Binance `PERPETUAL`/ayna `SPOT`; OKX `SWAP`; vadeli
  `CURRENT/NEXT_QUARTER` ve OKX `FUTURES` sözleşmeleri likidite/vade
  riskiyle düşürülür — `_scan_all_universe`). `--symbols` yok sayılır.
  Sıralama hacimseldir: en likit coinler önce taranır. Canlı ölçüm:
  **OKX 528 feed**.
- **Paralel mum taraması:** sembol başına görev yerine, borsa başına
  semaphore (Binance 10 / OKX 4) + **rate pacer** (Binance 25 istek/sn,
  OKX 8 istek/sn — borsa limitlerinin altında güvenli pay; 429 koruması).
- **Tek tüketici değerlendirme kuyruğu:** fetch'ler paralel, değerlendirme
  TEK kuyruk tüketicisiyle ANA event loop'ta sıralı çalışır → executor
  paylaşılan durumu ve SQLite için yarış koşulu yoktur (dış v1.6'nın
  "SQLite objects created in a thread" hatası bu mimaride zaten
  imkânsızdır; not belgelendi).
- **Aynı mum iki kez değerlendirilmez** (`last_closed` damgası); mum
  başına pozisyon yönetimi tekrarı da engellenir.
- **OKX WS parçalama:** 250+ enstrümanda akış 250'lik parçalara bölünür,
  ayrı bağlantılarda çalışır, kuyrukta birleşir; herhangi biri koparsa
  hata yukarı yayılır ve `stream_tickers_reconnecting` tüm parçaları
  yeniden kurar. (Binance zaten tek `!miniTicker@arr` tüm-pazar akışıdır.)
- **Sweep koruması isteğe bağlı kalır:** 1046 defteri sürekli çekmek rate
  limitlerine sığmaz → tam pazarda giriş adayı sembolün defteri sinyal
  ANINDA `executor.book_fetcher` ile tazelenir; dar listede eski toplu
  tarama aynen sürer.
- **Veri bütünlüğü ölçeklendi (`DataConfig.full_market`):** dar listede
  TÜM feed'lerin ısınması aranırken tam pazarda çoğunluk (≥%50, üst sınır
  50 feed) yeterlidir; bayatlık oranı yalnız **yerleşik** (yeterli tick
  almış) feed'lerde sayılır → işlem görmeyen düşük hacimli coinler güvenli
  modu tetiklemez. Sembol başı tazelik denetimi AYNEN korunur.
- **MTF/OI görevleri tam pazarda kapalıdır** (1000+ sembol × 3 TF + OI
  sorgusu rate limitlerine sığmaz): MTF için pipeline'ın 5m yeniden
  örnekleme yedeği kullanılır, order flow "uygulanmadı" raporlar.
  Açılışta açıkça loglanır.
- **Dead-man's switch kapsamı:** tam pazarda countdown 1000+ sembole
  gönderilmez (borsa hız limitini patlatır); kapsam = açık paper
  pozisyonları. Borsada yalnız bunların emirleri vardır (giriş emirleri
  dolumdan sonra gider) → kapsam tamdır, gerekçe kodda ve günlükte.
- **Rapor:** `scan_all`, `universe_sizes`, `symbols="ALL-USDT"` alanları.
- **Fail-closed:** evren keşfi başarısızsa oturum KALKMAZ (kısmi evrenle
  "tam pazar" iddiası yapılmaz), hata loglanıp çıkılır.

### 1.4 RVOL sahte-hacim düzeltmesi (dış v1.6) — baz hacim

- **Kök neden (dış sürümün kanıtlı bulgusu):** canlı spike dedektörü
  hacmi `quote = baz × fiyat` hesaplıyordu; fiyat oynadığında HİÇ İŞLEM
  OLMASA BİLE quote hacmi değişiyor → sahte hacim deltası → RVOL 100-500x
  şişiyor → gerçek sinyaller "şüpheli/veri hatası" diye engelleniyordu
  (MRNA, MINIMAX, ZRX, CRO, COIN vakaları).
- **Düzeltme:** `Ticker`'a `base_volume_24h` alanı eklendi
  (fiyattan bağımsız). Binance miniTicker `v` alanı, OKX `volCcy24h`
  doğrudan kullanılır (fiyatla ÇARPILMAZ). Executor spike dedektörüne
  **baz hacim deltası** verir; baz hacim yoksa eski quote yolu
  (geriye uyum). Tick-CVD de aynı doğru deltabeslenir.
- Sanity cap (RVOL > 100) hâlâ aktiftir — artık GERÇEK aşırı sapmaları
  yakalar, fiyat oynaklığını değil.

### 1.5 Bayat sinyal giriş koruması (dış v1.7)

- **Vaka (dış sürüm analizi):** sinyal ~4 dk önce kapanan 5m mumdan
  üretildi (FTT 0.2288); canlı fiyat 0.2306'ya çıkmıştı — stop seviyesi
  zaten piyasa fiyatının altındaydı (SHORT). Limit doldu, AYNI SANİYE
  stop-out (hold_ms=0, -4.44 USDT).
- **Düzeltme:** giriş emri verilmeden ÖNCE canlı fiyat kontrolü: canlı
  fiyat zaten stopun ötesindeyse (LONG: live ≤ stop, SHORT: live ≥ stop)
  giriş İPTAL edilir ("GİRİŞ İPTAL: bayat sinyal"), `last_block_reason`
  yazılır, sayaç artar. Canlı fiyat yoksa eski davranış (geriye uyum).
- **Panel:** Sistem sağlığı bölümüne "⏸ bayat sinyal iptali" sayacı;
  oturum raporuna `stale_entry_cancels`.
- Konum: plan kurulduktan HEMEN sonra (şok testi/portföy kontrolünden
  önce) — mahkûm plan için gereksiz değerlendirme yapılmaz.

## 2. v3.0'a özgü entegrasyon kararları (dış sürümde olmayanlar)

- Motor kapısı `SignalPipeline` içinde: `--motors` backtest'i de otomatik
  etkiler (v1.4 bunu ayrıca backtest engine'e yazmıştı; v3.0 mimarisinde
  gerek yoktur).
- Tam pazar taraması v2.0 boru hattıyla çalışır: 528+ sembolde her kapanış
  rejim → uzmanlar → Hakem → MTF (resampled) → skor ≥ 70 zincirinden geçer;
  evren listesi işlem kararı ÜRETMEZ.
- Evren keşfi için yeni modül eklenmedi: v2.0'dan `fetch_top_usdt_futures`
  (zaten hacimsel sıralı, adres çözümü yapar) yeniden kullanıldı; üstüne
  perpetual filtresi (`_scan_all_universe`) kondu.
- Paralel tarama dar listede de kullanılır (döngü hedefi 5 sn) — eski
  sıralı yenileme davranışının yerini hızlı ve rate-güvenli model aldı;
  208 v1.2 testi bu değişimden etkilenmedi (görev katmanı test kapsamı
  dışıdır, executor davranışı değişmedi).

## 3. Test paketi (389)

- Yeni `tests/test_v31_signal_cli.py` (7), `test_v31_motor_selection.py`
  (10), `test_v31_volume_fix.py` (11), `test_v31_stale_entry_guard.py` (6),
  `test_v31_scan_all.py` (29): CLI eşikleri + doğrulama, motor kapısı
  (pipeline + executor + resolver), baz hacim önceliği/geri dönüş (Ticker,
  Binance `v`, OKX `volCcy24h`), bayat giriş (SHORT/LONG, sınırda, iptal
  sayacı), evren keşfi (USDT/PERPETUAL/SWAP filtresi, hacimsel sıra,
  vadeli düşürme), book_fetcher sırası + hata toleransı, OKX WS parçalama
  (küçük/600/hata yayılımı), pacer aralığı, rapor alanları, tam pazar
  ısınma/bayatlık ölçeklemesi.
- **208 v1.2 testi hiç değişmeden aynen geçer**; 118 v2/v3 testi de aynen.

## 4. Canlı duman testi (bu paketle, gerçek veri)

```
TAM PAZAR TARAMASI: okx=528 | toplam 528 feed | döngü hedefi 90 sn
TAM TARAMA: 528 sembol, 66.0 sn (hedef 90 sn)   # iki tam döngü
ticks ~247.335 / 3 dk | 429 hatası: 0 | güvenli mod: hayır | hata: yok
rapor: scan_all=true, universe_sizes={okx:528}, symbols=ALL-USDT,
       signal_thresholds={... enabled_motors:["trend"]}
```

## 5. Bilinçli olarak KAPSAM DIŞI bırakılanlar

- **429 için ek geri çekilme (backoff) katmanı, borsa saat senkronu
  (zaman ofset kontrolü), Binance hedge mode (dual-side pozisyon):**
  dış geliştiricinin kendi yol haritasında da birleştirmeden SONRAKI adım
  olarak sıralanmıştır ve v1.7 paketinde kodları yoktur. v3.2 adayıdır.
  Not: tarama katmanındaki pacer (25/8 istek/sn) 429 önlemenin birinci
  hattıdır ve bu sürümde içeridedir.
- **PostgreSQL/TimescaleDB/Redis:** tek süreçli bot için SQLite (WAL)
  yeterlidir (v3.0'daki gerekçe aynen geçerli).

## 6. Kullanım

```bash
# TAM PAZAR: her iki borsadaki tüm USDT perpetual'lar (hacimsel sıra)
python -m app.main --mode paper --paper --exchange all --scan-all \
    --motors trend --profile apex --duration-minutes 60

# Gevşetilmiş eşiklerle dar liste
python -m app.main --mode paper --paper --exchange okx --symbols BTCUSDT \
    --motors trend --min-rvol 1.2 --fade-impulse 0.25 --spike-multiplier 2.5

# Tam pazar + testnet eşleme
python -m app.main --mode paper --paper --scan-all --live-testnet \
    --live-exchange okx --duration-minutes 60
```

Paket PAPER ONLY'dir; gerçek emir gönderilmez (testnet eşleme ayrıca ve
açıkça istenir).
