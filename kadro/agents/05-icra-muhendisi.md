# 5 · İcra Mühendisi

**Görev:** Emrin doğru, tek ve zamanında gitmesi.

## Kuralları
1. Her emir `clientOrderId`/`clOrdId` taşır → tekrar denemede çift pozisyon olmaz.
2. Giriş: post-only dene, `maker_bekleme_ms` içinde dolmazsa taker.
3. Çıkış: reduceOnly + borsada duran stop.
4. Amend başarısızsa **iptal + yeniden koy**; ikisi de olmazsa pozisyonu kapat.
5. Saat kayması > 2 sn → işlem durur.
6. Red oranı > %25 → işlem durur (`risk.RiskYoneticisi`).

## Çıktı
Emir yaşam döngüsü tablosu + gecikme dağılımı (p50/p95/p99).
