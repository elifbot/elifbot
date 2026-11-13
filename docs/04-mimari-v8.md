# 04 · v8 mimarisi

## Akış

```
feed.py (sentetik | csv | canlı WS)
   → types.Tick
   → signals.Tape (kayan pencere)  →  SinyalKomitesi (3 dedektör, skor ≥ 0.55)
   → risk.RiskYoneticisi (10 kapı)  →  sizing.boyut_hesapla (500 $ notional + stop fiyatı)
   → broker.SimuleBorsa (teminat fiziği, komisyon, kayma, CROSS tasfiye)
        veya exchanges.{binance,okx} (gerçek emir)
   → engine.Motor (pozisyon, stop yönetimi, zombi çıkışı)
   → ledger.Defter (append-only JSONL, idempotent, uzlaştırma)
```

## Modüller

| Dosya | Sorumluluk | Kritik karar |
|---|---|---|
| `config.py` | Kural + motor ayarları | Altı sayı burada; `dogrula()` ihlali reddeder |
| `types.py` | Tick, Pozisyon, Emir, Enstruman | Borsadan bağımsız şema |
| `sizing.py` | Miktar, stop fiyatı, tasfiye | Adım yuvarlaması → gerçek notional |
| `risk.py` | 10 giriş kapısı, durdurucular | "Emir sayısı sınırsız, teminat sınırlı" |
| `signals.py` | 3 dedektör + komite | Kovalama yasağı riskte, sinyalde değil |
| `broker.py` | Simülasyon borsası | Teminat reddi + borsada duran stop + tasfiye |
| `engine.py` | Pozisyon yaşam döngüsü | Stop **borsada**, Python'da değil |
| `ledger.py` | Jurnal, uzlaştırma | Aynı olay iki kez yazılmaz |
| `feed.py` | 3 besleme kaynağı | Motor kaynağı bilmez |
| `exchanges/*.py` | Binance/OKX | CROSS + 10x + reduceOnly stop |

## Eski paketten ayrılan 5 nokta

1. **Stop borsada durur.** `_stop_koy()` giriş anında `STOP_MARKET reduce_only` gönderir.
   Kâr koruması `amend` ile stop'u yukarı taşır. Tick kontrolü yok → gap'te zarara dönüş yok.
2. **Teminat fiziği.** `SimuleBorsa.emir_gonder()` serbest teminatı kontrol eder; yetmezse
   `TEMINAT_YETERSIZ` döner. Hayalî 6.150 $ teminat oluşamaz.
3. **Hesap kaldıracı raporlanır.** `risk.kasa_raporu()` her an `kaldirac` ve
   `tasfiye_mesafesi_pct` verir.
4. **Kovalama yasağı tek yerde.** Son 30 sn'de %1.2'den fazla hareket varsa o yöne giriş yok —
   v7'nin fikri korunur, ama "her şeyi eleyen" hâli değil.
5. **Operasyonel durdurucular.** Veri bayat, saat kayması, red oranı > %25 → işlem durur.
   Bunlar ticaret kuralı değil, güvenliktir.

## v8'in ölçülen ilk sonucu (15 dk, 120 sembol)

| Metrik | Değer |
|---|---|
| Kapanan | 18 |
| WR | %55.6 |
| En kötü tek işlem | **−10.95 $** (eski motorlarda −20.00 $) |
| En iyi tek işlem | +11.19 $ |
| Eşzamanlı pozisyon | 19 (teminat reddi: 90 giriş engellendi) |
| Hesap kaldıracı | 9.46x |
| Tasfiye | 0 |

## Bilinen sınırlar

- Sinyal seti ölçülmüş bir kenar değil; gerçek veriyle walk-forward gerekir.
- Funding ve likidasyon cezası simülasyonda basitleştirilmiş.
- Canlı adaptörler ağa çıkmadan test edildi (imza/parametre); entegrasyon testi gerekir.
