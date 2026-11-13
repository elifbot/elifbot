# FUSION PRO 4.0 — Full Futures Universe

## Kapsam

Bot artık sabit 100 coin listesine bağlı değildir. Binance ve OKX tarafındaki uygun **USDT/USDC linear futures** enstrümanlarını dinamik olarak keşfeder.

- Binance: USDT-M perpetual + mevcut USDT-M quarterly futures
- OKX: USDT/USDC-settled SWAP + FUTURES
- Yeni listelenen / kapanan enstrümanlar bir sonraki universe refresh'te alınır.

## İki katmanlı takip

1. **Full-universe telemetry:** tüm uygun kontratlar hafif piyasa verisiyle izlenir.
2. **Event-driven deep scan:** anlık fiyat hareketi, hacim, likidite ve aktivite anomalisi gösteren adaylar candle + MTF + orderbook + funding + OI + signal engine'e sokulur.

Bu tasarım "100 coin seç" mantığından farklıdır: botun takip evreni borsa tarafından belirlenir; derin analiz ise o anda hareket eden kontratlara otomatik kayar.

## Neden bütün kontratları aynı anda ağır analiz etmiyoruz?

Her kontrat için 5m + 15m + 1h + 4h candle, orderbook, OI ve funding sorgularını aynı saniyede yapmak gereksiz API yükü ve rate-limit riski yaratır. Bunun yerine bütün evren izlenir, pahalı analiz olay tetiklemeli yapılır.
