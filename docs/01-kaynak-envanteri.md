# 01 · Kaynak envanteri

Bu depodaki her dosyanın nereden geldiği. Amaç: hangi kodun kime ait olduğu ve neyin
değiştirildiğinin denetlenebilir olması.

## 1. Gmail (13.11.2026 18:31)

| Alan | Değer |
|---|---|
| Gönderen | Ömer Acar `<acarbot56@gmail.com>` |
| Konu | ACARBOT · 6 BOT TEK AKIŞ — kod paketi (ACARBOT_6BOT.zip) |
| Ek | `ACARBOT_6BOT.zip` — 157.855 bayt, 53 dosya |
| sha256 | `b0c0426c03d47994c68016def021cf1e8f150e886854de3f2ecf4aac1fbcc687` |

Arşiv: `docs/ACARBOT_6BOT.zip` (değiştirilmedi).
Çalışma kopyası: `bot/acarbot_6bot/` — **stop ve teminat kontrolü yamalandı**, diff:
`yamalar/01-stop10-ve-teminat-fizigi.patch`.

Mailde bildirilen 6 bot:

| # | Bot | Kural seti | Evren |
|---|-----|-----------|-------|
| 1 | TURBO v1 | orijinal v1 motoru | ilk 30 sembol |
| 2 | OMEGA v1 | orijinal v1 motoru | ilk 30 sembol |
| 3 | ÜÇ-R (v5.1) | ÜÇ + LONG hacim eşiği 3,5x + zombi 20 dk | ilk 30 sembol |
| 4 | DÖRT (v6) | süzülmüş indikatör listesi | ilk 30 sembol |
| 5 | BEŞ (v7) | DÖRT-R + kovalama yasağı | ilk 30 sembol |
| 6 | ALTI | TURBO v1 kodu birebir | **510 sembol (tüm piyasa)** |

Mail ayrıca 25 dakikalık koşunun ham dökümünü (`loglar/`), 3 test dosyasının 9/9, 11/11,
9/9 geçtiğini ve "bu bir test sistemidir, canlı para ile çalıştırılmamalıdır" notunu içeriyor.

## 2. Google Drive (bugün yüklenen 31 öğe)

**Depoya alınanlar** (`drive/`, 1.7 MB):

| Dosya | Ne |
|---|---|
| `TUM_BOTLAR_16_FINAL.zip` | 16 botun final sürümleri (phoenix, …) |
| `ACARBOT56_v3.1_Tum_Futures_Bot.zip` | v3.1: turbo_engine, dashboard, cloud bridge, ai_agent |
| `ACARBOT_FUSION_v4.zip` | v4: fusion_bot, acarbot_omega, CI, testler |
| `ACARBOT_OMEGA_v1.0_Kurumsal_Motor.zip` | OMEGA v1 kurumsal motor |
| `4_BOT_TEST.zip` | 4 farklı modelin botu (superbot_final, superbot_v2, deepseek, nemotron) |
| `BOTLAR_BIRLESIK.py` | tüm botların tek dosya birleşimi (209 KB) |
| `SUPER_BOT (2).py`, `acarbot_nihal.zip` | alternatif motor denemeleri |
| `IKI_BOT_FARKLARI_DETAY.md` | TURBO vs OMEGA karşılaştırma analizi |
| `analyze_bots.py` | bot karşılaştırma scripti |
| `README_KURULUM.md`, `YENI_REPO_KURULUM.md`, `kur_yeni_repo.sh` | kurulum notları |

**Repoya alınmayanlar** (250 MB — `uploads.github.com` bu ortamda kapalı olduğu için Release'e
yüklenemedi; dosyalar Drive'da kalıyor, izleri `drive/MANIFEST/` altında):

| Dosya | Boyut | İçerik |
|---|---|---|
| `toplama 1.zip` | 49 MB | v9.4.5 / v9.5.2 / v9.5.3 sürüm arşivleri + patch'ler |
| `toplama 2.zip` | 52 MB | 399 dosya: V10 denemeleri, omnistudio, HTML paneller, ekran görüntüleri |
| `toplama 3.zip` | 102 MB | sürüm arşivi (en büyük) |
| `toplama 4.zip` | 59 MB | sürüm arşivi |

Doğrulama: `sha256sum -c drive/MANIFEST/sha256.txt`.

Bu dört arşiv **açıldı**: içindeki 2.414 kod/doküman/konfig dosyası (31.9 MB)
`drive/toplama/` altına alındı, iç içe zip'ler dahil. İkili dosyalar ve 300 KB üstü
içerik Drive'da bırakıldı; gerekçesi `drive/toplama/excluded.csv` ve
`drive/toplama/README.md` içinde.

Bu dört arşiv **tarihsel sürüm koleksiyonu**dur; içlerinde gerçek piyasa tick verisi yok
(kontrol edildi: patch, zip, html, pdf, jpg). Bu yüzden backtest için kullanılamazlar.

## 3. Neyin nesi yok

- **Gerçek tick arşivi yok.** Ne mailde ne Drive'da ham piyasa verisi var. Bu yüzden kenar
  (edge) ölçümü yapılamadı; yalnızca motor davranışı ölçüldü.
- **API anahtarı yok.** Canlı mod bu yüzden zaten kilitli.
