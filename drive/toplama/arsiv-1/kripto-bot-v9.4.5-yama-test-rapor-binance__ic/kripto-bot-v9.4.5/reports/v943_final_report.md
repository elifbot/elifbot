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

Bu bölümdeki 121 sonucu eski host test kaydıdır. Yeni gerçek Docker testi ayrıca aşağıdaki r3 bölümündedir (121 geçti, 11.73s); iki koşunun test sayıları toplanmaz.
Önceki 87 teste 34 yeni sağlık/endpoint/değişmezlik kontrolü eklendi. Test kapsamı: dört niyet tablosu, 0/14.999/15/16s sınırları, yeniden başlatma/yabancı sahip, gerçek nakit/ücret/funding hataları, pozisyon kümesi farkı, ilk emir, iptal, salt-okunurluk, sıkı recovery ve gerçek HTTP handlerı. Endpoint testi iki akışın birbirini ezmediğini doğrular.

İlk test koşusunda eski alarm metnine bağlı bir assert başarısızdı (117 geçti, 1 başarısız). Bu testin beklentisi istenen yeni POSITION_SET_MISMATCH sözleşmesine güncellendi; güvenlik denetimi kaldırılmadı. İlk çıktı saklandı. Son tam test 121/121dir.

## Önceki tamamlanmış 15 dakikalık canlı PAPER koşusu

- Donma UTC: 2026-11-03T09:01:26.971253+00:00. Donmuş kaynak kontrolü başarılı.
- Aktif süre yaklaşık 900.534s; drenaj 0.000s; toplam 900.534s.
- Bu eski 15 dakikalık deney doğrudan Python ileydi. Sonraki r3 Docker deneyi ayrı bölümde kaydedildi.
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
- Maliyet sınırı: sağlık görünümü DB kopyası alır. Küçük DBdeki test, büyüyen defterde veya sık panel sorgusunda gecikme/CPU/RAM maliyetini ölçmüş sayılmaz. r3 bölümünde dar sentetik kopya ölçümü eklendi; tam API/gerçek büyük defter yük doğrulaması yapılmadı.
- Yeni 24 saatlik prospektif PAPER koşusu önceden kaydedilmiş planla BAŞLATILDI; tamamlanmadı. Başlangıç kanıtı ve sınırlar aşağıdaki r3 bölümündedir.
- Az sayıda deneme/dolumdan yürütme güvenilirliği çıkarılamaz. Kapanmış işlem yoksa çıkış/kapanış hattı bu canlı koşuda sınanmamıştır.
- Paper dolumu gerçek borsa dolumu değildir. Çıkış, emir kuyruğu ve piyasa etkisi için geniş kapsamlı genel onay yoktur.
- Önceki negatif tarihsel araştırma kanıtı değişmedi. Yeni strateji eşiği seçimi, tarihsel kârlılık doğrulaması veya bağımsız ileri-OOS iddiası yoktur.

## Dosyalar

v943_freeze_manifest.json, v943_pytest.txt, v943_pytest_initial_alarm_contract.txt, v943_reference_sources, v943_strict_method_hash_proof.json, v943_live_run.log, v943_health_samples.jsonl, v943_paper_15dk_summary.json, v943_test_results.json ve yeni PACKAGE_MANIFEST.json. Diğer v94/v941 dosyaları devralınan tarihsel arşivdir.


# Paketleme r3 — gerçek Docker testi ve 24 saatlik PAPER başlangıcı

Belge anı: 2026-11-03T09:54:57.700034+00:00. **Koşu BAŞLADI; tamamlanmadı.**

## Docker: hata ve düzeltme

- İlk temiz Docker build başarılıydı, fakat pytest 4 collection hatasıyla durdu: `yaml` modülü eksikti. İlk çıktı `v943_docker_24h_start/docker_pytest.txt` içinde korundu.
- Yalnız paketleme/bağımlılık düzeltildi: PyYAML eklendi, Dockerfile test edilmiş sabit sürümleri yükler. Strateji/risk/çıkış/muhasebe ve sağlık runtime Python kaynakları değiştirilmedi.
- Düzeltilmiş gerçek konteynerde **121 passed in 11.73s**. Konteyner kaynak90/paket149 kontrolü geçti; bu 149, imajın dokümantasyon güncellemesinden önceki içeriğidir. Güncel ZIP kendi yeni manifestiyle doğrulanır.
- Docker kendi HEALTHCHECK komutunu gerçekten çalıştırdı: **healthy**, ilk kayıtların ExitCode değeri 0. Ayrı gözlemcinin HTTP200 çıktısıyla karıştırılmadı.
- Sandbox Docker bridge/iptables kapalı: bu deney `--network=host` ile yapıldı; varsayılan bridge ve `docker compose up` ayrıca doğrulanmadı.
- Sabit imaj: `sha256:2d00ac1d88982dccfdf938e18c10a9f6ae702000b1909892dfaef79abfe0da9a`.

## Önceden kaydedilmiş 24 saat planı

- Plan kaydı UTC: **2026-11-03T09:51:12.044050+00:00**; konteyner başlangıcı UTC: **2026-11-03T09:51:31.424232461Z**. Plan koşudan önce yazıldı.
- Plan kimliği: `fa0ee81b69f925c465d4a86178ec8f5813c3b8afc8cf59d11eafae5e5518660f`. Dosyanın SHA-256 değeri: `0dd8a0e0f8c114255ad6356f46d5f3a579ea9e822db86c726df9b8b4d3e3e589`.
- **86.400 saniye aktif + en fazla 600 saniye drenaj**, yeniden başlatma yok. Tahmini aktif bitiş 4 Kasım 2026 12:52 Türkiye saati civarı; gerçek tamamlanma süre/faz/çıkış kanıtıyla ayrıca değerlendirilecek.
- Yeni boş PAPER defteri; gerçek borsa emri yok. Aynı kaynak/config; gate gevşetme, zorla sinyal/dolum veya sonuç elde edene kadar uzatma yok.
- Kaynak donması: `v943_packaging_freeze_manifest.json` / 90 dosya; config SHA ve observer SHA plan içinde. Bu manifestte devralınmış `live_plan` alanı eski 900 saniyelik deneye aittir; **yeni deney planı `v943_24h_frozen_plan.json` dosyasıdır**.
- Salt-okunur DB taraması 0,25s; PENDING varken `/health` 0,5s, yokken 5s; `/api/state` 15s; Docker durumu 20s. Gerçek zaman damgaları ve API gecikmeleri saklanır; bu aralıklar sürekli/boşluksuz gözlem garantisi değildir.
- Aranan olaylar: aynı niyet kimliğiyle genç/sahibi bu süreç olan PENDING + HTTP200/IN_FLIGHT/reconciled=false; sonraki terminal durum; en az bir doğal paper giriş dolumu ve doğal tam kapanış. Terminal/ücret/defter bağlantıları son analizde ayrıca denetlenir; yalnız sayaçlar nihai kabul sayılmaz.
- Süre bitip olaylar eksikse **YETERSİZ GÖZLEM**. Kesinti olursa **KESİLDİ**, tamamlanmış 24 saat sayılmaz. Sandbox sürekliliği garanti edilmez. Her 503 ve ilk başarısız test korunur.

### Teslim anındaki durum (canlı güncellenen dosya değil)

`{"health_samples": 40, "http_200": 40, "http_503": 0, "http_errors": 0, "owned_young_pending_http200": 0, "real_closed_trades": 0, "natural_entry_fills": 0, "pending_events": 0, "db_read_errors": 0}`
- Durum: **RUNNING**, son gözlenen aktif süre yaklaşık 193.3s; 24 saat tamamlanması **false**.
- Canlı PENDING eşleşmesi: False; giriş/kapanış döngüsü: False. İlk 15 dakikalık testin 59/59 sayısı bu yeni sayaçlara eklenmedi.
- Güncellenen ham kayıtlar: `/home/user/v943-long-paper-evidence` içindeki `progress.json`, `health_events.jsonl`, `pending_events.jsonl` (olay oluşursa), `state_samples.jsonl`, `docker_health_history.jsonl`, `paper24h_console.log`. ZIP yalnız bu teslim anının başlangıç kanıtlarını içerir; ilerideki sonuçları içermez.

## Kopyalama maliyeti — dar sentetik ölçüm

| Yaklaşık ek veri | n | p50 ms | p95/maks ms | CPU ort. ms | Süreçte o ana kadarki tepe RSS KiB |
|---|---:|---:|---:|---:|---:|
| 0 MiB | 10 | 0.700 | 2.514/2.514 | 0.886 | 27384 |
| 1 MiB | 10 | 1.225 | 1.495/1.495 | 1.266 | 28040 |
| 10 MiB | 10 | 7.616 | 20.167/20.167 | 8.850 | 38832 |
| 100 MiB | 5 | 88.807 | 101.187/101.187 | 88.678 | 137844 |

Bu, sabit imajda padding ile büyütülmüş DBde izole ledger sağlık-kopyası ölçümüdür. Gerçek işlem nüfusu, tam HTTP/panel yükü veya ayrı-thread yarış testi değildir. Az n ile güvenilir kuyruk-gecikmesi tahmini yapılmaz. RSS sütunu çağrı başına bellek farkı değil, süreçte birikimli tepe değerdir. Thread-token kayıt penceresi sınırı değişmedi.

**Gerçek para/operasyonel hazırlık/kârlılık onayı hâlâ yok.**
