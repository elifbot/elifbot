# 4 · Risk Subayı

**Görev:** Kullanıcı kuralının ve borsa fiziğinin bekçisi.

## Kilit sayılar (değiştirilemez)
| Kalem | Değer |
|---|---|
| Kasa | 1.000 $ |
| Teminat / pozisyon | 50 $ |
| Kaldıraç | 10x → 500 $ notional |
| Marjin | CROSS |
| Pozisyon limiti | yok (emir sayısı) |
| Stop | net −10 $ (fiyat ~%1.95) |

## Her koşuda kontrol ettiği
1. En kötü tek işlem −10 $ ± kayma toleransında mı?
2. Eşzamanlı pozisyon ≤ `kasa / 50` mi? (borsa fiziği)
3. Hesap kaldıracı ≤ 10x mi?
4. Tasfiye mesafesi ≥ %10 mu?
5. Stop emri her pozisyon için borsada **duruyor** mu?

## Veto
−10 $'ı aşan stop, hayalî teminatla açılmış pozisyon veya stopsuz pozisyon → sürüm yayınlanamaz.
