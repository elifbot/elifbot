# v7 Değişiklikleri

## Düzeltilen hatalar
1. **Backtest kaldıracı 5x'e kırpıyordu** (`min(leverage, 5)`): 20x sonuçlar gerçeğinden çok yumuşaktı. Artık gerçek notional K/Z kullanılıyor.
2. **%5 stop, 20x'te likidasyondan sonra kalıyordu** (20x likidasyon ≈ %4.5). Stop artık likidasyon mesafesinin %70'ini aşmaz (20x → %3.15; 10x/5x → %5). Executor + backtest + borsa stop emri aynı değeri kullanır.
3. **Günlük zarar limiti fiyat % ile ölçülüyordu**; artık HESAP bakiyesine göre (pnl_usdt / bakiye).

## Eklenenler
- Sert tavanlar (config.yaml `risk:` altında): `max_kademe`, `mutlak_max_pozisyon`, `ayni_yon_max_pozisyon`, `toplam_marj_tavani_yuzde`, `haftalik_max_zarar_yuzde`, `likidasyon_stop_tamponu`
- `src/reconcile.py` + `Executor.reconcile_with_exchange()` + `ExchangeManager.fetch_open_positions()`: açılışta ve 5 dakikada bir bot kaydı ↔ borsa karşılaştırması (hayalet pozisyon siler, sahipsiz pozisyon için alarm verir). Paper modda devre dışı.
- Backtest'e likidasyon simülasyonu
- Test bölümü 29 (95/95 test geçiyor)

## v7.1 — Para Akışı Tetikleyicisi
- `config.yaml > sinyal:` `para_akisi_tetik`, `para_akisi_esik` (50), `tetik_indikator_min` (10), `tetik_min_toplam` (15)
- Para akışı skoru ≥ +50 (veya ≤ −50) + indikatör aynı yönde ≥ 10 + toplam skor aynı yönde ≥ 15 ise, toplam skor 55'e ulaşmasa da giriş yapılır. 1h/4h MTF filtresi ve haber vetosu yine geçerlidir.
- Kapatmak için `para_akisi_tetik: false`.
- Backtest'e funding maliyeti eklendi (`funding_8h_pct`, `bar_minutes`).
- Test bölümü 30 (toplam 101 test geçiyor).

## Henüz yapılmayanlar
- `clientOrderId` ile idempotent emir yok; rejim (ADX) filtresi yok; spoofing teyidi (CVD) yok
- Gerçek veriyle walk-forward çalıştırılmadı
