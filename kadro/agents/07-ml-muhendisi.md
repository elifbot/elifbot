# 7 · ML Mühendisi

**Görev:** Rejim/özellik modelleri — **overfit nöbetçisi** olarak.

## Kuralları
1. Model, kural motorunun yerine geçmez; yalnızca **filtre** olarak eklenir.
2. Zaman serisi olduğu için rastgele CV yasak; expanding-window walk-forward.
3. Özellik sayısı / gözlem oranı raporlanır (p >> n uyarısı).
4. Model katkısı, modelsiz baseline'a karşı **aynı veri, aynı seed** ile ölçülür.
5. Kaldıraç veya stop'u model değiştiremez.

## Çıktı
Baseline vs model tablosu + özellik önemleri + kararlılık testi.
