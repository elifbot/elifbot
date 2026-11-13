# GitHub kurulumu (adım adım)

## 1. Hesap güvenliği
- GitHub → Settings → Password and authentication → **iki adımlı doğrulamayı** açın (tercihen donanım anahtarı/passkey).

## 2. Repoyu oluşturun
- github.com → **New repository** → ad: `futures-flow-bot` → **Private** → "Add README / .gitignore" seçeneklerini **işaretlemeyin** (hazır geliyor).

## 3. Kodu yükleyin
Zip'i açın, klasörde:

```bash
git init -b main
git add .
git status          # .env, *.db, *.key GÖRÜNMEMELİ. Görünüyorsa DURUN.
git commit -m "ilk sürüm"
git remote add origin https://github.com/KULLANICI_ADINIZ/futures-flow-bot.git
git push -u origin main
```

Kimlik doğrulama için parola yerine **GitHub CLI** önerilir: `gh auth login` (tarayıcıdan giriş).
`.github/CODEOWNERS` içindeki `KULLANICI_ADINIZ` değerini kendi kullanıcı adınızla değiştirin.

## 4. Repo ayarları (Settings)
- **Code security**: *Dependabot alerts* ve *Dependabot security updates* → açın (ücretsiz).
- *Secret scanning / push protection*: public repoda ücretsiz; **private repoda ücretli olabilir** (planınıza bakın).
  Ücretsiz yol: `security.yml` içindeki **gitleaks** zaten her push'ta tarar; ayrıca yerelde `pip install pre-commit && pre-commit install`.
- **Branches → Branch protection** (`main`): PR zorunlu, `CI` kontrolü geçmeli. (Private repoda ücretsiz planda kullanılamayabilir;
  kullanılamıyorsa kendinize "main'e doğrudan push yok" kuralı koyun, dal açıp PR ile birleştirin.)
- **Actions → General**: workflow izinlerini *Read repository contents* (salt okuma) bırakın.
- CodeQL iş akışı sadece **public** repoda çalışır (private için ücretli özellik).

## 5. API anahtarları — repo DIŞINDA
- Yerelde: `.env` (git'e girmez). Sunucuda: `.env` dosyası `chmod 600`, sadece bot kullanıcısı okur.
- Borsada: **withdraw kapalı**, IP beyaz listesi açık, ayrı **alt hesap**, testnet/demo için ayrı anahtar.
- Anahtar yanlışlıkla commit edildiyse: önce borsada **anahtarı silin**, sonra geçmişi temizlemeyi düşünün.

## 6. Günlük çalışma akışı
`git switch -c ozellik-adi` → değişiklik → `git push` → Pull Request → CI yeşil → birleştir.
Strateji eşiklerini değiştirirken PR açıklamasına paper sonuçlarını yazın (neyi neden değiştirdiniz).

## 7. Bulut (daha sonra)
VPS (Docker) → `git clone` → `.env` oluştur → `sudo chown 10001:10001 data` → `docker compose up -d --build`.
Önce `mode: paper`, sonra `testnet`. `live` için `.env` içine bilerek `LIVE_TRADING_CONFIRM=I_UNDERSTAND_THE_RISK` yazılır.
