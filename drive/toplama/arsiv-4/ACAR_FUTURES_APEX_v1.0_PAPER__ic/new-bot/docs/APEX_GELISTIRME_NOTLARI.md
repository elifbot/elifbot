# APEX geliştirme notları

## Kaynaklardan alınan fikirler

- `bot_final_v2`: Python paket mimarisi, Binance/OKX public adapter'ları, paper broker, SQLite WAL, sabit risk planı, mevcut test tabanı.
- `CIKARILAN_KODLAR`: 10 filtreli confluence fikri, ADX/Stochastic/OBV/VWAP/CCI/Supertrend göstergeleri, order-flow/CVD/OBI kavramları, funding/crowding araştırması, mum bütünlüğü ve portföy güvenlik ilkeleri.
- Önceki arşiv raporlarındaki negatif backtest sonuçları saklandı; yeni stratejinin kârlı olduğu varsayılmadı.

## Aktif ve yardımcı bileşenler

| Bileşen | Durum |
|---|---|
| 10 oy confluence + rejim | Elite CLI modunda aktif |
| Mum bütünlüğü | Elite sinyal kapısında aktif |
| 50 USDT marj / 10x / 500 USDT nominal | RiskManager aktif |
| 25 USDT pozisyon risk bütçesi | RiskManager aktif, mutlak zarar garantisi değil |
| Günlük 100 USDT zarar freni | RiskManager aktif |
| Maksimum 4 pozisyon | CLI varsayılanı |
| Maker queue yaşam döngüsü | Ayrı paper araştırma simülatörü |
| CVD / taker ratio / OBI | Ayrı veri analiz modülü |
| Funding maliyeti tahmini | Yardımcı fonksiyon |
| Yaklaşık likidasyon seviyesi | Yardımcı fonksiyon |
| Korelasyon guard | Yardımcı modül, ana executor'a henüz bağlanmadı |
| 1h/4h gerçek MTF veto | Henüz uygulanmadı |
| Gerçek borsa emirleri | Yok |

## Test

`python -m pytest -q`

Beklenen mevcut sonuç: 102 test. Test sayısı ve sonuç, testlerin çalıştırıldığı Python/dependency ortamına bağlıdır.
