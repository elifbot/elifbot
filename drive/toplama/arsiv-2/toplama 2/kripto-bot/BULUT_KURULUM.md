# ☁️ Bulut Kurulumu — Botu 7/24 Çalıştırma

Bilgisayarınız kapalıyken bile işlem yapması için bot bir bulut sunucuda çalışmalıdır.
En ucuz-güvenilir yol: **VPS + Docker** (aylık ~$5-6).

---

## Seçenek 1: VPS + Docker (ÖNERİLEN)

### Adım 1 — Sunucu açın
Hetzner, DigitalOcean veya Contabo'dan en küçük Linux (Ubuntu 22.04/24.04) sunucuyu açın.
**Konum olarak Almanya/Finlandiya seçin** (Binance/OKX sunucularına yakın = daha hızlı).

### Adım 2 — Sunucuya bağlanıp Docker kurun

```bash
ssh root@SUNUCU_IP
apt update && apt install -y docker.io docker-compose-plugin git
```

### Adım 3 — Botu yükleyin

```bash
git clone <reponuz> kripto-bot   # veya dosyaları scp ile atın
cd kripto-bot
cp .env.example .env
nano .env     # MODE=paper ile başlayın! Anahtarları girin.
```

### Adım 4 — Başlatın (arka planda, yeniden başlatsanız bile çalışır)

```bash
docker compose up -d --build
docker logs -f kripto-bot        # canlı izleme (çıkış: Ctrl+C)
```

### Günlük komutlar

```bash
docker logs --tail 100 kripto-bot   # son 100 satır
docker compose restart              # yeniden başlat
docker compose down                 # durdur
docker compose up -d --build        # güncelleme sonrası
```

---

## Seçenek 2: Docker'sız (systemd servisi)

```bash
apt install -y python3 python3-pip git
cd kripto-bot && pip install -r requirements.txt
cp .env.example .env && nano .env
```

`/etc/systemd/system/kripto-bot.service`:

```ini
[Unit]
Description=Kripto Bot
After=network.target

[Service]
WorkingDirectory=/root/kripto-bot
ExecStart=/usr/bin/python3 -m src.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now kripto-bot
journalctl -u kripto-bot -f   # canlı izleme
```

---

## Seçenek 3: Render / Railway (ücretsiz deneme için)

1. Bu klasörü GitHub'a yükleyin (` .env` dosyasını ASLA yüklemeyin!)
2. Render.com → New → Background Worker → repo'yu seçin
3. Build: `pip install -r requirements.txt` · Start: `python -m src.main`
4. Environment sekmesine `.env` değerlerini tek tek girin (MODE=paper!)

> Ücretsiz planda uyku modu olabilir; gerçek kullanım için VPS önerilir.

---

## 🔒 Güvenlik Kontrol Listesi

- [ ] `.env` dosyası Git'e YÜKLENMEDİ (`git status` ile kontrol edin)
- [ ] Borsa API anahtarında **withdraw (çekim) izni KAPALI**
- [ ] API anahtarına **IP kısıtlaması** (sunucu IP'si) açık
- [ ] Önce en az 2 hafta `paper`, sonra `testnet`, en son `live`
- [ ] `live`'a geçerken `islem_basina_risk_yuzde` değerini küçük tutun (%0.5-1)
- [ ] Sunucuda güvenlik duvarı açık: `ufw allow ssh && ufw enable`
- [ ] Telegram bildirimleri aktif (ne yaptığını hep görün)
