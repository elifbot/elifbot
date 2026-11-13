# ACARBOT V20 (acarbot-v20 5.0.0) — 1 SAATLİK PAPER TEST · KAPSAMLI ANALİZ RAPORU

**Rapor tarihi:** 10 Kasım 2026
**Test başlangıç (UTC):** 21:12:18 — **Test bitiş (UTC):** 22:14:2x
**Süre:** raporlanan 3.728 saniye (62 dk 8 sn) · duvar saati 3.746 saniye (62 dk 26 sn)
**Mod:** PAPER (gerçek emir YOK, borsaya emir gönderilmedi) + **gerçekleşen simüle kâr/zarar motoru (bu test için tarafımca eklendi)**
**Borsalar:** BINANCE (public www veri rotası) + OKX
**Min skor eşiği:** 0.30 · **Referans sermaye:** 1.000 USD / borsa
**Durum:** ✅ Test kesintisiz tamamlandı — çıkış kodu 0, **0 hata**, **0 kopma**, **0 yeniden başlatma**

---

## 1. YÖNETİCİ ÖZETİ (Executive Summary)

| # | Bulgu | Değer |
|---|-------|-------|
| 1 | Test hedefine ulaşıldı mı? | ✅ Evet — 1 saat kesintisiz koştu, çıkış kodu 0 |
| 2 | Hata / exception | **0** |
| 3 | Taranan evren (döngü başına) | 1.288 sembol keşfedildi, ~711 detaylı tarandı |
| 4 | Toplam detaylı anlık görüntü (snapshot) | **4.980** |
| 5 | Üretilen sinyal (tekrarlı) | **421** |
| 6 | Benzersiz sinyal | **130** |
| 7 | Açılan paper pozisyon | **38** (BINANCE 19 + OKX 19) |
| 8 | Reddedilen sinyal | **92** (%54 marj limiti, %46 korelasyon limiti) |
| 9 | **Kapanan pozisyon** | **0** — hiçbir stop/hedef/zaman çıkışı tetiklenmedi |
| 10 | **Gerçekleşen (realize) P&L** | **0,00 USD** (kapanma olmadığı için) |
| 11 | **Açık (unrealized) P&L** | **+15,70 USD** → 2.000 USD üzerinden **%+0,785** |
| 12 | BINANCE sonuç | 981,49 USD (**−1,85 %**) |
| 13 | OKX sonuç | 1.034,20 USD (**+3,42 %**) |
| 14 | Açık pozisyonlarda kârda olan | **25 / 38 (%65,8)** |
| 15 | Gözlenen en yüksek skor | **0,647** — **0,72 eşiğini hiçbir anlık görüntü geçemedi** |
| 16 | 0,70–0,80 bandındaki anlık görüntü sayısı | **0** (4.980 içinde) |

**Net kanaat:** AcarBot V20, 1 saatlik paper testte **yazılımsal olarak kusursuz çalıştı** (sıfır hata, sıfır kopma, tam veri akışı). Sinyal üretimi, evren taraması, risk kapıları ve pozisyon açma zinciri **uçtan uca çalışıyor**. Ancak **kâr/zarar üretme yeteneği bu testte ölçülemedi**: pozisyonlar açıldı ama 1 saatlik pencerede hiçbiri kapanmadı. Bunun nedeni bir hata değil, **parametre yapısıdır** (stop %3,94 → 1 saatte ulaşılamayacak kadar uzak; maksimum tutuş süresi 24 saat). Bu rapor, bunu ve beraberinde bulunan **7 kritik iyileştirme noktasını** ayrıntılı olarak belgeliyor.

---

## 2. TEST TANIMI VE KAPSAM

### 2.1 Ne test edildi

Kullanıcı talebi: *"drive son yüklediğim acarbot v20 var onu al test et 1 saatlik sonra sonuçlarını bana mail ile gönder raporu çok detaylı analiz olsun her noktasına kadar istiyorum. testi takip et kopma olursa düzelt devam ettir. raporda bildir"* + *"paper mod olacak ama sinyal gelirse pozisyon alacak kapatacak kâr zarar edecek ne olacaksa olsun yani"*

Buna göre test şunları kapsar:

1. Drive'dan **en son yüklenen** V20 paketinin indirilmesi ve doğrulanması
2. Paketin kendi birim testlerinin koşulması (34 test)
3. **1 saat boyunca kesintisiz canlı paper koşu** — gerçek piyasa verisi, simüle emir
4. Pozisyonların **açılması, işaretlenmesi (mark-to-market) ve kapatılması**, kâr/zarar üretmesi
5. Kesintisiz canlı takip paneli
6. Kopma olması hâlinde düzeltilip devam ettirilmesi
7. Bu kapsamlı raporun **e-posta ile gönderilmesi**

### 2.2 Test edilemeyenler ( dürüstlük sınırı)

| Konu | Neden test edilemedi |
|------|----------------------|
| Gerçek emir gönderimi (live order) | Ortamda **hiçbir API anahtarı yok** (`.env` dosyası mevcut değil, yalnızca `.env.example`) |
| Emir reddi / borsa hata kodları (tdMode, postOnly) | Gerçek emir gerektirir — yalnızca kaynak kod incelemesiyle tespit edildi (bkz. Bölüm 10) |
| Günlük/haftalık kayıp "kill switch"i | Tetiklenmesi için realize zarar gerekir; bu testte realize P&L = 0 |
| Uzun vadeli performans (win rate, expectancy) | İstatistiksel anlamlılık için en az yüzlerce kapanmış işlem gerekir; bu testte kapanan işlem = 0 |

---

## 3. ORTAM, KISITLAR VE TEST SIRASINDA YAPILAN MÜDAHALELER

> Kullanıcı talebi gereği ("kopma olursa düzelt devam ettir, raporda bildir"), testi çalıştırabilmek için yapılan **tüm müdahaleler** burada açıkça belgelenmiştir.

### 3.1 ⚠️ MÜDAHALE 1 (EN KRİTİK): Paper modunda kâr/zarar üretilmiyordu

**Tespit:** V20 paketindeki `phoenix/live.py` içindeki `PaperExecution` sınıfı (satır ~58–120) **yarım kalmış bir iskeletti**. Paket, `--paper` modunda pozisyonu "açıp" (`PAPER_FILLED`) bir kenara koyuyor, sonra:

- pozisyonu **asla işaretlemiyor** (mark-to-market yok → unrealized P&L yok),
- **asla kapatmıyor** (stop / hedef / süre çıkışı yok → realize P&L yok),
- komisyon, slipaj, sözleşme büyüklüğü (contract size) hiç hesaba katılmıyor,
- rapora **sabit 1000.0** yazıyordu — yani paper modu aslında bir **telemetri sayacıydı**, ticaret simülasyonu değildi.

Bu hâliyle kullanıcının istediği *"pozisyon alacak kapatacak kâr zarar edecek"* davranışı **imkânsızdı**.

**Çözüm (paket kaynak koduna DOKUNULMADAN):** Paket dosyaları değiştirilmedi; bunun yerine **çalışma zamanında devreye giren bir yama modülü** yazıldı. Böylece paketin 34 birim testi ve orijinal dosyaları bozulmadan korundu.

- `/home/user/test_reports/acarbot_paper_pnl.py` — `apply_patches()` fonksiyonu; `PaperExecution.__init__/submit/report` ve `LiveSignalRunner.snapshot_with_reason` metotlarını çalışma zamanında değiştirir.
- `/home/user/test_reports/run_paper_1h.py` — yamayı uygular, ardından `phoenix.live.main()` çağırır.

**Yamanın eklediği gerçek ticaret mantığı:**

| Özellik | Açıklama |
|---------|----------|
| Mark-to-market | Her döngüde her açık pozisyon son fiyatla yeniden değerlenir → **canlı unrealized P&L** |
| STOP çıkışı | Fiyat stop seviyesine dokunursa pozisyon kapanır (muhafazakâr: stop ve hedef aynı bar/anda kesişirse **stop kazanır**) |
| TARGET çıkışı | Hedef seviyeye dokunulursa kapanır |
| TIME çıkışı | `max_hold_bars × 15 dk` süre aşılırsa kapanır (V20 varsayılanı 96 bar = **24 saat**) |
| Komisyon + slipaj | Giriş ve çıkışta `fee_bps_per_side` + `slippage_bps_reserve` uygulanır |
| Contract size | Sözleşme büyüklüğü doğru çevrilerek USD P&L hesaplanır |
| Equity eğrisi, tepe equity, maksimum düşüş (drawdown) | Hesaplanır |
| Kazanma/kaybetme, isabet oranı, beklenti (expectancy), çıkış nedeni sayaçları | Hesaplanır |
| **Risk motoru entegrasyonu** | Gerçekleşen günlük/haftalık zarar artık `RiskManager.can_enter`'a besleniyor → **kill switch'ler paper modunda da çalışır** |

**Doğrulama:** 60 saniyelik bir duman testi (smoke test) koşuldu → çıkış 0, 1 döngü, 80 anlık görüntü, 2 sinyal (OKX ICP LONG 0.304, BINANCE AMD LONG 0.315), **2 PAPER_FILLED**, 0 hata, `paper_*` alanları rapora yazıldı.

### 3.2 MÜDAHALE 2: Binance API erişimi (HTTP 451)

Bu sandbox ortamından `api.binance.com`, `fapi.binance.com`, `testnet.binance.vision` ve `demo-fapi.binance.com` adreslerinin **tamamı HTTP 451** döndürüyor; `fapi.binance.vision` ise DNS hatası veriyor. Erişilebilen tek üretim veri yolu `https://www.binance.com/fapi/v1/` oldu.

**Çözüm:** Koşuya `PHOENIX_BINANCE_PUBLIC_WWW=1` çevre değişkeni verilerek bu rota etkinleştirildi. Bu sayede BINANCE **bu testte gerçekten taranabildi** (döngü başına ~533 sembol; v15_1 testinde bu sayı ~176 idi).

### 3.3 MÜDAHALE 3: `.env` dosyası ve `.bat` başlatıcıları

Pakette `.env` yok (yalnızca `.env.example`). Paketin kendi `.bat` başlatıcıları `.env` olmadan sert hata veriyor.

**Çözüm:** Gerekli ayarlar koşu betiğine satır içi çevre değişkeni olarak yazıldı. **Hiçbir gizli anahtar dosyaya yazılmadı** (zaten mevcut değil).

### 3.4 MÜDAHALE 4: Kesintisizlik (restart-resilient) koşu betiği

Kullanıcı "kopma olursa düzelt devam ettir" dediği için koşu, tek bir Python süreci olarak değil, **süpervizör döngüsü** olarak kurgulandı: `/home/user/test_reports/run_v20_1h.sh`

- Başlangıç zamanını `run_v20_start` dosyasına yazar (süreç ölse bile süre korunur),
- kalan süreyi hesaplayıp `python3 -u -m run_paper_1h --duration <kalan> --poll 15 --paper` çağırır,
- süreç düşerse **kalan süreyle yeniden başlatır**,
- 3.600 saniye dolana veya temiz çıkış (rc=0) olana kadar döner.

### 3.5 MÜDAHALE 5: Canlı takip paneli

Kullanıcı "paneli de aç anlık takip et kopma olmasın" dediği için `0.0.0.0:8000` üzerinde canlı panel açık tutuldu (`/home/user/phoenix_dashboard/server.py`): AcarBot V20 · 1 saatlik PAPER test · min_score=0.30 · canlı döngü/sinyal/P&L göstergeleri.

### 3.6 ⚠️ KOPMA / KESİNTİ RAPORU

| Kontrol | Sonuç |
|---------|-------|
| Süreç düşmesi / yeniden başlatma | **0 kez** — supervizör döngüsü hiç devreye girmedi |
| Ağ hatası / exception | **0** (`errors: 0`) |
| Düşürülen anlık görüntü | **2** adet (`market_data_stale` — eski veri, normal ve beklenen) |
| Sonuç | **Test ilk denemede, tek parça hâlinde, kesintisiz tamamlandı.** |

---

## 4. ZAMAN ÇİZELGESİ (7 DÖNGÜ)

| Döngü | Başlangıç (UTC) | Döngü süresi | Taranan (detaylı) | BINANCE / OKX |
|-------|-----------------|--------------|-------------------|---------------|
| 1 | 21:12:18 | ~8 dk 37 sn | 705 | ~533 / ~176 |
| 2 | 21:20:55 | ~8 dk 46 sn | 709 | ~533 / ~176 |
| 3 | 21:29:41 | ~8 dk 49 sn | 711 | ~533 / ~178 |
| 4 | 21:38:30 | ~9 dk 10 sn | 711 | ~532 / ~179 |
| 5 | 21:47:40 | ~8 dk 57 sn | 709 | ~536 / ~173 |
| 6 | 21:56:37 | ~9 dk 12 sn | 716 | ~536 / ~180 |
| 7 | 22:05:49 | ~8 dk 35 sn | 716 | ~536 / ~180 |
| **TOPLAM** | 62 dk | **~8 dk 50 sn / döngü** | **4.980** | **BINANCE ~3.740 / OKX ~1.242** |

**Not:** Son döngü 3.600 saniye sınırını ~2 dakika aşarak tamamlandı (motor süreyi yalnızca döngü başında kontrol ediyor). Raporlanan süre 3.728 sn, duvar saati 3.746 sn. Bu, hedeflenen 1 saatin **%103,6**'sı — hedefe ulaşıldı.

---

## 5. TARAMA VE VERİ KALİTESİ

| Metrik | Değer |
|--------|-------|
| Keşfedilen evren | **1.288** sembol (her döngüde sabit) |
| Döngü başına detaylı taranan | ~711 (%55'i) |
| Toplam taranan | **4.982** |
| Toplam detaylı anlık görüntü | **4.980** |
| Düşürülen (eski veri) | **2** (`market_data_stale`) → **%0,04 kayıp** |
| Hata | **0** |

### 5.1 Strateji ön elemesinde (pre-filter) reddedilenler

| Red nedeni | Adet | Oran | Yorum |
|------------|------|------|-------|
| `below_min_score` (skor < 0.30) | **4.375** | %87,9 | Normal — eşiğin doğal sonucu |
| `stale_book` (bayat emir defteri) | **117** | %2,35 | Veri tazeliği kontrolü çalışıyor |
| `wide_spread` (geniş makas) | **67** | %1,35 | Likidite filtresi çalışıyor |
| **Geçen (sinyal)** | **421** | %8,45 | ✅ |

**Yorum:** Veri kalitesi filtreleri (`stale_book`, `wide_spread`) **gerçekten devrede ve çalışıyor** — bu, kötü fiyattan işlem açılmasını engelleyen sağlıklı bir davranış. Toplam 4.559 anlık görüntü bu iki filtreyle elendi.

---

## 6. SİNYAL ÜRETİMİ ANALİZİ

### 6.1 Sinyal sayıları

| Metrik | Değer |
|--------|-------|
| Toplam sinyal (tekrarlı) | **421** |
| Benzersiz sinyal (sembol+yön) | **130** |
| BINANCE | **268** (%63,7) |
| OKX | **153** (%36,3) |
| **LONG** | **341** (%81,0) |
| **SHORT** | **80** (%19,0) |

⚠️ **Dikkat çeken bulgu — yön yanlılığı:** Sinyallerin **%81'i LONG**. Bu, testin yapıldığı saatlerde piyasanın genel eğiliminden kaynaklanabileceği gibi, **stratejinin yön taramasında yapısal bir LONG yanlılığı** olabileceğini de gösterir. 1 saatlik tek bir örneklemle kesin yargıya varılamaz; ancak **düşüş trendinde botun aynı yoğunlukta SHORT üretip üretmediği mutlaka uzun süreli testte doğrulanmalıdır.**

### 6.2 Skor dağılımı (4.980 anlık görüntü)

| Skor bandı | Adet | Oran |
|-----------|------|------|
| −0.60 … 0.00 | (dahil) | — |
| 0.0 – 0.1 | **2.334** | %46,9 |
| 0.1 – 0.2 | **1.350** | %27,1 |
| 0.2 – 0.3 | **691** | %13,9 |
| 0.3 – 0.4 | **295** | %5,9 |
| 0.4 – 0.5 | **94** | %1,9 |
| 0.5 – 0.6 | **30** | %0,60 |
| **0.6 – 0.7** | **2** | **%0,04** |
| 0.7 – 0.8 | **0** | **%0,00** |
| 0.8 – 1.0 | **0** | **%0,00** |

**İstatistikler:** min **−0,532** · max **+0,647** · ortalama **+0,0597**

### 6.3 ⭐ "0.72 eşiği" iddiasının AMPİRİK DOĞRULAMASI

Önceki analizimizde, 0.72 eşiğinin pratikte hiç sinyal üretmediği tespit edilmişti. **Bu 1 saatlik test bunu kesin olarak doğruladı:**

- 4.980 gerçek anlık görüntü, 1.288 sembol, 2 borsa, 62 dakika boyunca tarandı.
- **Gözlemlenen en yüksek skor: 0,647.**
- 0.70–0.80 bandında **0** anlık görüntü.
- 0.60–0.70 bandında yalnızca **2** anlık görüntü (%0,04).

**Sonuç:** 0.72 eşiğinde bu test **tek bir sinyal bile üretmezdi** (0 sinyal, 0 pozisyon, 0 P&L). V20'nin 0.30'a çekilmesi doğru bir karar; 0.72 yapılandırması **fiilen çalışmayan bir bot** üretiyordu. Bu, 4.980 gerçek veri noktasıyla kanıtlanmıştır.

**Ancak ters yönde bir uyarı:** 0.30 eşiği 4.980 taramanın **%8,45'ini** (421 sinyal) geçiriyor. Bu kadar yüksek bir geçiş oranı, sinyal kalitesinin seyrelmesi riskini taşır. 0.30 ile 0.72 arasında (ör. 0.40–0.50) bir optimum aranmalıdır: 0.40 bandı 94+30+2 = **126 sinyal**, 0.50 bandı 30+2 = **32 sinyal** üretirdi.

---

## 7. SİNYAL → EMİR KAPISI (EXECUTION GATE) ANALİZİ

130 benzersiz sinyalin tamamı risk/uygulama kapısına girdi:

| Sonuç | Adet | Oran |
|-------|------|------|
| ✅ **PAPER_FILLED** (pozisyon açıldı) | **38** | **%29,2** |
| ❌ **REJECTED** | **92** | **%70,8** |

### 7.1 Ret nedenleri (92 ret)

| Ret nedeni | Adet | Oran |
|-----------|------|------|
| `reserved_margin_cap:1000.00>950.00` | **50** | %54,3 |
| `correlation_limit` | **42** | %45,7 |

#### (a) Marj limiti doygunluğu — **KRİTİK BULGU**

Her borsada 19 pozisyon × 50 USD marj = **950 USD**, referans sermayenin (1.000 USD) **%95'i** olan `max_reserved_margin_pct` sınırına dayanıyor. Yani:

> **Bot, her iki borsada da 19. pozisyondan sonra fiilen kilitlendi.** 20. pozisyon için gereken 50 USD'lik marj, 950 USD'lik tavan nedeniyle hiçbir zaman onaylanmadı ve sonraki **50 sinyal otomatik olarak reddedildi.**

Bu, testin ikinci yarısındaki sinyallerin neredeyse tamamının "boşa gittiği" anlamına gelir. 1.000 USD gibi küçük bir referans sermayeyle 20 eşzamanlı pozisyon hedefi **matematiksel olarak tutarsızdır**: 20 × 50 = 1.000 USD = sermayenin %100'ü, oysa tavan %95.

**Öneri:** Ya `max_positions` 20'den **19'a** (veya daha aşağıya) çekilmeli, ya marj/trade 50'den **45'e** düşürülmeli, ya da `max_reserved_margin_pct` %95'ten **%100'e** (riskli) alınmalıdır. En güvenlisi: **marj/trade = 45 USD ve max_positions = 20** → 900 USD (%90) kullanım, 100 USD tampon kalır.

#### (b) Korelasyon limiti — **YANLIŞ POZİTİF BULGUSU**

42 korelasyon reddinin **6'sı TERS YÖNLÜ (negatif korelasyonlu) çiftler** yüzünden gerçekleşti. Örnekler:

```
correlation_limit:AMZN/USDT:USDT:-0.999
correlation_limit:TSM/USDT:USDT:-0.999
correlation_limit:RKLB/USDT:USDT:-0.988
correlation_limit:RKLB/USDT:USDT:-0.983
correlation_limit:ICP/USDT:USDT:-0.854
correlation_limit:UVXY/USDT:USDT:-0.893
```

Portföy kodu `abs(korelasyon) > 0.85` kontrolü yapıyor. Ancak **korelasyon −0.999 olan iki pozisyon aynı yöne gitmez; biri yükselirken diğeri düşer.** Ters korele bir çift aslında **riski azaltır (hedge)**, artırmaz. Bu 6 ret, korunması gereken çeşitlendirmeyi **gereksiz yere engelleyen mantık hatasıdır**.

**Öneri:** Korelasyon kontrolü yalnızca **pozitif** korelasyon için uygulanmalı (`corr > 0.85`), negatif korelasyon ya serbest bırakılmalı ya da ayrı bir (daha yüksek) eşikle değerlendirilmelidir.

**Korelasyon reddi alan başlıca semboller:** ICP (9), TSM (6), RKLB (6), AVGO (6), AMZN (3), UVXY, WDC, HYPER, PLTR, APP, MRNA, OPENAI, BTC

---

## 8. POZİSYON VE KÂR/ZARAR ANALİZİ

### 8.1 Genel tablo

| Metrik | BINANCE | OKX | **TOPLAM** |
|--------|---------|-----|-----------|
| Başlangıç sermayesi | 1.000,00 | 1.000,00 | **2.000,00** |
| Açılan pozisyon | 19 | 19 | **38** |
| **Kapanan pozisyon** | **0** | **0** | **0** |
| Realize P&L | 0,00 | 0,00 | **0,00** |
| Ödenen komisyon + slipaj | 0,00 | 0,00 | **0,00** |
| **Açık (unrealized) P&L** | **−18,51** | **+34,20** | **+15,70** |
| **Toplam equity** | **981,49** | **1.034,20** | **2.015,70** |
| **Getiri** | **−1,85 %** | **+3,42 %** | **+0,785 %** |
| Kârda olan açık pozisyon | 11 / 19 | 14 / 19 | **25 / 38 (%65,8)** |
| Zararda olan açık pozisyon | 8 / 19 | 5 / 19 | **13 / 38 (%34,2)** |
| Tepe equity | 1.000,00 | 1.000,00 | — |
| Maksimum düşüş | %0,00 | %0,00 | — |
| İsabet oranı / beklenti | tanımsız (kapanan işlem yok) | tanımsız | **tanımsız** |

**Önemli uyarı:** realize P&L = 0 ve komisyon = 0 olması bir **hata değildir**; komisyon ve slipaj yalnızca **kapanışta** realize edilir. 38 pozisyonun tamamı hâlâ açık olduğu için masraf daha sonra düşülecektir. Gerçek komisyon yükü tahmini: 38 pozisyon × (giriş+çıkış) × 500 USD × 5,5 bps ≈ **2 × 38 × 0,275 ≈ 20,9 USD** + slipaj rezervi ≈ **toplam ~32 USD** — yani mevcut +15,70 USD'lik açık kâr, **masraflar düştüğünde muhtemelen eksiye dönecektir.** Bu, küçük sermayede işlem başına **%1,6'lık (32/2000) toplam maliyet** anlamına gelir ve ciddi bir bulgudur.

### 8.2 Equity (sermaye) seyri — canlı takip kayıtları

Yama, equity eğrisini yalnızca kapanışlarda güncellediği için (0 kapanış → tek nokta), seyir **test sırasında periyodik olarak okunan kontrol noktalarından** yeniden oluşturulmuştur:

| Zaman (UTC) | BINANCE unrealized | OKX unrealized | **TOPLAM** |
|-------------|--------------------|----------------|-----------|
| 21:29 (döngü 3) | +10,15 | −12,79 | **−2,64** |
| 21:47 (döngü 4) | +4,96 | +8,30 | **+13,26** |
| 21:56 (döngü 5) | −0,28 | +28,56 | **+28,28** |
| 22:05 (döngü 6) | +1,96 | +24,25 | **+26,21** |
| **22:14 (FİNAL)** | **−18,51** | **+34,20** | **+15,70** |

**Yorum:** Toplam açık kâr +28,28 USD'ye kadar çıktı, sonra **son 9 dakikada 12,5 USD eridi**. Bu erimenin kaynağı net: BINANCE tarafında `H/USDT SHORT` (−11,71), `ICNT/USDT SHORT` (−7,02) ve `OPENAI/USDT SHORT` (−5,29). **Üç SHORT pozisyon yükselen piyasada toplam −24 USD zarar yazdı** ve BINANCE bacağını eksiye çevirdi. Açık pozisyonların %65,8'i kârda olmasına rağmen, **zararların boyutu kazançların boyutundan büyük** — bu, stop mesafesinin kazanç tarafında daha uzak olmasının (R:R 2.2) doğal sonucudur ama aynı zamanda **küçük sayıda büyük zararın portföyü sürüklediğini** gösterir.

### 8.3 Stop / hedef yapısı — **KRİTİK BULGU**

Tüm 38 pozisyonda:

| Parametre | Değer |
|-----------|-------|
| Stop mesafesi | **tam olarak %3,94** (hepsinde aynı, min = max = %3,94) |
| Hedef mesafesi | **tam olarak %8,67** (hepsinde aynı) |
| Risk/Ödül (R:R) | **2,20** |
| Risk bütçesi | 20 USD (500 USD notyonel üzerinden %4,0; 50 USD marjın %40'ı) |
| Ortalama tutuş süresi | 3.414 sn (~57 dk) |
| Maksimum tutuş | 96 bar × 15 dk = **24 saat** |

Stop fiyatı, `RiskManager.stop_price()` içinde **sabit bir USD risk bütçesinden** (max_loss_usd = 20) türetiliyor: `distance = budget / (qty × contract_size × cost_factor)`. Yani stop, **sembolün oynaklığına (ATR / volatilite) göre AYARLANMIYOR** — her sembolde aynı yüzde.

⚠️ **Bu, ciddi bir tasarım kusurudur:**

- **Yüksek oynaklıklı** altcoinlerde (ör. `H/USDT`, `BEAMX/USDT`, `FOGO/USDT`) %3,94'lük stop günlük gürültünün içinde kalır → **gereksiz yere stop-out** olur.
- **Düşük oynaklıklı** sembollerde (ör. `BTC/USDT`) %3,94 çok geniş kalır → hedefe ulaşmak neredeyse imkânsızlaşır, sermaye saatlerce bağlı kalır.

**Öneri:** Stop mesafesi **ATR tabanlı** hâle getirilmeli (ör. `max(1.5 × ATR%, 1.5%)` ve `min(..., 4%)` ile sınırlanmalı). ATR hesabı pakette zaten mevcut (`live.py` satır ~377: `atr = sum(tr[-14:]) / 14`), sadece sinyal/stop üretiminde kullanılmıyor.

### 8.4 Neden hiçbir pozisyon kapanmadı? (0 kapanışın açıklaması)

1. **STOP:** %3,94 uzaklıkta. 1 saatlik testte hiçbir sembol bu mesafeyi kat etmedi (gözlenen en büyük hareket: `H/USDT` −%2,34).
2. **HEDEF:** %8,67 uzaklıkta — 1 saatte gerçekçi değil.
3. **ZAMAN:** `max_hold_bars × 15 dk = 24 saat` — test 62 dakika sürdü, süre sınırına **ulaşılamadı**.

**Sonuç:** Bu bir **hata değil, parametre-zaman ölçek uyumsuzluğudur.** Botun tasarım ölçeği **günler/haftalar**, test penceresi ise **1 saat**. Kâr/zarar mekaniğinin gerçekten test edilebilmesi için:
- ya **en az 24–48 saat** koşulmalı (zaman çıkışlarını yakalamak için),
- ya da test modunda `max_hold_bars` geçici olarak düşürülmeli (ör. 4 bar = 1 saat) ve `max_loss_usd` küçültülerek (ör. 5 USD → stop %1) kapanışlar hızlandırılmalıdır.

### 8.5 ⚠️ KRİTİK: Aynı sembol iki borsada eşzamanlı açık

Testin sonunda **9 sembol, iki borsada aynı anda açıktı**:

| Sembol | BINANCE | OKX |
|--------|---------|-----|
| RKLB | ✅ LONG | ✅ LONG |
| AVGO | ✅ LONG | ✅ LONG |
| TSM | ✅ LONG | ✅ LONG |
| AMZN | ✅ LONG | ✅ LONG |
| WDC | ✅ LONG | ✅ LONG |
| QCOM | ✅ LONG | ✅ LONG |
| UVXY | ✅ SHORT | ✅ SHORT |
| APP | ✅ LONG | ✅ LONG |
| BTC | ✅ 2 farklı vade (261225 + 270326) | ✅ LONG |

Bu, **aynı piyasa riskinin iki kez alınması** demektir (fiilen 2× kaldıraç). Korelasyon kontrolü **yalnızca aynı borsa içinde** çalışıyor; borsalar arası çapraz kontrol **yok**. Gerçek parayla çalışırken bu, beklenmedik şekilde iki kat risk anlamına gelir.

**Öneri:** Korelasyon ve "aynı sembol" kontrolü **borsalar arası (global)** yapılmalı; ya aynı sembol ikinci borsada engellenmeli, ya da toplam risk bütçesi borsaya göre değil **sembol bazında** sınırlandırılmalıdır.

### 8.6 En çok kazandıran ve kaybettiren açık pozisyonlar

**En çok kazandıran 3:**
| Sembol | Borsa | Yön | Giriş | Son | Açık P&L |
|--------|-------|-----|-------|-----|----------|
| USELESS/USDT | OKX | LONG | 0,13951 | 0,14277 | **+11,68** |
| CORE/USDT | OKX | LONG | 0,01276 | 0,01297 | **+8,23** |
| SOXS/USDT | OKX | SHORT | 55,33 | 54,81 | **+4,70** |

**En çok kaybettiren 3:**
| Sembol | Borsa | Yön | Giriş | Son | Açık P&L |
|--------|-------|-----|-------|-----|----------|
| H/USDT | BINANCE | **SHORT** | 0,03459 | 0,03540 | **−11,71** |
| ICNT/USDT | BINANCE | **SHORT** | 0,28490 | 0,28890 | **−7,02** |
| OPENAI/USDT | BINANCE | **SHORT** | 1.223,52 | 1.236,47 | **−5,29** |

⚠️ **Çarpıcı bulgu:** En çok kaybettiren 3 pozisyonun **tamamı SHORT**. Buna karşılık SHORT sinyalleri toplam sinyallerin yalnızca %19'unu oluşturuyor. Bu, **SHORT sinyallerinin kalitesinin LONG'lara göre daha düşük olduğu** şüphesini güçlendiriyor. Uzun süreli testte LONG ve SHORT performansı **ayrı ayrı** ölçülmelidir.

### 8.7 Tüm 38 açık pozisyon (final envanter)

**BINANCE (19 pozisyon · toplam −18,51 USD)**

| Sembol | Yön | Giriş | Son | Adet | Stop | Hedef | Açık P&L | Tutuş |
|--------|-----|-------|-----|------|------|-------|----------|-------|
| RKLB/USDT | LONG | 62,19 | 61,90 | 8,04 | 59,74 | 67,58 | −2,33 | 60,7 dk |
| AVGO/USDT | LONG | 333,17 | 333,89 | 1,50 | 320,04 | 362,06 | +1,08 | 60,2 dk |
| TSM/USDT | LONG | 398,65 | 399,70 | 1,25 | 382,94 | 433,22 | +1,32 | 60,0 dk |
| AMZN/USDT | LONG | 270,93 | 271,70 | 1,85 | 260,25 | 294,42 | +1,42 | 59,9 dk |
| ICNT/USDT | SHORT | 0,2849 | 0,2889 | 1.755,00 | 0,2961 | 0,2602 | **−7,02** | 59,9 dk |
| OPENAI/USDT | SHORT | 1.223,52 | 1.236,47 | 0,41 | 1.271,75 | 1.117,42 | **−5,29** | 59,8 dk |
| WDC/USDT | LONG | 289,12 | 289,46 | 1,73 | 277,72 | 314,19 | +0,59 | 59,8 dk |
| MRNA/USDT | SHORT | 251,21 | 252,27 | 1,99 | 261,11 | 229,43 | −2,11 | 59,6 dk |
| BEAMX/USDT | LONG | 0,004451 | 0,004455 | 112.334,31 | 0,004276 | 0,004837 | +0,45 | 59,4 dk |
| DOS/USDT | SHORT | 0,1633 | 0,1643 | 3.061,85 | 0,1697 | 0,1491 | −3,06 | 59,3 dk |
| QCOM/USDT | LONG | 174,44 | 174,53 | 2,87 | 167,56 | 189,57 | +0,26 | 59,3 dk |
| UVXY/USDT | SHORT | 18,35 | 18,23 | 27,25 | 19,07 | 16,76 | +3,27 | 59,0 dk |
| H/USDT | SHORT | 0,03459 | 0,03540 | 14.455,04 | 0,035953 | 0,031591 | **−11,71** | 58,6 dk |
| APP/USDT | LONG | 395,19 | 396,62 | 1,27 | 379,61 | 429,46 | +1,81 | 58,5 dk |
| BTC/USDT-261225 | LONG | 74.516,1 | 74.400,5 | 0,0067 | 71.578,9 | 80.977,9 | −0,78 | 58,5 dk |
| BEAT/USDT | SHORT | 0,07514 | 0,07496 | 6.654,25 | 0,078102 | 0,068624 | +1,20 | 58,3 dk |
| FOGO/USDT | SHORT | 0,00188 | 0,001874 | 265.957,45 | 0,001954 | 0,001717 | +1,60 | 58,0 dk |
| BTC/USDT-270326 | LONG | 75.518,4 | 75.419,3 | 0,0066 | 72.541,7 | 82.067,1 | −0,66 | 57,9 dk |
| HYPER/USDT | SHORT | 0,04783 | 0,04769 | 10.453,69 | 0,049715 | 0,043682 | +1,46 | 57,4 dk |

**OKX (19 pozisyon · toplam +34,20 USD)**

| Sembol | Yön | Giriş | Son | Açık P&L | Tutuş |
|--------|-----|-------|-----|----------|-------|
| ICP/USDT | LONG | 2,441 | 2,461 | +4,10 | 61,4 dk |
| RKLB/USDT | LONG | 62,26 | 61,90 | −2,89 | 59,2 dk |
| TSM/USDT | LONG | 398,64 | 399,54 | +1,13 | 58,8 dk |
| AMZN/USDT | LONG | 270,97 | 271,67 | +1,29 | 57,2 dk |
| AVGO/USDT | LONG | 333,35 | 333,92 | +0,86 | 57,2 dk |
| WDC/USDT | LONG | 289,77 | 289,46 | −0,54 | 56,5 dk |
| QCOM/USDT | LONG | 174,39 | 174,48 | +0,26 | 56,0 dk |
| UVXY/USDT | SHORT | 18,32 | 18,22 | +2,73 | 55,9 dk |
| PLTR/USDT | LONG | 169,34 | 169,61 | +0,80 | 55,8 dk |
| CORE/USDT | LONG | 0,01276 | 0,01297 | **+8,23** | 55,8 dk |
| HPE/USDT | LONG | 48,16 | 48,01 | −1,56 | 54,7 dk |
| APP/USDT | LONG | 394,72 | 396,40 | +2,13 | 54,3 dk |
| USELESS/USDT | LONG | 0,13951 | 0,14277 | **+11,68** | 53,7 dk |
| ETH/USDT | LONG | 2.059,52 | 2.057,80 | −0,42 | 53,6 dk |
| SOXS/USDT | SHORT | 55,33 | 54,81 | **+4,70** | 52,3 dk |
| TQQQ/USDT | LONG | 56,83 | 57,04 | +1,85 | 52,2 dk |
| NG/USDT | LONG | 3,507 | 3,495 | −1,71 | 52,1 dk |
| SPY/USDT | LONG | 752,12 | 752,48 | +0,24 | 52,0 dk |
| MU/USDT | LONG | 724,94 | 726,87 | +1,33 | 51,9 dk |

*(Tüm pozisyonlar 500 USD notyonel / 50 USD marj / 10× kaldıraç ile açılmıştır.)*

---

## 9. RİSK MOTORU DEĞERLENDİRMESİ

| Risk kontrolü | Test sonucu | Değerlendirme |
|---------------|-------------|---------------|
| Rezerve marj tavanı (%95) | 50 ret | ✅ Çalışıyor ama **yanlış yapılandırılmış** (19. pozisyonda kilitleniyor) |
| Korelasyon limiti (0,85) | 42 ret | ⚠️ Çalışıyor ama **ters yönlü çiftleri de bloke ediyor** (6 yanlış pozitif) |
| Maksimum pozisyon (20) | 19'da durdu | ⚠️ Hedefe hiç ulaşılamadı (marj tavanı nedeniyle) |
| Veri tazeliği (`stale_book`) | 117 ret | ✅ Sağlıklı çalışıyor |
| Makas/likidite (`wide_spread`) | 67 ret | ✅ Sağlıklı çalışıyor |
| Günlük/haftalık kayıp kill switch | **test edilemedi** | Realize zarar oluşmadığı için tetiklenmedi — mantık artık besleniyor ama doğrulanamadı |
| Borsalar arası mükerrer risk | **YOK** | ❌ **Eksik** — 9 sembol iki borsada çift açıldı |
| Sözleşme büyüklüğü (contract size) | ✅ | Yama ile doğru uygulandı (`USELESS` 10× sözleşme doğru çevrildi) |

---

## 10. TESPİT EDİLEN KUSURLAR VE RİSKLER (ÖNCELİK SIRASIYLA)

### 🔴 P1 — KRİTİK

**1. Paper motoru kâr/zarar üretmiyordu (yarım kalmış iskelet)**
- **Etki:** Paper modu bir ticaret simülasyonu değil, sayısal bir sayaçtı. Kullanıcının istediği "pozisyon alsın, kapatsın, kâr/zarar etsin" davranışı pakette **yoktu**.
- **Durum:** Bu test için tarafımdan yazılan yama ile çözüldü (`acarbot_paper_pnl.py`). **Ancak bu yama test ortamına aittir, pakete dahil değildir.** Paketin kendi `phoenix/live.py` dosyası hâlâ eksiktir.
- **Aksiyon:** Yamanın mantığı **pakete kalıcı olarak işlenmeli** ve birim testleri yazılmalı.

**2. Marj tavanı doygunluğu — bot 19. pozisyonda kilitleniyor**
- 20 × 50 USD = 1.000 USD > %95 tavan (950 USD) → 20. pozisyon **asla** açılamaz, sonrasındaki her sinyal boşa gider (bu testte 50 ret).
- **Aksiyon:** `margin_per_trade` 45 USD'ye çekilmeli veya `max_positions` 19'a indirilmeli.

**3. Borsalar arası mükerrer pozisyon (riskin ikiye katlanması)**
- 9 sembol iki borsada aynı anda açık. Korelasyon kontrolü yalnızca borsa içi çalışıyor.
- **Aksiyon:** Global (borsalar arası) sembol/korelasyon kontrolü eklenmeli.

### 🟠 P2 — YÜKSEK

**4. Stop mesafesi oynaklığa göre ayarlanmıyor (sabit %3,94)**
- Her sembolde aynı yüzde; yüksek oynaklıklı coinlerde gereksiz stop-out, düşük oynaklıklıda hedefe ulaşamama riski.
- **Aksiyon:** ATR tabanlı stop (paketteki ATR hesabı zaten mevcut, kullanılmıyor).

**5. Korelasyon kontrolü ters yönlü (negatif) çiftleri de engelliyor**
- 6 ret, aslında riski azaltan hedge çiftlerini bloke etti.
- **Aksiyon:** `corr > 0.85` kullanılmalı; negatif korelasyon serbest bırakılmalı.

**6. İşlem maliyeti, küçük sermayede getiriyi yiyor**
- 38 pozisyonun giriş+çıkış maliyeti ≈ **32 USD** (2.000 USD üzerinden %1,6), mevcut açık kâr +15,70 USD'nin **iki katı**.
- **Aksiyon:** Ya işlem başına notyonel artırılmalı (maliyet oranı düşer), ya maker emirlerle komisyon düşürülmeli, ya da daha yüksek skor eşiğiyle işlem sayısı azaltılmalı.

### 🟡 P3 — ORTA

**7. Yön yanlılığı (sinyallerin %81'i LONG)**
- Düşüş piyasasında bot aynı yoğunlukta SHORT üretemeyebilir.
- En çok zarar eden 3 pozisyonun tamamı SHORT — SHORT kalitesi şüpheli.
- **Aksiyon:** LONG/SHORT performansı uzun testlerde ayrı ayrı raporlanmalı.

**8. Zaman ölçeği uyuşmazlığı (1 saatlik test ↔ 24 saatlik tutuş süresi)**
- Bu testte kapanış gözlenememesinin nedeni.
- **Aksiyon:** P&L doğrulaması için en az 24–48 saatlik koşu veya test profilinde kısaltılmış `max_hold_bars`.

**9. 0.30 eşiği çok gevşek olabilir**
- 4.980 taramanın %8,45'i sinyale dönüştü; 0.40–0.50 bandı kaliteyi artırabilir.
- **Aksiyon:** 0.30 / 0.40 / 0.50 eşikleriyle karşılaştırmalı (A/B) uzun test.

### ⚪ P4 — BİLGİ (önceki analizden taşındı, bu testte doğrulanamadı)

**10. Gerçek emir yolu (kod incelemesi bulgusu, anahtar olmadığı için test edilemedi)**
- **OKX:** `ccxt` OKX adaptörü giriş emirlerinde `tdMode` zorunlu kılıyor (varsayılan yok) → `tdMode` gönderilmezse emir reddedilir.
- **BINANCE:** Ask/bid fiyatlı `postOnly` giriş emri → `GTX` olarak gönderilir ve **garanti reddedilir** (maker olmayan fiyat).
- **Sözleşme yuvarlama:** Kontrat büyüklüğü yuvarlaması miktarı **sıfıra** düşürebilir.
- **Aksiyon:** Gerçek anahtarla, küçük tutarla, önce testnet/demo ortamında doğrulanmalı.

---

## 11. ÖNERİLEN AKSİYON LİSTESİ (sıralı)

| # | Aksiyon | Beklenen fayda |
|---|---------|----------------|
| 1 | Paper P&L yamasını **pakete kalıcı olarak işle** + birim testi | Paper modu gerçekten ticaret simülasyonu olur |
| 2 | `margin_per_trade`: 50 → **45 USD** (veya `max_positions`: 20 → 19) | Marj tavanı kilitlenmesi çözülür, ~50 ret/1saat önlenir |
| 3 | Korelasyon kontrolünü **global (borsalar arası)** yap + `corr > 0.85` (negatif serbest) | Çift risk ve 6 yanlış pozitif önlenir |
| 4 | Stop'u **ATR tabanlı** hâle getir | Stop-out kalitesi, sembol bazlı risk doğru ölçeklenir |
| 5 | **24–48 saatlik** doğrulama koşusu yap (veya test profilinde `max_hold_bars` = 4) | Gerçek win rate / expectancy / drawdown ölçülür |
| 6 | 0.30 / 0.40 / 0.50 eşiklerini **A/B karşılaştır** | Sinyal kalitesi/miktarı optimumu bulunur |
| 7 | LONG / SHORT performansını **ayrı raporla** | Yön yanlılığı ve SHORT kalitesi netleşir |
| 8 | Gerçek anahtarla **önce testnet/demo**, sonra çok küçük tutarla canlı doğrulama | OKX `tdMode` ve Binance `postOnly` reddi riskleri giderilir |

---

## 12. SONUÇ VE KANAAT

**Yazılım kalitesi — BAŞARILI:** AcarBot V20 (5.0.0), 1 saatlik kesintisiz paper testte **sıfır hata, sıfır kopma, sıfır yeniden başlatma** ile çalıştı. Keşif → tarama → skorlama → risk kapısı → pozisyon açma → işaretleme zincirinin **tamamı uçtan uca çalışıyor**. 34/34 birim testi geçiyor. Evren taraması (1.288 sembol), veri kalitesi filtreleri ve risk kontrolleri aktif ve işlevsel.

**Ticaret performansı — ÖLÇÜLEMEDİ:** 38 pozisyon açıldı, **hiçbiri kapanmadı**. Bunun nedeni botun bozuk olması değil, **tasarım ölçeğinin (24 saatlik tutuş, %3,94 stop) test penceresinden (1 saat) çok daha uzun olmasıdır**. Bu nedenle "kâr ediyor mu?" sorusuna bu test **cevap veremez**; verebileceği tek şey, portföyün 62 dakikada **%+0,785 (açık)** taşıdığı ve açık pozisyonların **%65,8'inin kârda** olduğudur.

**En önemli üç bulgu:**
1. **Paper modu pakette yarım kalmıştı** — kâr/zarar üretmiyordu; bu test için yamayla çalışır hâle getirildi ve pakete kalıcı işlenmesi gerekiyor.
2. **Bot her iki borsada da 19. pozisyonda marj tavanına çarpıp kilitleniyor** — 20. pozisyon matematiksel olarak asla açılamıyor ve sonraki 50 sinyal boşa gidiyor.
3. **9 sembol iki borsada eşzamanlı açıldı** — borsalar arası risk kontrolü yok, fiilen 2× kaldıraç.

**0.72 iddiası kesin olarak doğrulandı:** 4.980 gerçek anlık görüntüde gözlenen en yüksek skor **0,647**; 0.70 üzerinde **tek bir gözlem bile yok**. 0.72 eşiği botu fiilen çalışmaz hâle getiriyordu; 0.30'a çekilmesi doğru bir karardı — ancak 0.30 da fazla gevşek olabilir ve 0.40–0.50 bandı denenmelidir.

---

## EK A — TEST DOSYALARI VE KOMUTLAR

| Dosya | Açıklama |
|-------|----------|
| `/home/user/google_drive/ACARBOT_V20_FULL.zip` | Drive'dan indirilen paket (50.799 B, Drive ID `1t5XWJUWah1KOMCqTwau0bMcLUHLOnwoq`) |
| `/home/user/acarbot_v20/phoenix_v4_super_final_20_acarbot/` | Açılmış proje kökü |
| `/home/user/test_reports/acarbot_paper_pnl.py` | **Paper P&L yaması** (`apply_patches()`) — mark-to-market, stop/hedef/zaman çıkışı, komisyon, equity, drawdown |
| `/home/user/test_reports/run_paper_1h.py` | Yamayı uygulayıp `phoenix.live.main()` çağıran başlatıcı |
| `/home/user/test_reports/run_v20_1h.sh` | 3.600 sn'lik, yeniden başlatmaya dayanıklı süpervizör koşu betiği |
| `/home/user/test_reports/live_10min_report.json` | **Ham final rapor (tüm metrikler)** |
| `/home/user/test_reports/live_10min.log` | Koşu günlüğü (Cycle / PAPER_CLOSE satırları) |
| `/home/user/phoenix_dashboard/server.py` | Canlı takip paneli (0.0.0.0:8000) |

**Koşu komutu:**
```bash
cd /home/user/test_reports
bash run_v20_1h.sh
# içinde:
# PHOENIX_BINANCE_PUBLIC_WWW=1
# PYTHONPATH="$PKG:/home/user/test_reports"
# python3 -u -m run_paper_1h --duration <kalan> --poll 15 --detail-per-cycle 0 --paper \
#   --report /home/user/test_reports/live_10min_report.json
```

## EK B — HAM FİNAL METRİKLER (rapordan birebir)

```json
{
  "version": "5.0.0-acarbot-v20", "mode": "PAPER",
  "duration_sec": 3728, "cycles": 7,
  "universe_discovered": 1288, "universe_scanned_total": 4982,
  "detailed_snapshots": 4980, "signals_seen": 421, "unique_signals": 130, "errors": 0,
  "score_min": -0.5318, "score_max": 0.6470, "score_mean": 0.0597,
  "score_histogram": {"0.0-0.1":2334,"0.1-0.2":1350,"0.2-0.3":691,"0.3-0.4":295,
                      "0.4-0.5":94,"0.5-0.6":30,"0.6-0.7":2,"0.7-1.0":0},
  "strategy_rejections": {"below_min_score":4375,"stale_book":117,"wide_spread":67},
  "snapshot_dropped": {"market_data_stale": 2},
  "signals_by_exchange": {"BINANCE":268,"OKX":153},
  "signals_by_side": {"LONG":341,"SHORT":80},
  "paper_execution": {"PAPER_FILLED":38,"REJECTED":92,
                      "reserved_margin_cap":50,"correlation_limit":42}
}
```

**Kâr/Zarar özeti:**

```json
{
  "BINANCE": {"open":19,"closed":0,"realized":0.00,"unrealized":-18.51,
              "equity":981.49,"return_pct":-1.85,
              "rejections":{"margin_cap":44,"correlation":23}},
  "OKX":     {"open":19,"closed":0,"realized":0.00,"unrealized":+34.20,
              "equity":1034.20,"return_pct":+3.42,
              "rejections":{"margin_cap":6,"correlation":17}},
  "TOPLAM":  {"open":38,"closed":0,"unrealized":+15.70,
              "equity":2015.70,"return_pct":+0.785,
              "profitable_open":25,"losing_open":13}
}
```

---

*Bu rapor, 10 Kasım 2026 tarihinde gerçekleştirilen 1 saatlik kesintisiz paper testinin tüm verilerine dayanarak hazırlanmıştır. Tüm sayılar `live_10min_report.json` ham çıktısından alınmıştır.*
