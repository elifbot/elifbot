# Doğrulama Raporu — Gerçek Piyasa Verisiyle PAPER

**Tarih:** 3 Kasım 2026 · **Ortam:** Linux sandbox, Python 3.13.16
**Mod:** PAPER (borsaya emir gönderilmedi) · **Gerçek para onayı:** YOK

---

## 1. Özet

| Doğrulama | Sonuç |
|---|---|
| Arşiv SHA-256 bütünlüğü | **17/17 eşleşti** |
| v9.4.5 "158 test" iddiası | **Yeniden koşuldu: 158 passed** |
| OmniStudio test paketi | **150/150 geçti** |
| Gerçek piyasa verisi erişimi | **2 borsa, WS + REST** |
| Doğal profil süre protokolü | **COMPLETED, 0 boşluk** |
| Aç/kapat yaşam döngüsü | **Gerçek veriyle doğrulandı** |
| LIVE kilidi | **Aktif, test edildi** |
| 20 YZ sağlayıcı | **Kayıtlı, anahtarsız dürüst mod** |

## 2. Test paketi

```
150 passed in 1.32s
```

Kapsam dağılımı:

| Alan | Test |
|---|---:|
| Fiyat indeksi eşdeğerliği | 8 |
| Kayan hacim toplamı eşdeğerliği | 5 |
| İndikatörler | 7 |
| Dedektör kapıları | 8 |
| Giriş politikası | 10 |
| Risk / stop yolu | 18 |
| PAPER icra + muhasebe | 11 |
| 20 YZ konseyi | 14 |
| Güvenlik / config | 10 |
| Süreklilik | 4 |
| Görev denetimi | 5 |
| SQLite / lease | 7 |
| Uçtan uca entegrasyon | 2 |

### Testlerin bulduğu gerçek hatalar

Testler yazılırken **3 gerçek kod hatası** bulundu ve düzeltildi:

1. **`slots=True` metadata çakışması** — `Order`/`Position` üzerinde `setattr`
   çalışmıyordu. Açık `meta: dict` alanına taşındı.
2. **SQL parametre sayısı** — `decisions` tablosuna 8 kolona 9 değer
   gönderiliyordu. Düzeltildi.
3. **`CouncilVerdict` kurucu argümanı** — `rounds` iki kez veriliyordu.

Ayrıca ilk gerçek koşuda **3 davranışsal hata** bulundu:

4. **Faz geçişi** — `WARMUP` durumundan `ACTIVE`'e geçiş hiç tetiklenmiyordu.
5. **Hacim tazeliği** — hacim taşıyan gerçek tick, hacim akışını tazelemiyordu;
   bu yüzden 7.054 sahte `stale_volume` reddi oluşuyordu.
6. **Planlı kapanış** — normal kapanıştaki `cancel()` görev ölümü sayılıp
   run'ı `FAILED` yapıyordu. `begin_shutdown()` ayrımı eklendi.

> Bu hatalar gizlenmedi. İlk koşunun `FAILED` kaydı `runs/ilk-gercek-test/`
> altında kanıt olarak duruyor.

## 3. Gerçek veri koşuları

### 3.1 `ilk-gercek-test` — FAILED (kanıt olarak saklandı)

| Ölçüm | Değer |
|---|---:|
| Gerçek tick | 8.480 |
| WS mesaj | 8.482 (2 borsa) |
| REST hata | 0 / 1.618 |
| Durum | FAILED (kapanış iptali hata sayıldı) |

Bu koşu yukarıdaki 4–6 numaralı hataları ortaya çıkardı.

### 3.2 `dogrulamali-test` — COMPLETED

| Ölçüm | Değer |
|---|---:|
| Gerçek tick | 11.072 |
| Aktif pencere tamamlandı | **evet** |
| Süreklilik boşluğu | **0** |
| Maks poll gecikmesi | 0,0106 s |
| Görev hatası | **0** |
| Sinyal | 0 |

### 3.3 `genis-evren-8dk` — COMPLETED, doğal profil

**Profil:** `natural` — üretim eşikleri, filtre gevşetmesi **yok**.

| Ölçüm | Değer |
|---|---:|
| İzlenen sembol | 140 (70 + 70) |
| Gerçek tick | **60.806** |
| WS mesaj | 60.811 |
| Aktif süre | 480 s + 60 s drenaj |
| Süreklilik boşluğu | **0** |
| Görev hatası / alarm | **0 / 0** |
| Dedektör sinyali | **4** |
| Politikaya giren | 3 |
| Kabul | **0** |

Ret nedenleri (gerçek, makine okunur):

| Sembol | Yön | Ret | Değer / Eşik |
|---|---|---|---|
| HYPE_USDT | LONG | `OVER_EXTENDED` | 3,288 > 3,0 ATR |
| ZEC_USDT | LONG | `CONTRA_FLOW` | −36,92 < −35,0 |
| SOXL_USDT | LONG | `EDGE_BELOW_COST` | 0,600 < 1,15 oran |

**Yorum:** Bu, sistemin doğru çalıştığının kanıtıdır. Doğal eşikler çok
seçicidir ve bu, arşivin v9.4.1 bulgusuyla (kenar maliyeti karşılamıyor)
tutarlıdır. **Daha çok işlem görmek için filtreler gevşetilmedi.**

### 3.4 `yasam-dongusu-tani` — COMPLETED, tanı profili

> ⚠️ **BU KOŞU DOĞAL STRATEJİ KANITI DEĞİLDİR.**
> Profil `lifecycle-diagnostic`; eşikler yalnız aç/kapat yolunu gerçek veri
> üzerinde sınamak için gevşetildi. `SONUC.json` içinde
> `evidence_class: LIFECYCLE_DIAGNOSTIC_NOT_NATURAL` ve
> `filters_relaxed: true` olarak işaretlidir. İşlem sayısı, PnL veya isabet
> oranı strateji değerlendirmesinde **kullanılamaz**.

| Ölçüm | Değer |
|---|---:|
| Gerçek tick | 32.613 |
| Dedektör sinyali | 844 |
| Politikayı geçen | 7 |
| Konseye giren | 1 |
| Kabul / emir | **1 / 1** |
| Kısmi dolum | 9 |
| Süresi dolan emir | 1 |
| Açılan pozisyon | **1** |
| Kapanan pozisyon | **1** |
| Süreklilik boşluğu | **0** |

**Gerçek yaşam döngüsü kaydı:**

```
18:51:41  PAPER AÇILIŞ  BMTUSDT LONG qty=470.95 @0.026010
                        stop=0.025864  tp=0.026192
18:52:50  PAPER KAPANIŞ BMTUSDT LONG net=-0.335406 USDT  neden=STOP_LOSS
```

| Muhasebe | Değer |
|---|---:|
| Tutma süresi | 68,849 s |
| Gerçekleşen net | **−0,335406 USDT** |
| Ödenen ücret | 0,108970 USDT |
| Başlangıç equity | 10.000,000000 |
| Bitiş equity | **9.999,664594** |
| Açık unrealized | 0,000000 |
| Borsaya gönderilen emir | **0** |

Bu tek işlem **kârlılık göstergesi değildir**; yalnız şu yolu doğrular:
sinyal → kapılar → konsey → boyut → maker kısmi dolum → stop tetikleme →
taker çıkış → ücret + net PnL → equity + SQLite + JSONL.

## 4. Performans ölçümü

| İşlem | v9.4.5 arşiv (maks) | OmniStudio (maks) |
|---|---:|---:|
| Tick işleme (`on_trade`) | 150,602 ms | **1,901 ms** |
| Genişlik güncelleme | 150,004 ms | **2,320 ms** |
| WS JSON parse | 20,218 s / 2,55 M çağrı | 0,155 s / 8,5 K çağrı |
| Süreklilik boşluğu | 1 × 5,22 s | **0** |

**Yorum sınırı:** Farklı ortam, farklı sembol sayısı, farklı süre. Eşleştirilmiş
kontrollü kıyas **değildir**; "X kat hızlandı" iddiası kurulmaz. Yalnız aynı
işin artık milisaniye mertebesinde olduğu söylenebilir.

### Hâlâ yavaş olan yerler (dürüstçe)

| İşlem | Maks | Not |
|---|---:|---|
| `candle_refresh` | 5.094 ms | 140 sembol REST toplu istek; ağ beklemesi |
| `quote_refresh` | 2.719 ms | Aynı; event loop'u bloke etmez (async) |
| `state_write` | 6,916 ms | SQLite commit; disk gecikmesi olabilir |

Bunlar **ağ/disk beklemesidir**, CPU darboğazı değildir. Tick hattını
bloke etmezler çünkü ayrı async görevlerde çalışırlar.

## 5. Eşdeğerlik doğrulamaları

Optimizasyonların çıktıyı değiştirmediği kanıtlandı:

| Yapı | Kontrol | Uyuşmazlık |
|---|---:|---:|
| `PriceHistory.first_at_or_after` | 1.000+ arama (CLI check) | **0** |
| `PriceHistory` rastgele test | 120 deneme × 8 eşik | **0** |
| Kayan hacim toplamı | **24.000** kontrol | **0** |
| Dedektör hız/rvol | 300 tick tam tarama kıyası | **0** |

Sırasız zaman damgası, NaN, tampon taşması, cutoff geriye gitmesi ve
eviction durumlarının hepsinde eski doğru yola düşülür.

## 6. Güvenlik doğrulamaları

| Kontrol | Sonuç |
|---|---|
| `assert_mode_allowed(LIVE)` | `LiveTradingBlocked` yükseltti ✓ |
| Config `mode: LIVE` | Doğrulamada reddedildi ✓ |
| Anahtar `public_info()`'da | Görünmüyor ✓ |
| Anahtar config dökümünde | Görünmüyor ✓ |
| Pano yazma ucu | Yok (salt okunur) ✓ |
| Pano yol geçişi (`..`) | Engellendi ✓ |
| Borsaya giden emir | **0** (tüm koşularda) ✓ |

## 7. Yapılmayanlar

Açıkça beyan edilir:

- Gerçek YZ API çağrısı **yapılmadı** (anahtar yok). Adapter'lar yazıldı,
  protokoller gerçek; ancak canlı sağlayıcı yanıtı ile uçtan uca test
  edilmedi. Anahtar girildiğinde ilk doğrulama gerekir.
- Uzun süreli (saatler/günler) bellek soak testi yapılmadı.
- Büyük gerçek defter yük testi yapılmadı.
- Docker/Compose dağıtımı doğrulanmadı (bu ortamda Docker yok).
- Tam transitif bağımlılık kilidi üretilmedi.
- 5,22 s tarihsel boşluğun kök nedeni **hâlâ açık**; yeni kod boşluğu anında
  tespit eder ama nedeni kanıtlamaz.
- Eşleştirilmiş performans kıyası yapılmadı.

## 8. Kanıt dizinleri

```
runs/
├── ilk-gercek-test/        FAILED — bulunan 3 hatanın kanıtı
├── dogrulamali-test/       COMPLETED — düzeltme sonrası, 0 boşluk
├── genis-evren-8dk/        COMPLETED — doğal profil, 60.806 tick
└── yasam-dongusu-tani/     COMPLETED — tanı, gerçek aç/kapat
```

Her dizinde: `SONUC.json`, `RAPOR.md`, `config.json`, `decisions.jsonl`,
`events.jsonl`, `health.jsonl`, `state.db`, `console.log`.

Ham kayıtlar silinmedi veya yeniden yazılmadı.