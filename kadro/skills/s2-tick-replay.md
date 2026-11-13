# S2 · Gerçek tick replay

1. Arşivi hazırla (CSV): `ts,symbol,price,delta_usd,buy_usd,quote_vol_24h`.
   - `ts` saniye (ms ise otomatik çevrilir), USD cinsinden hacim.
2. Kalite kontrolü: `python3 bot/tools/veri_kontrol.py <csv>` → boşluk/aykırı değer raporu.
3. Koş: `python3 bot/tools/replay_6bot.py --besleme csv --ticks <csv> --dakika 60 --etiket <ad>`
4. Rapor `runs/<ad>/` altına düşer; `rapor.json.besleme` alanı "GERCEK PIYASA VERISI" olmalı.
5. Sentetik koşu ile **karşılaştırma** yapılacaksa iki raporu yan yana koy, aynı seed/özellikle karıştırma.

Kabul: raporda veri sha256 + satır sayısı + zaman aralığı yazılı.
