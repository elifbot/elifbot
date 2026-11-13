# S6 · Veri kalitesi

| Kontrol | Eşik | Aksiyon |
|---|---|---|
| Zaman boşluğu | > 5 sn | uyarı, > 60 sn ise sembolü çıkar |
| Fiyat sıçraması | > %20 tek tick | tick'i işaretle, sinyalde kullanma |
| Tekrar ts | aynı ts + aynı fiyat | tekilleştir |
| Negatif/sıfır hacim | ≤ 0 | at |
| Saat dilimi | UTC | dönüştür, raporda yaz |
| Sembol eşleşmesi | evren listesi | eşleşmeyenleri raporla |

Çıktı: `runs/<etiket>/veri_kalite.json` + sha256.
