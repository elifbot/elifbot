# 05 · Test protokolü

## Katmanlar

| Katman | Ne | Komut |
|---|---|---|
| L1 Kural | 1000/50/10x/CROSS/limitsiz/−10 | `pytest bot/tests/test_v8_kural.py` |
| L2 Borsa fiziği | teminat reddi, gap stop, CROSS tasfiye | `pytest bot/tests/test_v8_borsa.py` |
| L3 Adaptör | imza, ctVal, conditional emir | `pytest bot/tests/test_v8_borsa_adaptor.py` |
| L4 Motor davranışı | 60 dk replay, 6 bot | `replay_6bot.py --dakika 60` |
| L5 Kenar (edge) | **gerçek** tick ile walk-forward | `replay_6bot.py --besleme csv --ticks ...` |
| L6 Kaos | WS kopması, red oranı, saat kayması | `skills/s9` senaryoları |

## L4 — 60 dakikalık koşunun kabul kriterleri

- [ ] Her bot en az 1 işlem üretir (sinyal yolu canlı)
- [ ] `en kötü tek işlem ≥ −11 $`
- [ ] Kullanılan teminat **hiçbir an** kasayı aşmaz
- [ ] Hesap kaldıracı ≤ 10x
- [ ] Tasfiye = 0
- [ ] Kopma = 0, jurnal satır sayısı = rapor kapanan sayısı

## L5 — gerçek veri protokolü (kenar ölçümü)

1. En az **30 gün** kesintisiz tick arşivi (510 sembol ideal, en az 30).
2. Walk-forward: 15 gün eğitim / 7 gün doğrulama / 8 gün test.
3. Her dilimde: işlem ≥ 100, PF > 1.1, maksDD < %15, en kötü işlem ≥ −11 $.
4. Test dilimi **bir kez** çalıştırılır.
5. Sonuç, aynı dönemde "rastgele giriş + aynı stop" baseline'ı ile karşılaştırılır
   (baseline'ı geçemeyen strateji kenar değildir).

## Ölçüm dürüstlüğü

- WR yanında başabaş WR, PF, maksDD zorunlu.
- Realize ve açık PnL ayrı sütun.
- Örneklem < 100 → "yön göstergesi".
- Sentetik koşu → "kenar ölçümü değil" etiketi zorunlu.
- Her rapora veri sha256 + seed yazılır.

## CI

`.github/workflows/ci.yml`: pytest + kural tablosu + 6-bot import smoke + 2 dk replay.
Kırılırsa PR birleşmez.
