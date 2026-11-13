# Gizlilik / sır temizliği

## Ne oldu

Drive arşivleri (`toplama 1–4`) depoya alınırken GitHub **push koruması** iki gerçek anahtar
tespit etti ve push'u reddetti:

| Dosya | Tür |
|---|---|
| `drive/toplama/arsiv-4/toplama 4/ayarlar.json` | Google AI Studio API anahtarı (`AQ.Ab8RN6…`) |
| `drive/toplama/arsiv-4/toplama 4/Yeni Metin Belgesi.txt` | Aynı türde 3 anahtar |

Tarama genişletildi: 13 dosyada **17 anahtar** maskelendi (`***REDACTED***`), 0 dosya silindi.
Özel anahtar (PEM) ve `private_key` bloğu bulunmadı.

## Yapılan temizlik

| Desen | Ne |
|---|---|
| `AQ.…` | Google AI Studio anahtarı |
| `AIza…` | Google API anahtarı |
| `sk-…` | OpenAI tarzı |
| `ghp_/gho_/…` | GitHub token |
| `xoxb-…` | Slack token |
| `AKIA…` | AWS erişim anahtarı |
| `api_key = "…"` vb. | 13 atama maskelendi |

Kodun kendisi korundu; yalnızca değerler maskelendi. Doğrulama betiği: aynı desenlerle
tam depo taraması → **0 kalan**.

## Senin yapman gereken (önemli)

Bu anahtarlar bir süre **açık metin** olarak Drive'da ve senin makinende durdu. Depoya
girmedi (push reddedildi, temizlendi) ama:

1. **Google AI Studio** anahtarlarını iptal et, yenisini üret.
2. **Binance / OKX** API anahtarların arşivlerde geçtiyse **iptal et**; yenilerinde
   *çekim yetkisi kapalı* + IP kısıtı kullan.
3. Bundan sonra: anahtarları `config.json`'a yazma, `.env` kullan (`.gitignore`'da).
4. GitHub'da **Secret scanning** açık kalsın — bu sefer işe yaradı.

## Kural

Depoya giren hiçbir dosyada canlı anahtar olmayacak. `anahtar`, `api_key`, `secret`,
`passphrase` alanları **boş** veya `***REDACTED***` olacak.
