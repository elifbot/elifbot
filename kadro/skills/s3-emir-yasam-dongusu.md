# S3 · Emir yaşam döngüsü

1. `clientOrderId` üret (idempotency anahtarı).
2. Post-only dene; `maker_bekleme_ms` içinde dolmazsa taker'a geç.
3. Dolum sonrası **aynı anda** stop emri koy (reduceOnly).
4. Kısmi dolumda kalan miktar için emri güncelle; asla "tahmini" miktarla devam etme.
5. Amend → başarısızsa iptal+yeniden koy → o da olmazsa pozisyonu kapat.
6. Her adımı deftere yaz (`ledger.Defter`), yeniden başlatmada uzlaştır.

Kabul: kaos testinde (rastgele timeout) çift pozisyon veya sahipsiz stop = 0.
