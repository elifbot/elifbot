# S4 · Stop doğrulama (−10 $)

1. Giriş fiyatı `p`, notional `N=500`.
2. Hedef: `net = yon*(stop/p - 1)*N - gidis_donus_komisyon = -10`.
3. `stop_fiyati()` bunu üretir; kayma tamponu (5 bps) eklenir.
4. Test: `test_stop_net_zarari_10_dolar` → tolerans ±0.6 $.
5. Replay sonrası: `en_kotu_tek_islem` −10.6 $ ile −0.5 $ arasında olmalı.
6. Daha kötüsü varsa: gap var → likidite filtresini yükselt veya stop tamponunu büyüt.

Kabul: son 1.000 işlemde −11 $'dan kötü işlem oranı < %0.5.
