# v9.4.3 — PENDING sağlık ve endpoint yaması

**PAPER araştırma sürümü; gerçek para, kârlılık veya gerçek borsa yürütme onayı yok.**

**Kanıt sınırı:** 15 saniyelik PENDING toleransı birim ve ayrı HTTP testleriyle doğrulandı. Canlı koşuda PENDING sırasında sağlıklı HTTP yanıtı gözlenmedi. 59/59 HTTP 200 yalnız örneklenen bağlantı/sağlık durumlarının kanıtıdır; canlı PENDING senaryosu veya uçtan uca operasyonel hazırlık onayı değildir.

## Yapılan düzeltmeler

- Süreç-içi sahiplik kaydıyla eşleşen, 15 saniyeden genç PENDING için yalnız sağlık görünümünde IN_FLIGHT/200. 15 saniyede ve sonrasında alarm/503.
- Restarttan kalan, başka store/PIDden gelen, yaşı/sahibi belirsiz kayıt hemen alarm. Bu kayıtlara süre toleransı verilmez.
- Üretim defteri değiştirilmez: salt-okunur SQLite yedeği belleğe alınır. Uygun genç niyetler yalnız geçici kopyada ayrıştırılır; kalan kesinleşmiş hesap, ücret, funding ve pozisyonlar eski sıkı doğrulayıcıdan geçer.
- IN_FLIGHT anında ledger_reconciled=false kalır; bu tamamlanmış mutabakat değildir. Uyarı ve pending yaşları APIde görünür; panel TAM yerine İŞLEM BEKLİYOR gösterir.
- Alarmlar gerçek nedenini gösterir: LEDGER_INTEGRITY_ERROR(reason=...), gerçek küme farkında POSITION_SET_MISMATCH.
- endpoint_aggTrade ve endpoint_bookTicker ayrı; endpoint ortak alanı artık son yazanın adresiyle yanıltmaz.

## Güvenlik ve değişmezlik

- Sıkı verify_paper_ledger_integrity metodu kaynak metni olarak değişmedi. Recovery, mali işlem kilidi ve PENDINGin kalıcı kaydı değiştirilmedi.
- Prepare yöntemlerine yalnız süreç-içi gözlem kaydı eklendi. Bu atama çıkarılınca ASTleri önceki yöntemlerle aynı; commit/iptal yöntemleri aynıdır.
- UnifiedTradingEngine içinde yalnız operational_health_snapshot değişti; diğer yöntemlerin ASTleri eski kaynakla aynı. Strateji/risk/çıkış/replay dosyaları korundu.
- Önceki 13 dosya grubunun 11i byte-byte aynı. live_runner ve unified_engine sağlık/telemetri değişikliği nedeniyle farklı; 13/13 aynı iddiası YOK. StateStore da ek sağlık kaydı/metodu içerir.
- Ek sağlık hesaplarının canlı zamanlamayı hiç etkilemediği iddia edilmez.

## Testler

```text
........................................................................ [ 59%]
.................................................                        [100%]
121 passed in 11.84s
```

Bu raporlama düzeltmesinde yeni test yapılmadı; aşağıdaki 121 sonucu önceki kendi ortamımızdaki tam test kaydıdır.
Önceki 87 teste 34 yeni sağlık/endpoint/değişmezlik kontrolü eklendi. Test kapsamı: dört niyet tablosu, 0/14.999/15/16s sınırları, yeniden başlatma/yabancı sahip, gerçek nakit/ücret/funding hataları, pozisyon kümesi farkı, ilk emir, iptal, salt-okunurluk, sıkı recovery ve gerçek HTTP handlerı. Endpoint testi iki akışın birbirini ezmediğini doğrular.

İlk test koşusunda eski alarm metnine bağlı bir assert başarısızdı (117 geçti, 1 başarısız). Bu testin beklentisi istenen yeni POSITION_SET_MISMATCH sözleşmesine güncellendi; güvenlik denetimi kaldırılmadı. İlk çıktı saklandı. Son tam test 121/121dir.

## Yeni canlı paper koşusu

- Donma UTC: 2026-11-03T09:01:26.971253+00:00. Donmuş kaynak kontrolü başarılı.
- Aktif süre yaklaşık 900.534s; drenaj 0.000s; toplam 900.534s.
- Doğrudan Python ile çalıştırıldı; Docker build/çalıştırması bu deneyde yapılmadı.
| Ölçüm | Binance | OKX |
|---|---:|---:|
| İşlem ticki | 93336 | 88525 |
| BBO | 2096582 | 435958 |
| Hata | 0 | 0 |
| aggTrade hatası | 0 | — |
| Trade-tape sağlıklı | True | True |

- Endpoint aggTrade: `fstream.binance.com/market`; bookTicker: `fstream.binance.com/public`.
- HTTP örnekleri: `{'200': 59}`. Aktif fazda ilk 60s sonrası 56 örnek, başarısız 0. Yaklaşık 15s aralıkla alınan örneklerdir; sürekli erişilebilirlik garantisi değildir.
- Canlı örneklerde IN_FLIGHT görülme sayısı: 0. Sıfırsa bu canlı koşu PENDING toleransını olay üzerinde sınamış sayılmaz; o davranış ayrı HTTP/regresyon testleriyle sınanmıştır.
- Paper kuyruk: `{"submitted": 1, "filled": 0, "partial_filled": 0, "expired_unfilled": 1, "post_only_rejected": 0, "open_resting": 0, "fill_rate_pct": 0.0, "avg_wait_ms": 5500.2, "avg_unfilled_runaway_bps": 5.2}`.
- Kapanmış 0, açık 0. Kapalı net +0.000000, açık brüt +0.000000, toplam equity farkı +0.000000 USDT.
- Son sıkı defter kontrolü: `{"ok": true, "empty": true, "reason": "clean_empty_db"}`.

### Yalnız örneklenen bağlantı/sağlık kontrolleri — tam operasyonel kabul değil

| Kontrol | Geçti |
|---|---|
| completed_900s | True |
| binance_ticks_positive | True |
| aggTrade_errors_zero | True |
| both_tapes_healthy | True |
| observed_active_post_grace_health_200 | True |
| endpoint_fields_correct | True |
| frozen_source_unchanged | True |
| final_strict_ledger_ok | True |
| no_sampling_errors_before_completion | True |

## Sınırlar ve önceki olayın yorumu

Kayıt: 1 emir denemesi vardı, dolmadı; 0 açık/0 kapalı pozisyon ve 0 gözlenmiş IN_FLIGHT örneği. Bu, PENDINGin hiç oluşmadığını kanıtlamaz; onun içindeki HTTP yanıtının örneklemeye yakalanmadığını gösterir. Önceki 503ün canlıda kapandığı kanıtlanmış değildir.

**v9.4.2deki 503 için en olası neden geçici PENDING emir niyeti; deneyle yeniden üretildi, canlı olayda ayrıca yakalanmadı.** Yeni yama eski koşunun sonucunu geriye dönük değiştirmez.
- Bu yalnız tek yeni ağ/zaman koşusudur. Ağ koşulları değişirse tekrar test gerekir.
- Thread sınırı: PENDING kaydı sonrası süreç-içi token kaydediliyor. Mevcut tek iş parçacıklı asyncio akışında arada await yok; ayrı threadli sağlık okuyucusu için atomik görünürlük ayrıca sınanmış değildir.
- Maliyet sınırı: sağlık görünümü DB kopyası alır. Küçük DBdeki test, büyüyen defterde veya sık panel sorgusunda gecikme/CPU/RAM maliyetini ölçmüş sayılmaz. Bu performans doğrulaması yapılmadı.
- Önerilen 24–48 saatlik prospektif koşu bu raporlama düzeltmesi sırasında BAŞLATILMADI. Süre, kaynak donması ve olay odaklı örnekleme koşudan önce belirlenmelidir.
- Az sayıda deneme/dolumdan yürütme güvenilirliği çıkarılamaz. Kapanmış işlem yoksa çıkış/kapanış hattı bu canlı koşuda sınanmamıştır.
- Paper dolumu gerçek borsa dolumu değildir. Çıkış, emir kuyruğu ve piyasa etkisi için geniş kapsamlı genel onay yoktur.
- Önceki negatif tarihsel araştırma kanıtı değişmedi. Yeni strateji eşiği seçimi, tarihsel kârlılık doğrulaması veya bağımsız ileri-OOS iddiası yoktur.

## Dosyalar

v943_freeze_manifest.json, v943_pytest.txt, v943_pytest_initial_alarm_contract.txt, v943_reference_sources, v943_strict_method_hash_proof.json, v943_live_run.log, v943_health_samples.jsonl, v943_paper_15dk_summary.json, v943_test_results.json ve yeni PACKAGE_MANIFEST.json. Diğer v94/v941 dosyaları devralınan tarihsel arşivdir.
