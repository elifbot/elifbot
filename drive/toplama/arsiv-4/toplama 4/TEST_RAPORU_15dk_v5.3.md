# 15 DAKİKALIK CANLI PAPER TESTİ — v5.3

**Oturum:** 2026-11-08 07:08:19 → 07:23:19 UTC · **900,0 sn** (tam)
**Sürüm:** `5.3-final` · çıkış kodu **0**
**Komut:**
```bash
python3 -m app.main --mode paper --paper --exchange all --scan-all \
  --profile apex --motors trend --balance 1000 --duration-minutes 15 \
  --costs docs/maliyet_olcum_v5.2.json \
  --state test15_v53.sqlite3 --report-file session_report_15min_v53.json
```
Gerçek emir gönderilmedi. `--paper` zorunlu onay bayrağı verildi.

---

## 1. Sağlık — TEMİZ

| Ölçüt | Sonuç |
|---|---|
| Traceback | **0** |
| Grid ihlali | **0** |
| ERROR seviyesi log | **0** |
| Çıkış kodu | **0** |
| Oturum süresi | **900,0 sn** (kesintisiz) |

---

## 2. İşlem akışı

| | |
|---|---|
| Giriş emri | **4** |
| Dolum | **1** |
| Kapanış | **0** |
| Açık pozisyon | **1** |
| Bakiye | 1000,00 → **999,1416** (giriş ücreti) |
| Equity | **994,7249** |
| Gerçekleşen PnL | **0,0000** |
| Gerçekleşmeyen PnL | **−4,4167** |

Dolan pozisyon: **`binance:MUBARAKUSDT` LONG** @ 0,040681862,
miktar 105.506,16, 07:15:47 UTC. Oturum sonunda hâlâ açıktı;
stop/TP/TTL tetiklenmedi.

**Dürüst sınır:** bu oturum **kapanmış işlem üretmedi**, dolayısıyla
gerçekleşen PnL kanıtı yok. Equity'deki −5,28 USDT'nin tamamı
**işaretlenmemiş (mark-to-market)** değerdir; kapanış fiyatı değildir.
Önceki iki oturumun aksine canlı maliyet ölçekleme yolu bu turda
**çalıştırılmadı** (aşağıya bakın).

Diğer üç emir dolmadı: `HIMSBUSDT` LONG (skor 78),
`GRASS-USDT-SWAP` LONG (skor 76), `QIUSDT` SHORT (skor 93).
45 saniyelik maker TTL içinde fiyat limite gelmedi.

---

## 3. YENİ — canlı gölge sinyal kanıtı

Bu, v5.3'ün test ettiği asıl yeniliktir. Önceki sürümlerde gölge
takibinin en kısa ufku **30 dakika** idi; 15 dakikalık testte hiçbir
sinyal olgunlaşamıyor ve mekanizma **sessizce boş** dönüyordu.
Ufuklar **1 / 5 / 15 / 30 / 60 / 120 dk** yapıldı ve özet, eldeki en
uzun olgun ufku kullanacak şekilde düzeltildi.

Maliyet kapısının reddettiği **3 sinyal** artık izleniyor:

| Reddedilen | Borsa |
|---|---|
| `PENG-USDT-SWAP` | OKX |
| `INFQ-USDT-SWAP` | OKX |
| `GMX-USDT-SWAP` | OKX |

```json
"MALIYET_BUTCESI_ASIMI": {
  "blocked": 3, "matured": 3, "karar_veren": 1,
  "once_stop": 1, "once_hedef": 0, "hedef_orani": 0.0,
  "ort_son_getiri_pct": -0.0737,
  "olgunlasan_ufuk_dakika": 15,
  "ort_mfe_pct": 0.0784, "ort_mae_pct": -0.1898
}
```

**Okuma:** üçü de 15 dakikalık ufukta olgunlaştı. Biri karar verdi:
**önce stop'a dokundu, hedefe hiç dokunmadı.** Ortalama en iyi excursion
+%0,0784 iken en kötü excursion −%0,1898 — yani hareket aşağı yönlüydü.

Bu, 90 günlük backtest kapı atfıyla **aynı yönde**: maliyet kapısı
kötü adayları eliyor (orada reddedilenlerin kazanma oranı %18,9,
kabul edilenlerden %28,6'dan düşük).

> **İstatistiksel sınır — açıkça:** karar veren sinyal sayısı **1**.
> Bu bir oran değildir, tek gözlemdir. Mekanizmanın **çalıştığını**
> kanıtlar; kapının kârlı olduğunu **kanıtlamaz**. Yön backtest ile
> tutarlıdır, hepsi bu.

Ayrıca artık iyimser `would_have_won` alanı yok: "hedefe değdi" demek
için fiyatın **stop'a önce değmemiş** olması gerekiyor ve yol 1 dakikalık
mumlarla izleniyor.

---

## 4. Risk ölçekleme

```json
"budgets_issued": 7, "blocked_count": 3,
"binding_counts": {"cost": 1, "drawdown": 6},
"min_scale_seen": 0.001552, "mean_scale": 0.857365,
"opened_positions": 1, "scaled_down_positions": 0,
"observed_min_net_risk": 25.0, "observed_max_net_risk": 25.0,
"never_scaled_up": true, "live_effective": null
```

- **7 bütçe verildi, 3'ü engellendi.** Bağlayıcı kısıt çoğunlukla
  **drawdown (6)**, bir kez **maliyet (1)**.
- `GRASS-USDT-SWAP` emri bütçesi **2,50 USDT tabanına** kadar küçültüldü
  (ölçek 0,0016) — yani ölçekleyici gerçekten devreye girdi; ancak o emir
  **dolmadığı** için açılan pozisyon sayısına girmiyor.
- Dolan tek pozisyon (`MUBARAKUSDT`) ölçeklenmemişti: net risk **25,00 USDT**.
  Bu yüzden **`live_effective = null`** — "canlıda ölçekleme etkin"
  diyemeyiz, çünkü bu oturumda ölçeklenmiş pozisyon açılmadı.
- **`never_scaled_up = true`**: hiçbir pozisyon taban riskin üstüne
  çıkarılmadı. Gerçek paraya ölçekleme yapılmadı.

**Önceki turla karşılaştırma:** v5.2 B turunda `live_effective = true`
idi (OFC pozisyonu 25,00 yerine 12,9574 USDT risk ile açıldı, ölçek
0,5183). O kanıt **geçerli ve duruyor**; bu tur onu tekrarlamadı.

---

## 5. Sinyal redleri

| Neden | Adet |
|---|---|
| `dusuk_hacim` | 2.919 |
| `trend_onayi_yok` | 544 |
| `geri_cekilme_yok` | 107 |
| `fake_breakout_or_suspect` | 76 |
| `rejim_uyumsuz` | 41 |
| `dusuk_puan` | 1 |

`dusuk_hacim` yine baskın. **Bu bir darboğaz teşhisi değildir:**
v5.3 ablasyonu RVOL eşiğini 1,5 → 0,5 çektiğinde bu redler %66 azaldı
ama işlem sayısı **hiç değişmedi** ve net sonuç **kötüleşti**
(−80,65 → −82,25). Redler başka kapılara kaydı. Hacim kalibrasyonu
öncelik listesinden çıkarıldı.

---

## 6. Ters seçilim

```json
"fills_beyond_stop": 0, "stale_fill_cancels": 0,
"born_dead_closes": 0, "optimistic_stale_cancel": false,
"policy": "GERÇEKÇİ (ters seçilim modellenir, kayıp görünür)"
```

Bu oturumda stop ötesi dolum olmadı. Politika **gerçekçi** kaldı;
iyimser iptal kalkanı kapalı. (v5.2 A turundaki GNO `hold_ms=0`
davranışının kasıtlı gerçekçilik olduğu doğrulanmıştı; geri alınmıştır.)

---

## 7. Üç oturumun karşılaştırması

| | v5.2 A | v5.2 B | **v5.3** |
|---|---|---|---|
| Giriş emri | 6 | 6 | **4** |
| Dolum | 1 | 1 | **1** |
| Kapanış | 1 | 1 | **0** |
| Gerçekleşen PnL | −31,3734 | −15,6826 | **0,0000** |
| Gerçekleşmeyen | 0 | 0 | **−4,4167** |
| `live_effective` | null | **true** | null |
| Gölge olgunlaşan | 0 | 0 | **3** |
| Traceback / grid | 0 / 0 | 0 / 0 | **0 / 0** |

**Toplam gerçekleşen: −47,0560 USDT, 2 işlem, 0 kazanan.**
Üç oturum birlikte de istatistiksel bir örneklem değildir; amaç
**yolun çalıştığını** doğrulamaktır, kârlılığı değil.

---

## 8. Hüküm

**Yol sağlıklı, kanıt zayıf, kenar yok.**

- Kod hatasız 15 dakika koştu, emir → dolum → rapor zinciri çalıştı.
- Yeni gölge mekanizması **ilk kez canlı veri üretti** ve backtest
  bulgusuyla aynı yönü gösterdi (1 gözlem).
- Risk ölçekleyici bütçeleri gerçekten kıstı ama ölçeklenmiş pozisyon
  açılmadığı için bu turda canlı etkinlik **kanıtlanmadı**.
- Kapanmış işlem yok; bu oturumdan kârlılık/zarar hükmü çıkarılamaz.

90 günlük backtest hükmü değişmedi: **`NO_EDGE`**.
Çıkış geometrisi 5,53× açık (ödül/risk 0,452, gereken 2,500).

**Gerçek paraya ölçekleme YAPILMAMALI.** Pozisyon başına azami kayıp
**2,5–5 USDT** aralığında tutulmalı.

---

## 9. Açık sınırlar

- Testnet yok; paper motoru gerçek borsa emir defterini simüle etmiyor.
- MTF ve orderflow kapalı.
- Ajanlar backtest'te etkisiz.
- Binance futures tick doğrulanamadı (fapi 451 / 202 / 404) → 518 sembol
  `unverified`. Binance maliyetleri **ölçülmedi**, varsayılan kullanılıyor.
- OKX veri kaynağı sık sık `perp → spot-mirror` geçişi yaptı; raporlar
  etiketliyor ama fiyat kaynağı homojen değil.
- Backtest dolum penceresi 5 dk, canlı 45 sn (**6,7×**). 30 günlük
  ölçümde dolumların **%7,7'si** gerçek TTL dışındaydı. Ölçüldü,
  düzeltilmedi.
- Gölge kanıtı **1 karar veren sinyal** — oran değil, gözlem.
