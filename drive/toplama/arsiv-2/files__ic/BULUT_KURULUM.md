# ☁️ Bulut Kurulumu — Botu 7/24 Çalıştırma (v7.2)

En ucuz-güvenilir yol: **VPS + Docker** (aylık ~$5-6). Hetzner / DigitalOcean / Contabo, Ubuntu 22.04/24.04.
Konum: Almanya veya Finlandiya (ABD IP'leri Binance vadelide engelli olabilir).

## 1) Sunucuyu güvenli hazırlayın (root ile değil)

```bash
ssh root@SUNUCU_IP
adduser bot && usermod -aG sudo bot
rsync --archive --chown=bot:bot ~/.ssh /home/bot        # SSH anahtarınızı kopyalayın
# /etc/ssh/sshd_config -> PasswordAuthentication no, PermitRootLogin no ; sonra: systemctl restart ssh
ufw allow OpenSSH && ufw enable
```

## 2) Docker kurulumu

`docker-compose-plugin` Ubuntu'nun varsayılan depolarında YOKTUR; resmi betik kullanın:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker bot && newgrp docker
docker compose version
```

## 3) Botu yükleyin

```bash
git clone <reponuz> kripto-bot && cd kripto-bot
cp .env.example .env && chmod 600 .env
nano .env                  # MODE=paper ile başlayın
docker compose up -d --build
docker compose ps          # STATUS "healthy" olmalı
docker compose logs -f --tail 100
```

> Dosya adları: `.env.example` ve `.dockerignore` **noktayla** başlamalı (`_env.example`, `_dockerignore` olarak kalırsa çalışmaz).

## 4) Panele erişim (internete AÇMAYIN)

Docker, yayınlanan portları UFW'yi atlayarak internete açar. Bu yüzden `docker-compose.yml` portları
`127.0.0.1`'e bağlar. Kendi bilgisayarınızdan SSH tüneliyle bakın:

```bash
ssh -L 8501:127.0.0.1:8501 bot@SUNUCU_IP     # sonra tarayıcı: http://localhost:8501
```

## 5) Günlük komutlar

```bash
docker compose logs --tail 100
docker compose restart
docker compose down                  # veriler (named volume) silinmez
docker compose up -d --build         # güncelleme sonrası
docker volume ls                     # kripto-bot_kripto-data = kalıcı veri
```
Yedek: `docker run --rm -v kripto-bot_kripto-data:/d -v "$PWD":/b alpine tar czf /b/yedek.tgz -C /d .`

## 🔒 Güvenlik kontrol listesi

- [ ] `.env` Git'e yüklenmedi (`git status`), dosya izni 600
- [ ] Borsa API anahtarında **withdraw (çekim) KAPALI**, **IP kısıtlaması** sunucu IP'si
- [ ] Panel/health portları yalnızca 127.0.0.1 (`ss -tlnp` ile doğrulayın)
- [ ] SSH: parola girişi kapalı, root girişi kapalı
- [ ] Sıra: en az 2 hafta `paper` → `testnet` → `live`; live'da önce küçük kasa
- [ ] Telegram + Discord/PagerDuty alarmları test edildi (`/durum`, `/kill`)
- [ ] `.env.example` içinde gerçek Telegram chat ID veya anahtar yok
