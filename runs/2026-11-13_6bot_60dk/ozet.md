# 60 dakikalık 6-bot koşusu — özet

- **Besleme:** SENTETİK (bu ortamda OKX/Binance'e ağ erişimi yok). Sonuç **kenar (edge) ölçümü değildir**;
  motor davranışı, risk kuralı uyumu ve kasa/kaldıraç dinamiği ölçümüdür.
- **Piyasa zamanı:** 60 dk · bucket 0.5s · adım 7200 · seed 20261113
- **Evren:** 510 sembol (ilk 30 → BOT1-5, hepsi → BOT6)
- **Tick satırı:** 1480892 · **kapanan işlem:** 211
- **Duvar süresi:** 228.8 sn (hızlandırılmış replay)

| # | Bot | Kural seti | Kasa | Realize | Açık PnL | Açık | Kapanan | WR | PF | Teminat | Kaldıraç | MaksDD |
|---|-----|-----------|------|---------|----------|------|---------|----|----|---------|----------|--------|
| 1 | BOT 1 · TURBO v1 (30 sembol) | v1 | 952.95 | -28.87 | -18.18 | 9 | 46 | 65% | 0.82 | 450 | 4.7x | -69.06 |
| 2 | BOT 2 · OMEGA v1 (30 sembol) | v1 | 990.51 | +0.00 | -9.49 | 19 | 0 | 0% | - | 950 | 9.6x | -9.49 |
| 3 | BOT 3 · ÜÇ-R (v5.1 · 30 sembol) | v5.1 | 1023.02 | +23.02 | +0.00 | 0 | 22 | 82% | 1.59 | 0 | 0.0x | -36.60 |
| 4 | BOT 4 · DÖRT (v6 · 30 sembol) | v6 | 1035.31 | +35.73 | -0.42 | 2 | 36 | 78% | 1.48 | 100 | 1.0x | -28.41 |
| 5 | BOT 5 · BEŞ (v7 · 30 sembol) | v7 | 1015.22 | +15.48 | -0.26 | 1 | 37 | 57% | 1.22 | 50 | 0.5x | -35.61 |
| 6 | BOT 6 · ALTI (TURBO v1 kodu · TÜM PİYASA) | v1 | 1105.12 | +55.26 | +49.86 | 21 | 70 | 70% | 1.26 | 1050 | 9.5x | -41.84 |

> Kaldıraç = (kullanılan teminat × 10) / kasa. 1.0x = kasa kadar notional; 12x = kasanın 12 katı
> notional. Cross marjinde bu oran, %8.3 ters harekette kasanın tamamının gitmesi demektir.
