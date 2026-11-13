# S9 · Olay müdahale (runbook)

| Belirti | İlk kontrol | Aksiyon |
|---|---|---|
| WS koptu | `durum.json.baglanti.kopma` | otomatik yeniden bağlan; 3 denemede olmazsa dur |
| Veri bayat | son tick yaşı > 10 sn | yeni giriş yok, açık pozisyonlar stopta kalır |
| Emir red oranı > %25 | `red` sayaçları | işlem durdur, anahtar/bakiye kontrol |
| Saat kayması > 2 sn | NTP | işlem durdur |
| Tasfiye oldu | `tasfiye_sayisi` | tüm girişleri kapat, kök neden raporu |
| Beklenmeyen PnL sıçraması | kasa eğrisi | defter ↔ borsa uzlaştır |

Kural: şüphede kalırsan **kapat**, açık bırakma.
