# Kripto Bot v9.4.1 — Nihai inceleme ve deney raporu

**GERÇEK PARA ONAYI YOK. Bu dosya bir araştırma adayının olumlu ve olumsuz kanıtlarını birlikte raporlar.**

**Önceden tanımlı araştırma kabul sonucu:** `RESEARCH_CRITERIA_FAILED_REAL_MONEY_REJECTED`. Kontrollerin tümü geçti mi: **False**.

## 1. Yönetici özeti

- Yeni aday: **378 işlem, -354.98 USDT net**, özsermaye maksimum düşüşü **359.68 USDT**; başlangıç tek kasa $1000.
- Aynı yeni saat/cüzdanda eski v9.3 kuralları: **789 işlem, -567.72 USDT net**. Yeni-eski fark **+212.74 USDT**.
- Paper aktif hedefi 900s; toplam 900.22s, drenaj 0.00s. Kapanmış net +0.0000, açık brüt +0.0000, özsermaye farkı +0.0000 USDT.
- Regresyon testleri: **78 passed in 9.76s**. Kaynak/veri bütünlüğü doğrulandı; 13 işlem/risk/çıkış/yönlendirme/replay dosyası önceki v9.4 donmasıyla byte-byte aynı.
- **Canlı doğrulama eksik/degrade:** sıfır emir/dolum; Binance aggTrade sayacı 0 ve 133 hata, BBO verisi var. Genel healthy=true yalnız kotasyon güncelliğini gösterdiğinden tam işlem akışı sağlığı onayı değildir. Emir-yürütme hattı bu koşuda canlı dolumla sınanmadı.
- Daha temiz mimari ve daha güvenilir ölçüm otomatik olarak pozitif beklenti sağlamaz. Negatif veya kabul dışı bir aday başarılı strateji olarak pazarlanmadı; test sonucu görüldükten sonra işlem parametresi değiştirilmedi.

## 2. Kullanıcının dört tablo incelemesi

Görsellerdeki altı kapının adetleri ve getirileri v9.3 kaydedilmiş JSON özetiyle birebir eşleşti. XLSX eki gelmedi; görseller ve kayıtlar karşılaştırıldı. Ayrıntı: `v941_user_tables_verified.json`.

- v9.3 kazanan %56.90; ortalama kazanan +1.12, kaybeden -3.26 USDT. Yaklaşık başa baş isabet %74.4; açık -17.5 **yüzde puan**. Yuvarlanan ortalamalardan tekrar hesaplanan beklenti hassas rapor değeriyle tam eşleşmeyebilir.
- Net -88.82 USDT, brüt -48.25 ve ücret 40.57. Brüt yürütme fiyatlarından gelir ve kaymayı içerir; yalnız komisyonun tek neden olmadığı nettir, fakat sıfır sürtünmeli sinyal alfası bu sütundan tek başına ölçülemez.
- Eski lider/genişlik ablasyonunda kapı kapatılınca CHOP/ATR filtresi geliyordu. Bu yüzden +25.71 USDT fark saf “kapıyı çıkar” etkisi değildi. Yeni MARKET ablasyonu başka kapı eklemez. Ortak upstream özellikleri nedeniyle yeni kollar da tam ortogonal nedensel deney değildir.
- “Benzersiz örnek” olgunlaşmış 15m n değildir. Eski rapor bu paydayı ve yön başına ileri getiriyi tutmadığından bunlar geriye dönük güvenilir biçimde doldurulamaz; CI uydurulmadı.
- “Kârlı sinyali engellemiş / doğru engellemiş” yerine **pozitif/negatif işaretli getiri ipucu** kullanılır. Bu bir dolum, stop-yolu net kârı veya nedensel kapı etkisi değildir.

### Maliyet aritmetiği (eski altı kapı; ileri getiri, işlem neti değil)

Round trip komisyon 7bps; 8bps/yön kayma toplam 16bps. Böylece **23bps, spread ve funding hariç**. Referans spread 1.5bps eklenirse 24.5bps.

| Eski kapı | Rapordaki benzersiz alan | Olgunlaşmış 15m n | İşaretli brüt bps | 23bps sonrası senaryo |
|---|---:|---|---:|---:|
| commission_viability | 6 | Bilinmiyor / kaydedilmedi | +45.10 | +22.10 |
| win_loss_shield | 36 | Bilinmiyor / kaydedilmedi | +44.03 | +21.03 |
| quant_rule_council | 63 | Bilinmiyor / kaydedilmedi | +18.55 | -4.45 |
| vwap_overextension_gate | 33 | Bilinmiyor / kaydedilmedi | +9.53 | -13.47 |
| ten_agent_mutual_audit | 47 | Bilinmiyor / kaydedilmedi | -8.55 | -31.55 |
| global_leader_breadth_gate | 60 | Bilinmiyor / kaydedilmedi | -64.18 | -87.18 |

+44/+45bps olan iki ortalama maliyeti aşabilir; bilinmeyen olgunlaşmış payda, seçim yanlılığı, stop yolu ve dolum yokluğu nedeniyle bunlardan da kapı kaldırma kararı çıkmaz.

## 3. On uzmanlık açısından tartışma ve uygulanan değişiklikler

On bağımsız yapay zekâ/LLM çalıştırıldığı iddia edilmez. Tek asistan veri, istatistik, sinyal, emir akışı, rejim, çıkış, risk, yürütme, muhasebe ve operasyon açısından karşı görüşlü denetim yaptı. Ayrıntılı itiraz/karar tablosu: `v94_on_uzman_inceleme_ve_kararlar.md`.

v9.4 geliştirmesinde: kapanmış mum değişmezliği; ortak kapalı-mum çekirdeği; eksiksiz HTF; gerçek taker verisi; sentetik spot BBOyu futures gibi kullanmama; ATR taktik stop ve R/ATR takip; toplam ve yönlü stop-risk bütçesi; tek $1000 kasa; sonraki açılış dolumu; giriş-bar stop; aynı barın sonraki çıkış gelirini önceki açılışta harcamama; funding/işlem neti uzlaştırması.

Bunlar doğruluk ve risk hipotezleridir, kanıtlanmış pozitif edge değildir. $50/10x sabit kalır. Stop-bazlı açık risk bütçesi toplam drawdown limiti değildir; tekrar eden küçük kayıplar birikebilir. Çok yakın stoplar maliyet/whipsaw sorununu büyütebilir.

### Önceden sınırlanan geliştirme adayları

| Aday | İşlem | Net USDT | Özsermaye DD |
|---|---:|---:|---:|
| A | 91 | -72.11 | 72.44 |
| B | 87 | -78.03 | 78.36 |

Seçilen A: yalnız geliştirme netine göre daha az kaybeden aday. Her iki aday negatif; eski v9.3 holdout artık geliştirme verisi ve yeniden OOS diye sunulmadı.

## 4. Test başlamadan dondurulan plan

- Donma (UTC): **2026-11-03T07:13:34Z**.
- Tarihsel test: **2026-10-13T11:25:00+00:00 — 2026-10-28T01:25:00+00:00**, 8 × 4200 test barı, öncesinde 600 ısınma barı.
- Eski görüntüyle en az bir günlük boşlukla ayrık tarihsel blok; geliştirme tarihinden ÖNCE yer alır. Bu nedenle tam bağımsız prospektif/kronolojik ileri-OOS veya rolling walk-forward değildir.
- Önceki v9.4.0 süreçleri kayboldu ve tamamlanmış sonuç kaydedilmedi; kesintili oturum başarılı test sayılmadı. Arşivde kod zipi, donma kaydı ve kısmi kayıtlar var.
- v9.4.1 kabul ölçütleri v9.3/kullanıcı incelemesinden etkilenmiştir. Önceki kesilmiş süreç bazı kaydedilmemiş hesaplar yapmış olabilir; tamamlanmış sonuç incelenip parametre ayarlaması yapılmadı. Doğrulayıcı bağımsız deney iddiası yoktur.
- Mühürlü veri SHA-256: `7fa2396ad91885fafd16781bbb8b2b596a6c19016c1bfcd55eed8285789041d2`.

### Sabit başarı ölçütleri

```json
{
  "min_matured_per_gate_side": 50,
  "min_distinct_symbols": 3,
  "min_distinct_utc_days": 10,
  "bootstrap_draws": 10000,
  "moving_block_days": 2,
  "familywise_alpha": 0.05,
  "predeclared_gate_side_hypotheses": 6,
  "stress_net_lower_bound_bps": 1.0,
  "base_roundtrip_fee_bps": 7.0,
  "base_slippage_bps_per_side": 3.0,
  "stress_slippage_bps_per_side": 8.0,
  "reference_spread_bps": 1.5,
  "candidate_min_closed_trades": 100,
  "candidate_max_equity_drawdown_usdt": 50.0,
  "candidate_required_stress_arms": [
    "slippage_8bps",
    "slippage_15bps",
    "extra_bar_delay"
  ],
  "real_money_approval": false
}
```

Araştırma adayı: en az 100 kapalı işlem; baz ve önceden seçilen bütün stres kollarında pozitif net; maksimum özsermaye DD ≤ $50; en az 10 UTC günlük bloktan ortalama günlük net için nominal %95 alt sınır > 0; funding verisi tam. Her durumda gerçek para için otomatik onay yok.

Kapı-yön için: en az 50 olgunlaşmış örnek, 3 sembol, 10 UTC günü. Olmazsa CI hesaplanmaz. Pozitif fırsat maliyeti bayrağı, stres sonrası çoklu-düzeltilmiş alt sınır > +1bps gerektirir; bu da otomatik kapı kaldırma kararı değildir.

## 5. Tarihsel doğrulama sonuçları

| Kol | İşlem | Brüt | Ücret | Funding maliyeti | Net USDT | Özsermaye DD |
|---|---:|---:|---:|---:|---:|---:|
| v94 | 378 | -222.65 | 132.30 | +0.04 | **-354.98** | 359.68 |
| v93_on_corrected_clock | 789 | -291.35 | 276.13 | +0.25 | **-567.72** | 582.62 |
| without_TREND | 814 | -451.76 | 284.89 | +0.32 | **-736.97** | 740.81 |
| without_FLOW | 570 | -302.02 | 199.48 | +0.09 | **-501.59** | 506.94 |
| without_MARKET | 378 | -222.65 | 132.30 | +0.04 | **-354.98** | 359.68 |
| without_ADAPTIVE_EXIT | 343 | -281.62 | 120.05 | +0.19 | **-401.86** | 405.97 |
| slippage_8bps | 368 | -391.67 | 128.80 | +0.02 | **-520.50** | 523.55 |
| slippage_15bps | 345 | -596.33 | 120.76 | +0.02 | **-717.11** | 717.58 |
| extra_bar_delay | 236 | -294.42 | 82.61 | +0.03 | **-377.06** | 377.70 |
| no_fee_no_slippage_funding_on | 389 | -86.21 | 0.00 | +0.04 | **-86.25** | 101.94 |

- v9.4.1 isabet %25.93; ortalama kazanan/kaybeden +2.48 / -2.14 USDT; işlem başına -0.94 USDT.
- Daha az toplam kayıp, daha güçlü edge demek değildir: yeni/eski işlem başına net -0.939 / -0.720 USDT; profit factor 0.407 / 0.532. İşlem adedi de çok farklıdır.
- Toplam net farkın muhasebe ayrışımı: brüt fark +68.70, ücret tasarrufu +143.83, funding farkı +0.20 USDT. Bu bir nedensel alfa ayrıştırması değildir.
- Ortalama kazanan/kaybedenle yaklaşık başa baş isabet %46.25; gözlenen isabet bunun altındadır.
- Günlük ortalama netin iki günlük blok CI %95 (USDT/gün): [-29.91, -14.50].
- Cüzdan neti − işlem neti: 0.0000000000 USDT.
- Funding durumu: `{"AVAXUSDT": "FETCHED", "BNBUSDT": "FETCHED", "BTCUSDT": "FETCHED", "DOGEUSDT": "FETCHED", "ETHUSDT": "FETCHED", "SOLUSDT": "FETCHED", "SUIUSDT": "FETCHED", "XRPUSDT": "FETCHED"}`. Settlement mark yerine 5m açılışı kullanılır; yaklaşıktır.
- v9.3 karşılaştırması eski kuralları aynı yeni ortak saat ve cüzdanda çalıştırır; önceki teslimin birebir tekrarı değildir. Risk bütçesi/strateji birlikte değişmiştir; fark saf alfa katkısı değildir.
- no_fee_no_slippage_funding_on teşhisinde fee/kayma sıfır, funding ve karar içindeki maliyet başlığı kapısı aynı kalır. Feeye bağlı çıkış tabanı/dolum yolu da etkilenebilir; aynı sabit işlem listesinden ücret çıkarma işlemi değildir.
- Bu kolda bile net negatif: sorun yalnızca komisyon değildir. Yeni adayın daha az kaybetmesi kârlılık kanıtı değildir.
- MARKET ablasyonunun aynı çıkması yalnız bu örneklemde ek portföy farkı gözlenmediğini gösterir; evrensel gereksizlik kanıtı değildir. TREND/FLOW ve çıkış ablasyonları yol-bağımlı portföy karşılaştırmalarıdır; geleceğe taşınan kesin nedensel katsayılar değildir.

### Önceden yazılan kabul kontrolleri

```json
{
  "min_closed_trades": true,
  "positive_base_net": false,
  "positive_all_stress_nets": false,
  "equity_drawdown_within_cap": false,
  "daily_clustered_ci_positive": false,
  "funding_data_complete": true
}
```

### Yeni adayın çıkış ve sembol dökümleri

| Tür | Grup | İşlem | Net USDT |
|---|---|---:|---:|
| reason | CONFIRMED_THESIS_FAILURE | 144 | -200.95 |
| reason | PROFIT_LOCK_STOP | 85 | +233.62 |
| reason | STOP_GAP | 2 | +3.68 |
| reason | TACTICAL_STOP | 144 | -392.23 |
| reason | TEST_END_MARK_TO_MARKET | 3 | +0.90 |
| symbol | AVAXUSDT | 45 | -10.01 |
| symbol | BNBUSDT | 48 | -16.74 |
| symbol | BTCUSDT | 52 | -61.87 |
| symbol | DOGEUSDT | 51 | -55.24 |
| symbol | ETHUSDT | 45 | -44.92 |
| symbol | SOLUSDT | 41 | -69.04 |
| symbol | SUIUSDT | 52 | -58.23 |
| symbol | XRPUSDT | 44 | -38.93 |

## 6. Ayrı yönlü kapı-cohort denetimi

**Kapsam:** önceden tanımlanan üç aile TREND (HTF/etkinlik/RSI/uzama), FLOW ve MARKETtir. Veri kalitesi/tazelik, gerçek taker, spread, yerel yön tanımı, tetik, ATR-risk ve maliyet başlığı hard kontrolleri kaldırılmadı; bunların her biri için ayrı ileri-getiri CI deneyi yapılmış değildir. Eski altı kapının olgunlaşmış paydası da bilinmiyor. Bu rapor “bütün eski/yeni ret nedenlerine CI hesaplandı” iddiası taşımaz.
SINGLE_BLOCKER: yalnız ilgili TEK aile kaldırıldığında diğer bütün giriş koşullarını geçen aday. Yerine başka filtre konmaz. Gelecek fiyatlar yalnız etiket/rapor için okunur; işlem kararına/parametre seçimine verilmez. BASE_ACCEPTED_REFERENCE randomize veya eşleştirilmiş nedensel kontrol değildir.

| Cohort | Yön | Benzersiz | 15m olgun | Sansürlü | Brüt bps | 24.5bps sonrası | En kötü MAE bps | Taktik / %8 temas |
|---|---|---:|---:|---:|---:|---:|---:|---|
| BASE_ACCEPTED_REFERENCE | LONG | 254 | 254 | 0 | -6.00 | -30.50 | -572.07 | 20 / 0 |
| BASE_ACCEPTED_REFERENCE | SHORT | 365 | 365 | 0 | -3.94 | -28.44 | -261.32 | 39 / 0 |
| SINGLE_BLOCKER_FLOW | LONG | 394 | 393 | 1 | -4.80 | -29.30 | -158.28 | 26 / 0 |
| SINGLE_BLOCKER_FLOW | SHORT | 456 | 456 | 0 | +0.74 | -23.76 | -215.05 | 35 / 0 |
| SINGLE_BLOCKER_TREND | LONG | 1045 | 1040 | 5 | -2.84 | -27.34 | -289.87 | 102 / 0 |
| SINGLE_BLOCKER_TREND | SHORT | 1325 | 1325 | 0 | -3.69 | -28.19 | -186.77 | 203 / 0 |
| SINGLE_BLOCKER_MARKET | LONG | 0 | 0 | 0 | Yetersiz / yok | Yetersiz / yok | Yetersiz / yok | 0 / 0 |
| SINGLE_BLOCKER_MARKET | SHORT | 0 | 0 | 0 | Yetersiz / yok | Yetersiz / yok | Yetersiz / yok | 0 / 0 |

### Güven aralıkları: 8bps/yön maliyet senaryosu sonrasında

| Cohort | Yön | n / sembol / gün | Nominal %95 CI | Altı karşılaştırma düzeltilmiş CI | Durum |
|---|---|---|---|---|
| BASE_ACCEPTED_REFERENCE | LONG | 254 / 8 / 15 | [-34.24, -26.16] | [-36.02, -25.02] | DESCRIPTIVE_INTERVAL_AVAILABLE |
| BASE_ACCEPTED_REFERENCE | SHORT | 365 / 8 / 16 | [-33.32, -23.64] | [-34.98, -22.37] | DESCRIPTIVE_INTERVAL_AVAILABLE |
| SINGLE_BLOCKER_FLOW | LONG | 393 / 8 / 15 | [-33.37, -25.75] | [-34.79, -24.75] | DESCRIPTIVE_INTERVAL_AVAILABLE |
| SINGLE_BLOCKER_FLOW | SHORT | 456 / 8 / 16 | [-28.54, -17.21] | [-29.74, -14.74] | DESCRIPTIVE_INTERVAL_AVAILABLE |
| SINGLE_BLOCKER_TREND | LONG | 1040 / 8 / 15 | [-31.36, -22.20] | [-32.25, -20.39] | DESCRIPTIVE_INTERVAL_AVAILABLE |
| SINGLE_BLOCKER_TREND | SHORT | 1325 / 8 / 16 | [-31.86, -24.33] | [-32.94, -23.13] | DESCRIPTIVE_INTERVAL_AVAILABLE |
| SINGLE_BLOCKER_MARKET | LONG | 0 / 0 / 0 | Hesaplanamadı / yetersiz kanıt | Hesaplanamadı / yetersiz kanıt | INSUFFICIENT_EVIDENCE |
| SINGLE_BLOCKER_MARKET | SHORT | 0 / 0 / 0 | Hesaplanamadı / yetersiz kanıt | Hesaplanamadı / yetersiz kanıt | INSUFFICIENT_EVIDENCE |

SINGLE_BLOCKER_MARKET satırları ham audit JSONunda bulunmuyorsa bu renderer onları sıfır n / yetersiz kanıt olarak açıkça gösterir; yeni gözlem icat etmez. Tarihsel audit her sembol-kapalı mum için bir kez bakar: burada benzersiz cohort sayısı ilgili cohort ham kayıt sayısına eşittir, canlıdaki tekrar eden kapı sayacıyla karıştırılmaz.

İki günlük hareketli blok bootstrap bütün sembolleri aynı UTC gününde birlikte kümeler. Üç kapı × iki yön için nominal Bonferroni aile düzeltmesi vardır. Kısa seri, rejim değişimi ve durağanlık varsayımı nedeniyle aralıklar betimleyicidir; kesin anlamlılık/kausalite iddiası yoktur. Ufuklar örtüşür. Başlangıç bariyerine temas, gerçek maker dolumu veya dinamik takip stopuyla gerçekleşecek işlemin tam sonucu değildir.

## 7. 15 dakika canlı veri / PAPER sonucu

- Faz COMPLETED; aktif hedef 900s, toplam 900.22s, drenaj 0.00s.
- Kapalı işlem **0**; kapalı brüt **+0.0000**, kapalı net **+0.0000 USDT**.
- Açık pozisyon **0**; gerçekleşmemiş brüt **+0.0000 USDT**.
- Ödenmiş ücret 0.0000; equity **1000.0000**, başlangıca fark **+0.0000 USDT**.
- **Akış kusuru:** Binance BBO 1,773,328 güncelleme, aggTrade 0, hata 133. OKX BBO 427,665, işlem ticki 70,112, hata 0. Her iki venue kotasyon almış olsa da tam çift-venue trade-tape/yürütme doğrulaması geçmedi.
- **Sağlık alanı kör noktası:** JSONdaki genel healthy=true BBO güncelliğiyle birlikte oluşuyor; sıfır işlem akışını sağlıklı kanıtlamaz. Donmuş runner değiştirilmedi. Kök neden bu deneyde giderilmiş/doğrulanmış sayılmaz. Ayrı yeni sürüm ve yeni donmayla onarım gerekir.
- Gerçek emir gönderilmedi. Sıfır/az işlem veya pozitif birkaç paper işlem kârlılık kanıtı değildir. Bu tek gün testi 10 UTC günü gate-CI koşulunu karşılayamaz.

```json
{
  "venues": {
    "binance": {
      "healthy": true,
      "fresh_pairs": 34,
      "ticks": 0,
      "bbo_updates": 1773328,
      "endpoint": "fstream.binance.com",
      "last_ts": 1793690951.5113788,
      "errors": 133
    },
    "okx": {
      "healthy": true,
      "fresh_pairs": 35,
      "ticks": 70112,
      "bbo_updates": 427665,
      "endpoint": "wss://ws.okx.com/ws/v5/public",
      "last_ts": 1793690951.5101519,
      "errors": 0
    }
  },
  "venue_trade_counts": {
    "binance": 0,
    "okx": 0
  },
  "maker_queue": {
    "submitted": 0,
    "filled": 0,
    "partial_filled": 0,
    "expired_unfilled": 0,
    "post_only_rejected": 0,
    "open_resting": 0,
    "fill_rate_pct": 0.0,
    "avg_wait_ms": 0.0,
    "avg_unfilled_runaway_bps": 0.0
  },
  "operational_health": {
    "healthy": true,
    "feed_lag_sec": 0.09,
    "ledger_reconciled": true,
    "memory_open_count": 0,
    "sqlite_open_count": 0,
    "alarms": []
  },
  "observer_errors": []
}
```

### Canlı kapı adetleri — ham, benzersiz ve olgunlaşmış ayrı

| Kapı | Yön | Ham | Benzersiz | Olgun 5m | Olgun 15m | Bekleyen 15m | Pencere kaçırılmış 15m | En kötü 15m MAE bps | %8 temas |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SINGLE_BLOCKER_TREND | LONG | 0 | 0 | 0 | 0 | 0 | 0 | Yetersiz / yok | 0 |
| SINGLE_BLOCKER_TREND | SHORT | 5 | 5 | 5 | 0 | 5 | 0 | Yetersiz / yok | 0 |
| SINGLE_BLOCKER_FLOW | LONG | 0 | 0 | 0 | 0 | 0 | 0 | Yetersiz / yok | 0 |
| SINGLE_BLOCKER_FLOW | SHORT | 5 | 5 | 5 | 0 | 5 | 0 | Yetersiz / yok | 0 |
| SINGLE_BLOCKER_MARKET | LONG | 0 | 0 | 0 | 0 | 0 | 0 | Yetersiz / yok | 0 |
| SINGLE_BLOCKER_MARKET | SHORT | 0 | 0 | 0 | 0 | 0 | 0 | Yetersiz / yok | 0 |

Gözlemci hataları JSON bölümünde gösterilir. 15m ufku dolmamış cohortlara son fiyatla 15m etiketi verilmedi. Pencere içindeki gözlem bekleyenleri ayrıntılı JSONda ayrıca bulunur. Tek günlük canlı örnek için tüm CI sonuçları yetersiz kanıttır.

## 8. Kural değişmezliğinin SHA-256 kanıtı

| Dosya | v9.4.0 = v9.4.1 SHA-256 | Aynı |
|---|---|---|
| src/v94_core.py | `d05e6e29df3a2086cd72f3fd4b7be5a81db7c75a143d73ac6ee8a562e2c75349` | True |
| src/adaptive_policy.py | `95d1cd1709e31765cc1997c6cda98b8f214bc57edf6104837e6018eee1904099` | True |
| src/v94_live_risk.py | `89b01884db0d60b9e78867f2125227c32cd145042d0bac4af0007592f02912e6` | True |
| src/v94_live_router.py | `6fe5d8f0302bc91ebe6bac207d5151acf6a6087ccfaec35e3f476652977aa9b3` | True |
| src/risk.py | `7dfec46ce8cdbf9e31b8a72a47b623187d96dd8466783544504806a63af47779` | True |
| src/flow_exit_manager.py | `f4fbd2576f485ae2afad7c53075296fac3fa24e2f68b8739fc1b2bd07fe3c963` | True |
| src/executor.py | `e71ed14f341b2cc916398fd7dbd3bb466e8fdbd8d4a8a535a636705726b4a3be` | True |
| src/unified_engine.py | `7d55e793cec19ac0f2d9b89efc9604fd6968b514c94db73b3f2c766a33789889` | True |
| src/live_runner.py | `da5caef97272f047107c33b0e4a3e44f3929735b23684c812ec135f06ce9b36a` | True |
| backtests/chronological_portfolio.py | `f72ddc71bd7350dc9186edf5e507a25b5c429fb5dcf146751518c35fe25593f8` | True |
| strategies/v93_flow_strategy.py | `6196b255bd3ed134ab1c1ca1b4d5d0039a217f4a153ddf4c26c9a86b758f6fe8` | True |
| src/strategy.py | `220ae0921487add6f33d92b783b145d3a656cc448e474de9de641c631a5a489b` | True |
| strategies/base.py | `ee5d1280863b10c65233454d7f44ad264f2021ae4267558cfd4043de5b90b343` | True |

İşlem kodu temeli 9.4.0, paket sürümü 9.4.1. Değişen katmanlar: ayrı ölçüm gözlemcisi, istatistik, test/rapor araçları ve metadata. Orijinal karar nesnesi değiştirilmez. Ek CPU süresi nedeniyle canlı zamanlamanın birebir aynı olduğu iddia edilmez.

## 9. Son karar ve sonraki adım

**RESEARCH_CRITERIA_FAILED_REAL_MONEY_REJECTED. Gerçek para onayı: FALSE.**

- Yeni aday negatif veya kabul dışıysa performans yükseltmesi olarak terfi ettirilmez. Ölçüm altyapısının doğrulanması strateji edge kanıtı değildir.
- Aynı test üzerinde yeni eşik/stop ayarı yapıp tekrar “OOS” denmedi; kazanan sembol veya yön sonradan seçilmedi.
- Sonraki strateji deneyi ancak yeni, ayrıca dondurulmuş hipotez ve yeni veriyle yapılabilir. Önce entry edge ile çıkış etkisini ayrıştıran kontrollü deney ve daha uzun prospektif paper gerekir.
- Stop-bazlı risk, gap, likidite çöküşü, ortak piyasa faktörü ve tekrarlayan zararlardan oluşan toplam düşüşü garantiyle sınırlamaz.
- Miras paper muhasebesi marjı aşan gap kaybını likidasyonla sınırlar; gerçek cross kaybı daha yüksek olabilir. Sabit sembol seçimi survivorship yanlılığı taşır.

## Kanıt dosyaları

`v94_historical_validation.json`, `v941_gate_cohort_audit.json`, `v94_freeze_manifest.json`, `v94_development_results.json`, `v94_canli_15dk_summary.json`, `v94_pytest.txt`, doğrulanmış CSV tabloları ve kesintili oturum arşivi.
