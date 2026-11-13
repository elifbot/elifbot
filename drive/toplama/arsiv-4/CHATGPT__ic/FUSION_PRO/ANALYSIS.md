# Kaynak kod analizi — FUSION PRO 2.0

## İncelenen güçlü parçalar

### `file_35_market_data.py`
- Binance Spot WebSocket: aggTrade, bookTicker, depth20.
- Binance Futures forceOrder likidasyon akışı.
- Ping/pong, recv timeout, 23 saat proaktif reconnect.
- Reconnect sonrası SQLite state recovery.

**FUSION PRO'ya alınan fikir:** public WS, reconnect, veri yaşı ve market-health yaklaşımı. Ancak ilk sürümde sinyal doğruluğunu kolaylaştırmak için REST snapshot + public WS ayrımı yapıldı; WS, fiyat/BBO katmanı olarak genişletilebilir.

### `file_127_live_runner.py`
- Binance + OKX public/paper mimarisi.
- Multi-exchange failover.
- Maker queue simulator.
- 10-agent / council / counterfactual gibi çok sayıda araştırma kapısı.

**FUSION PRO kararı:** çoklu borsa ve yapay konseyler ana sinyal yolundan çıkarıldı. Bunlar ölçülmeden eklenmiş karmaşıklık ve bağımlılık yaratıyordu. Bunun yerine açıklanabilir puanlama + audit trail kullanıldı.

### `file_94_risk.py`
- ATR/swing stop.
- Likidasyon tamponu.
- Günlük/haftalık zarar limitleri.
- Dynamic leverage.
- Position sizing.

**FUSION PRO'ya alınan fikir:** stop mesafesine göre risk ve kaldıraç. Sabit dolar riskinin küçük hesaplarda tehlikeli olması nedeniyle yüzde-risk tavanı esas alındı.

### `file_101_strategy.py` / `file_147_unified_engine.py`
- MTF, rejim, funding settlement guard, basis, flow exit, confluence, counterfactual telemetry.

**FUSION PRO:** MTF trend consensus + funding + flow + spread/depth + cost edge gate tek omurgaya alındı.

### Araştırma raporları
Kaynak arşivdeki v9.4.1 araştırma raporu adayın negatif sonuç verdiğini açıkça belirtiyor: 378 işlem, -354.98 USDT net ve maksimum 359.68 USDT equity drawdown. Bu nedenle kaynakta bulunan parametreleri "kanıtlanmış kârlı" kabul etmedim.

## Bilinçli olarak kaldırılanlar

- LLM hakemini ana sinyal kapısı yapmak.
- 10 ajanlı tartışmayı deterministik alpha gibi kullanmak.
- Kanıtlanmamış sabit başarı oranları.
- Gerçek emir katmanı.
- Çoklu borsa karmaşasını ilk sürümde zorunlu kılmak.

## Yeni P0/P1 kontroller

1. Kapanmış mum only.
2. Stale data hard gate.
3. Spread hard gate.
4. Funding settlement risk gate.
5. Net edge after fee + slippage + spread.
6. 15m/1h/4h trend consensus.
7. ATR stop + equity-percent sizing.
8. Paper fill slippage.
9. SQLite WAL audit trail.
10. `WHY/WHY_NOT` karar kaydı.

## Kalan geliştirme adayları

- Binance Futures public WS'yi kline/order-book state ile tam birleştirmek.
- Historical OI/funding/taker data cache'ini backtest'e bağlamak.
- Walk-forward + Monte Carlo + stress matrix'i otomatik CI pipeline yapmak.
- Gerçek exchange order layer'ı ancak testnet + uzun live-paper doğrulamasından sonra ayrı modül olarak eklemek.
