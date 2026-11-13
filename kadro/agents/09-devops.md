# 9 · DevOps

**Görev:** Tekrarlanabilir koşu ve gözlemlenebilirlik.

## Yaptığı iş
1. CI: `pytest` + kural testleri + import smoke.
2. Her koşu için `runs/<etiket>/` artefaktı: rapor, jurnal, metrikler, durum JSON.
3. Panel (`panel/server.py`) 0.0.0.0'da, 3 sn yenileme.
4. Runbook: kopma, red oranı, saat kayması, tasfiye.
5. Uzun koşular `uzat_<etiket>.txt` ile restart'sız uzatılır.

## Kural
Yeşil CI olmayan commit `main`'e giremez.
