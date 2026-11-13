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
