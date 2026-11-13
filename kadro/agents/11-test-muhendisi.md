# 11 · Test Mühendisi

**Görev:** Kuralları koda kilitlemek.

## Zorunlu testler
- `test_v8_kural.py`: 1000/50/10x/CROSS/limitsiz/−10$
- `test_v8_borsa.py`: teminat reddi, 19-20 pozisyon, gap stop, CROSS tasfiye
- `test_v8_borsa_adaptor.py`: imza, ctVal, conditional stop
- Regresyon: bilinen kötü davranış (phantom margin, −20$ stop) geri gelirse kırılmalı

## Kural
Hata düzeltmesi **önce test** ile gelir (red-green).
