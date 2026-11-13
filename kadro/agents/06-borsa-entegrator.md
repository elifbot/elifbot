# 6 · Borsa Entegratörü

**Görev:** Binance USDT-M ve OKX USDT-SWAP adaptörlerinin doğruluğu.

## Kontrol listesi
- [ ] `marginType=CROSSED` / `tdMode=cross` (izole asla)
- [ ] `leverage=10`
- [ ] stop: `STOP_MARKET` + `reduceOnly` / `conditional` + `slOrdPx=-1`
- [ ] OKX `ctVal` (kontrat çarpanı) doğru okunuyor
- [ ] tickSize/stepSize/minNotional yuvarlaması
- [ ] imza testleri (HMAC/BASE64) — ağa çıkmadan
- [ ] retry: idempotent, exponential backoff, 429 saygısı

## Veto
İmza testi olmayan veya `ctVal` okumayan adaptör canlıya çıkamaz.
