# 8 · Güvenlik

**Görev:** Anahtar ve sırların güvenliği.

## Kuralları
- API anahtarı **yalnızca** `.env` (git'e girmez) veya ortam değişkeni.
- Borsa anahtarında **çekim yetkisi kapalı**, IP kısıtı açık.
- Log/jurnal içinde anahtar, imza, passphrase asla yazılmaz.
- Canlı emir kilidi: `ACARBOT_CANLI_ONAY=EVET-RISKI-ANLIYORUM`.
- CI'da secret taraması (gitleaks/trufflehog).

## Veto
Sır sızıntısı, çekim yetkili anahtar veya kilitsiz canlı mod → derhal durdur.
