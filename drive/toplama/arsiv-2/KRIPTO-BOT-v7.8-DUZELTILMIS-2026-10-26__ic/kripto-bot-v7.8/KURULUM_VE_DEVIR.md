# KRIPTO-BOT v7.8 — Devreye Alma Rehberi (Adım Adım)

> Bu rehber, `KRIPTO-BOT-v7.8-MAIL-PAKETI.zip` içindeki projeyi **sıfırdan çalışan bir 7/24 bota** çevirmek için hazırlandı.
> ViraColor Excel çalışması (v2.0) ikinci aşamada; bu rehber bitince ona geçiyoruz.

---

## 0) Şu an neredeyiz? (bu oturumda doğrulanan gerçekler)

| Kontrol | Sonuç |
|---|---|
| `python -m pytest tests` | ✅ **141 test geçti** |
| `python test_hizli.py` | ✅ **101/101 senaryo geçti** |
| `MODE=paper python -m src.main` | ✅ Çalıştı — **516 USDT perpetual parite**, Binance 507 / OKX 267 |
| Canlı veri akışı | ✅ ~43.000 tick/dk, gecikme **~69 ms** (Binance taker+book, OKX trades+books) |
| `/health` ve `/metrics` | ✅ `http://SUNUCU:8502/health` → `healthy:true`, `journal_mode:wal` |
| Web paneli | ✅ `http://SUNUCU:8501` → paper kasa **$100.000** görünüyor |
| Gerçek paper işlem döngüsü | ✅ 3 dakikada 5 SHORT açtı (MANTRA, HMSTR, JASMY, BLUR, SONIC) — 10x, $50 marj, %8 stop, gerekçe: PARA AKIŞI TETİKLEYİCİSİ |
| `test_bot_v7.py` | ⚠️ Paketle gelen bilinen hata: `import bot_v7` (eski tek dosya sürümüne ait). Bu dosya v7.8'de **çalışmaz**, `test_hizli.py` + `tests/` kullanılacak. |
| Banner | ⚠️ Konsolda `v7.7` yazıyor (sadece kozmetik; kod ve config v7.8) |
| `/health` heartbeat bayrağı | ⚠️ İşlemler açılırken `healthy:false / stale_heartbeat` görüldü; bot işlem açmaya devam etti (DB yazımı tazeydi). **Tek başına alarm sebebi sayma** — `deploy/nobetci.sh` bu yüzden DB tazeliğine + servis durumuna bakar. İlk saatte doğrula. |

**Önemli coğrafi not:** Sunucu bulunduğu bölgeye göre Binance'in **451 (restricted location)** cevabını verdiği görüldü. Çözüm: `.env` içinde `BINANCE_PUBLIC_WWW=1` (resmî USDⓈ-M public uçlarını kullanır — bu ayarla 507 Binance paritesi sorunsuz geldi). Kalıcı engel varsa botu **yalnız OKX** ile çalıştırmak da mümkündür (aşağıda Aşama 1-C).

---

## 1) Sunucu gereksinimi

| | Minimum | Önerilen |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Disk | 5 GB | 20 GB SSD |
| İşletim sistemi | Ubuntu 22.04 / 24.04 (Debian 12 de olur) | Ubuntu 24.04 LTS |
| Python | 3.11+ | 3.12 |
| Ağ | Kesintisiz, düşük gecikmeli | Binance/OKX'e yakın lokasyon (Frankfurt/Amsterdam) |

Kendi bilgisayarında denemek için de aynı adımlar geçerli (Windows'ta WSL2 önerilir, çünkü `systemd` ve sinyal yönetimi Linux'ta düzgün çalışır).

---

## 2) Kurulum (5 dakika)

```bash
# 1. Paketi sunucuya kopyala ve aç
scp KRIPTO-BOT-v7.8-MAIL-PAKETI.zip kullanici@SUNUCU:/tmp/
ssh kullanici@SUNUCU
sudo mkdir -p /opt/kripto-bot && sudo chown $USER /opt/kripto-bot
cd /opt/kripto-bot
unzip /tmp/KRIPTO-BOT-v7.8-MAIL-PAKETI.zip     # içinden kripto-bot-v7.8/ çıkar
ls kripto-bot-v7.8                             # README.md  config.yaml  src/  tests/  configs/

# 2. Sanal ortam + bağımlılıklar
sudo apt update && sudo apt install -y python3-venv python3-pip unzip
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r kripto-bot-v7.8/requirements.txt

# 3. Ayarları oluştur (.env.ornek dosyasını kopyala ve doldur)
cd kripto-bot-v7.8
cp .env.ornek .env  &&  chmod 600 .env
nano .env                                      # MODE=paper ile başla, sırları gir
```

Hazır kurulum betiğiyle tek komutta da yapabilirsin: **`deploy/kur.sh`** (bkz. dosya sonundaki Ek-A).

---

## 3) `.env` — tüm anahtarlar tek yerde

API anahtarları **asla** `config.yaml`'a yazılmaz; bot sadece `.env` okur (sır maskeleme açık).

```ini
MODE=paper                     # paper | testnet | live
BINANCE_PUBLIC_WWW=1           # coğrafi blok (451) varsa 1 bırak
DASHBOARD_HOST=0.0.0.0
PORT=8501
DASHBOARD_TOKEN=en-az-16-karakter-rastgele-token

# --- Bildirim (bu kurulumda işlem açmadan önce zorunlu doğrulanır) ---
REQUIRE_NOTIFICATIONS=1
NOTIFICATION_STARTUP_TEST=1
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
WHATSAPP_PHONE=                # +90...
WHATSAPP_API_KEY=              # sağlayıcı yöntemi 1
WHATSAPP_PHONE_NUMBER_ID=      # Meta Cloud yöntemi 2
WHATSAPP_CLOUD_TOKEN=          # Meta Cloud yöntemi 2
WHATSAPP_WEBHOOK_URL=          # webhook yöntemi 3
DISCORD_WEBHOOK_URL=
PAGERDUTY_ROUTING_KEY=

# --- Yalnız testnet/live için ---
# BINANCE_API_KEY= / BINANCE_API_SECRET=
# OKX_API_KEY= / OKX_API_SECRET= / OKX_API_PASSPHRASE=
# LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY     # live'da zorunlu
```

---

## 4) Aşama 1 — PAPER (gerçek veri, sanal para) ✅ buradan başla

```bash
MODE=paper .venv/bin/python -m src.main
```

Açılışta görmen gerekenler:

```
🤖 KRIPTO-BOT ... başlatılıyor | MOD: PAPER | 516 USDT perpetual
💰 Paper kasa: $100,000.00
🩺 Sağlık & Prometheus sunucusu aktif: http://0.0.0.0:8502/health & /metrics
💓 1dk | tick=43316 | borsa=BINANCE | gecikme=69ms | ...
```

**Süreli test oturumu** (bu kabul testi tam 1 saattir):

```bash
MODE=paper PAPER_SESSION_HOURS=1 .venv/bin/python -m src.main
```
> `PAPER_SESSION_HOURS` yalnız paper'da geçerlidir; 0 = süresiz. Süre dolunca yeni girişler kesilir, paper pozisyonları kapatılır ve nihai rapor yazılıp gönderilir. Terminal/Arena arka planı yerine kalıcı Linux host + systemd kullanılmalıdır; `SIGKILL` hiçbir Python programı tarafından yakalanamaz.

**Aşama 1-C — yalnız OKX ile çalıştırma:** `config.yaml` → `genel.borsalar: ["okx"]`, `genel.semboller` listesini OKX'te olan paritelerle bırak. (Binance 451'i tamamen aşmak istersen bu yol.)

**Paper kabul kriteri (öneri):** 48 saat kesintisiz çalışma, `sigorta=AKTİF`, tick akışı düşmüyor, `open_positions` mantıklı (maks 6), `pnl_usdt_sum` raporlanıyor, panelde equity eğrisi oluşuyor. Bu sağlanmadan testnet'e geçmemek gerekir.

---

## 5) Aşama 2 — TESTNET (gerçek emir, sahte para)

1. Binance/OKX **testnet** hesabı aç, API anahtarlarını al.
2. `.env`: `MODE=testnet` + ilgili API anahtarları.
   ⚠️ `config.yaml`'da `borsalar: ["binance","okx"]` olduğu sürece **her iki borsanın** anahtarı da zorunludur (bot bunu doğrular). Tek borsa ile gideceksen listeyi tek elemana indir.
3. Çalıştır: `MODE=testnet .venv/bin/python -m src.main`
4. İzle: panelde `mode: TESTNET`, `/health` → `active_exchange`, pozisyon aç/kapa döngüsü, `recent_trades` kayıtları, `trades_total` artıyor mu.

---

## 5.5) Performans — evren büyüklüğü (bu oturumda ölçüldü, önemli)

Aynı sunucuda iki farklı ayarla ölçüm:

| Ayar | Tick | Gecikme | `/health` | CPU |
|---|---|---|---|---|
| `futures.max_parite: 0` → **516 parite** | ~101–138 bin/dk | 69 ms → **7.552 ms** (doygunluk) | ❌ yanıt vermiyor / `stale_heartbeat` | — |
| `futures.max_parite: 100` → **100 parite** | ~7,8 bin/dk | **60 ms** (stabil) | ✅ `healthy:true`, hb 21 sn | %47 (2 vCPU) |

**Sonuç:** 1–2 vCPU'lu VPS'te tüm evren (516 parite) event loop'u doyuruyor; bot işlem açmaya devam ediyor ama `/health` ve heartbeat bayatlıyor, gecikme 7,5 saniyeye çıkıyor. **Öneri:**

```yaml
# config.yaml
futures:
  max_parite: 100        # 2 vCPU icin 100; 4+ vCPU'da 200-250
  ws_grup_boyutu: 50
  tarama_araligi_saniye: 90
```
4+ vCPU / 4 GB'lık sunucuda `max_parite: 250` güvenli sınırdır. `0` (tüm evren) yalnız 8 vCPU üzerinde önerilir.

> Not: 100 pariteye düşürdükten sonra bot, SQLite'tan **5 açık pozisyonu kurtararak** yeniden başladı (`♻️ SQLite'tan 5 açık pozisyon kurtarıldı`) — yani yeniden başlatma pozisyon kaybettirmiyor, kalıcı hafıza çalışıyor.

---

## 6) Aşama 3 — LIVE (gerçek para) — kademeli aç

1. `.env`: `MODE=live`, canlı API anahtarları (borsada **para çekme yetkisi kapalı**, sadece futures işlem), IP kısıtı açık.
2. `LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY` — bu satır olmadan bot **kasıtlı olarak açılmaz** (kolay koruma).
3. İlk 24 saat: kasaya **küçük bakiye** koy, tek parite ile başla (`genel.semboller`), `risk.max_pozisyon` düşük tut.
4. Risk ayarları `config.yaml → risk` bölümünde; v7.8 varsayılanı: **50 USDT marj × 10x, 40 USDT stop (%80), maks 6 pozisyon (aynı yönde 4), günlük -%5 sigorta, haftalık -%12 kilidi**.
5. `firsat_takasi_aktif: false` (v7.8'de kapalı), erken kâr kilidi + zirve kâr koruma aktif — bunları canlıya çıkmadan **değiştirme**; önce paper'da ölç.

**Geri alma / acil durdurma:** Telegram `/kill` (tüm pozisyonları kapat + kilit), `/durdur` (yeni girişi kes), panelde **Kill Switch** düğmesi, ya da `systemctl stop kripto-bot`.

---

## 7) Panel, sağlık ve metrikler

| Servis | Adres | Not |
|---|---|---|
| Web paneli | `http://SUNUCU:8501` | Canlı equity, pozisyonlar, işlem geçmişi, Kill Switch / Duraklat / GC / sembol kapat |
| Sağlık | `http://SUNUCU:8502/health` | `healthy`, `heartbeat_fresh`, `circuit_breaker`, `sqlite.journal_mode` |
| Prometheus | `http://SUNUCU:8502/metrics` | `kriptobot_up`, `equity_usdt`, `open_positions`, `trades_total` … |

**Güvenlik (şart):**
- `DASHBOARD_TOKEN` **boş bırakılırsa** panel API'leri sadece `127.0.0.1` isteklerine açıktır. Dışarıdan erişeceksen token **zorunlu** (en az 16 karakter) ve mümkünse paneli nginx/Cloudflare arkasına + HTTPS'e al.
- Firewall: `8501/8502` portlarını dünyaya açma; VPN veya IP kısıtı kullan.
  ```bash
  sudo ufw allow 22/tcp
  sudo ufw allow from <kendi-IP> to any port 8501,8502 proto tcp
  sudo ufw enable
  ```
- Panel **emir göndermez**: kontrol komutları SQLite kuyruğuna yazılır, ana bot uygular. Bu yüzden paneli durdurmak botu durdurmaz.

---

## 8) 7/24 çalıştırma — systemd (önerilen)

`deploy/` klasöründeki iki dosyayı kullan:

```bash
sudo cp deploy/kripto-bot.service deploy/kripto-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kripto-bot kripto-panel      # ikisini başlat + açılışta otomatik
systemctl status kripto-bot --no-pager
journalctl -u kripto-bot -f                              # canlı log
```

Bot servisi `Restart=on-failure` ile hata/SIGKILL sonrasında 5 sn içinde geri kalkar; planlı süre sonu (`exit 0`) yeniden başlamaz. `SIGTERM` alındığında bot nedeni `reports/termination_requested.json` ve SQLite'a yazar, yeni girişleri durdurur, açık paper pozisyonlarını güvenli kapatır ve `reports/last_exit.json` üretir. `MODE` değiştirmek için `.env`'i düzelt, `sudo systemctl restart kripto-bot` (panel için de aynısı — panel `MODE`'u kendi `.env`'inden okur).

**Basit dış izleme** (5 dakikada bir sağlık kontrolü + Telegram'a alarm) — `deploy/nobetci.sh`, cron:
```bash
*/5 * * * * /opt/kripto-bot/deploy/nobetci.sh
```

---

## 9) Bildirimleri bağlama

- **Telegram (iki yönlü):** `@BotFather` → token; bota `/start` yaz, `getUpdates` ile `chat_id` al → `.env`. Komutlar: `/guncel /pnl /durum /piyasa /rapor /gunluk /pozisyonlar /sigorta /durdur /baslat /kill`.
- **WhatsApp:** üç destekli yöntemden biri gerekir: (1) `WHATSAPP_PHONE` + `WHATSAPP_API_KEY`, (2) `WHATSAPP_PHONE` + Meta `WHATSAPP_PHONE_NUMBER_ID` + `WHATSAPP_CLOUD_TOKEN`, veya (3) `WHATSAPP_WEBHOOK_URL`.
- **Zorunlu açılış testi:** `REQUIRE_NOTIFICATIONS=1` ve `NOTIFICATION_STARTUP_TEST=1` bırakıldığında etkin görünen bir kanalın kimlik bilgisi eksikse ya da gerçek test mesajı teslim edilemezse bot **işlem açmadan kapanır**. Konsolda `Telegram=BAŞARILI` ve `WhatsApp=BAŞARILI` görülmeden bir saatlik oturuma başlanmaz.
- **Discord / PagerDuty:** `DISCORD_WEBHOOK_URL`, `PAGERDUTY_ROUTING_KEY` — ikisi de opsiyonel; PagerDuty varsayılan olarak sadece kritik olayda (sigorta/kill/failover) çalar.

---

## 10) Sorun giderme

| Belirti | Neden / Çözüm |
|---|---|
| `REQUIRE_NOTIFICATIONS=1: bildirim ön kontrolü başarısız` | `.env` içinde Telegram ve/veya WhatsApp kimlik bilgileri eksik. `config.yaml` boole değeri tek başına teslimat sağlamaz. |
| `açılış teslimat testi başarısız` | Anahtar var ancak API reddi/ağ/yanlış chat veya telefon bilgisi var; test başarılı olmadan stratejiyi başlatma. |
| Bot aniden yok oluyor, Python traceback yok | Dış runtime süreci öldürmüş olabilir. Arena/terminal arka planı yerine systemd kullan; `journalctl -u kripto-bot`, `reports/last_exit.json` ve `termination_requested.json` kontrol edilir. `last_exit.json` yoksa SIGKILL/host kaybı kuvvetlidir. |
| `/health` yavaşlıyor, gecikme saniyelere çıkıyor | Evren çok geniş: `futures.max_parite` düşür (bkz. 5.5) |
| `451` / Binance verisi yok | Coğrafi blok. `BINANCE_PUBLIC_WWW=1`, olmazsa `borsalar: ["okx"]` |
| `ConfigError: live modu kilitli...` | `LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY` eksik |
| `testnet modu için okx kimlik bilgileri eksik` | İki borsa listeli; ya OKX anahtarını gir ya `borsalar`'ı tek borsaya indir |
| `test_bot_v7.py → ModuleNotFoundError: bot_v7` | Bilinen paket hatası; bu dosyayı çalıştırma, `pytest tests` + `test_hizli.py` kullan |
| Panel boş / `balance 0` | Panel ile bot **aynı `bot_state.db`**'yi okumalı: ikisini de aynı klasörden çalıştır, `BOT_DB_FILE` tanımlıysa ikisinde de aynı olsun. `mode` uyuşmazlığı da boş ekran verir. |
| `/health` → `stale_heartbeat` ama işlemler sürüyor | v7.8'de heartbeat meta'sı gecikmeli güncellenebiliyor; bot ölmediyse panik yapma. Gerçek ölçüt: servis aktif mi + `bot_state.db` son yazma zamanı (`stat -c %Y`). `nobetci.sh` bunu otomatik yapar |
| Panelde `401` | `DASHBOARD_TOKEN` dolu ama tarayıcı token göndermiyor; ya token'ı panel arayüzüne gir ya token'ı boşalt (yalnız loopback) |
| `database is locked` | Aynı DB'ye iki bot süreci bağlanmış olabilir; tek `src.main` çalıştır (WAL zaten açık) |
| Port çakışması | `PORT=8501` (panel) ve `8502` (health) boş olmalı: `ss -ltnp \| grep -E '8501\|8502'` |
| Log çok uzun | `journalctl --vacuum-size=200M` veya `deploy/logrotate` örneği |

---

## 11) Devreye alma kontrol listesi

- [ ] Sunucu + Python 3.11+ kurulu, `.venv` hazır, `requirements.txt` yüklendi
- [ ] `pytest tests` → 141 test geçiyor (sunucuda da doğrula)
- [ ] `.env` dolduruldu, `chmod 600`, git dışında
- [ ] `futures.max_parite` sunucu gücüne göre ayarlandı (2 vCPU → 100, 4+ vCPU → 250)
- [ ] Paper mode 48 saat kesintisiz çalıştı, `/health` sürekli `healthy:true`
- [ ] Panel + token + firewall (8501/8502 dışarı kapalı)
- [ ] Telegram bildirimi ve `/kill` testi yapıldı
- [ ] systemd servisleri `enable --now`, reboot sonrası otomatik kalkıyor
- [ ] Dış izleme (cron/nobetçi) kurulu
- [ ] Testnet'te en az 100 işlem döngüsü
- [ ] Live'a küçük bakiyeyle, tek parite, düşük pozisyon tavanıyla geçildi

---

## Ek-A) `deploy/kur.sh` ne yapıyor?

Ubuntu/Debian'da sırayla: sistem paketleri → `kriptobot` kullanıcısı → projeyi `/opt/kripto-bot`'a kopyalar → venv + bağımlılıklar → `.env` yoksa `.env.ornek`'ten üretir (rastgele `DASHBOARD_TOKEN`) → systemd birimlerini kurar → `MODE=paper` ile başlatır. Sonunda panel ve `/health` adreslerini yazar.

```bash
sudo bash deploy/kur.sh /tmp/KRIPTO-BOT-v7.8-MAIL-PAKETI.zip
```

**Sonraki aşama:** ViraColor v2.0 — mevcut `FİNAL_600_KOMPONENT` çalışma kitabının (KOMPONENTLER 600 slot / SİPARİŞ KAYITLARI 41 sütun / ÜRETİM FORMU reçete motoru / ÜRÜN TANIMLARI 1-9 komponent) üzerine 9 sütunlu **LB** ve **PPF Lot Detay** sayfalarını ekleyen `.xlsx` sürümü.
