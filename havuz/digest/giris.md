# HAVUZ DEMETİ · GIRIS

**Soru:** Giriş sinyalleri: hangi kurulum gerçekten tekrar edilebilir? Hangileri gürültüden ibaret ve neden?

Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; kanıt yoksa 'veri yok' de, uydurma.

#### drive/toplama/arsiv-2/V4_V78_KOD_ANALIZI_VE_RISK_ADAYI_20261031__ic/aday/ws_bot.py:517-523
```
            alanlar = ["ts_utc", "exchange", "symbol", "side", "entry_price",
                       "signal_ret_pct", "signal_rvol", "signal_volume_usd",
                       "durum"] + akis_csv_alanlari()
            satir = {"ts_utc": ts_utc, "exchange": s.exchange, "symbol": s.symbol,
                     "side": s.yon, "entry_price": s.fiyat,
                     "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
                     "signal_volume_usd": s.hacim_usd, "durum": durum}
```

#### drive/toplama/arsiv-2/V4_V78_KOD_ANALIZI_VE_RISK_ADAYI_20261031__ic/aday/ws_bot.py:1062-1068
```
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))
```

#### drive/toplama/arsiv-2/V4_V78_KOD_ANALIZI_VE_RISK_ADAYI_20261031__ic/aday/ws_bot.py:1140-1146
```
        tahmini_cikis_ucreti = pos.qty_base * pos.entry_price * config.TAKER_FEE_RATE
        net_0 = -pos.entry_fee - tahmini_cikis_ucreti
        self.telemetri[anahtar] = {
            "exchange": s.exchange, "symbol": s.symbol, "side": s.yon,
            "opened_at": pos.opened_at, "entry_price": pos.entry_price,
            "qty_base": pos.qty_base, "entry_fee": pos.entry_fee,
            "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
```

#### drive/toplama/arsiv-2/v37_vwap02_paper_paketi_20261030__ic/v37_vwap02_paper_paketi_20261030/ws_bot.py:981-987
```
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))
```

#### drive/toplama/arsiv-2/v37_vwap02_paper_paketi_20261030__ic/v37_vwap02_paper_paketi_20261030/ws_bot.py:989-995
```
        giris_ucreti = config.MAKER_FEE_RATE if limit_doldu else config.TAKER_FEE_RATE
        sonuc = self.portfoy.open_position(
            s.exchange, s.symbol, s.yon, giris_fiyat, MARJ,
            leverage=KALDIRAC,
            now_ms=_simdi if self.signal_enrichment_active else s.ts_ms,
            price_ts=s.ts_ms if self.signal_enrichment_active else None,
            poll_interval_ms=5_000 if self.signal_enrichment_active else 2_000,
```

#### drive/toplama/arsiv-2/v37_vwap02_paper_paketi_20261030__ic/v37_vwap02_paper_paketi_20261030/ws_bot.py:1038-1044
```
        tahmini_cikis_ucreti = pos.qty_base * pos.entry_price * config.TAKER_FEE_RATE
        net_0 = -pos.entry_fee - tahmini_cikis_ucreti
        self.telemetri[anahtar] = {
            "exchange": s.exchange, "symbol": s.symbol, "side": s.yon,
            "opened_at": pos.opened_at, "entry_price": pos.entry_price,
            "qty_base": pos.qty_base, "entry_fee": pos.entry_fee,
            "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/ws_bot.py:1027-1033
```
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/ws_bot.py:1035-1041
```
        giris_ucreti = config.MAKER_FEE_RATE if limit_doldu else config.TAKER_FEE_RATE
        sonuc = self.portfoy.open_position(
            s.exchange, s.symbol, s.yon, giris_fiyat, MARJ,
            leverage=KALDIRAC,
            now_ms=_simdi if self.signal_enrichment_active else s.ts_ms,
            price_ts=s.ts_ms if self.signal_enrichment_active else None,
            poll_interval_ms=5_000 if self.signal_enrichment_active else 2_000,
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/ws_bot.py:1084-1090
```
        tahmini_cikis_ucreti = pos.qty_base * pos.entry_price * config.TAKER_FEE_RATE
        net_0 = -pos.entry_fee - tahmini_cikis_ucreti
        self.telemetri[anahtar] = {
            "exchange": s.exchange, "symbol": s.symbol, "side": s.yon,
            "opened_at": pos.opened_at, "entry_price": pos.entry_price,
            "qty_base": pos.qty_base, "entry_fee": pos.entry_fee,
            "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
```

#### drive/toplama/arsiv-2/Futures_Bot_v4.0_TUNING_GUNCELLEME_20261029__ic/Futures_Bot_v4.0_TUNING_GUNCELLEME_20261029/paper_run/v37_paper_tuning_run_20261029_03/ws_bot.py:958-964
```
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))
```

#### drive/toplama/arsiv-2/Futures_Bot_v4.0_TUNING_GUNCELLEME_20261029__ic/Futures_Bot_v4.0_TUNING_GUNCELLEME_20261029/paper_run/v37_paper_tuning_run_20261029_03/ws_bot.py:966-972
```
        giris_ucreti = config.MAKER_FEE_RATE if limit_doldu else config.TAKER_FEE_RATE
        sonuc = self.portfoy.open_position(
            s.exchange, s.symbol, s.yon, giris_fiyat, MARJ,
            leverage=KALDIRAC,
            now_ms=_simdi if self.signal_enrichment_active else s.ts_ms,
            price_ts=s.ts_ms if self.signal_enrichment_active else None,
            poll_interval_ms=5_000 if self.signal_enrichment_active else 2_000,
```

#### drive/toplama/arsiv-2/Futures_Bot_v4.0_TUNING_GUNCELLEME_20261029__ic/Futures_Bot_v4.0_TUNING_GUNCELLEME_20261029/paper_run/v37_paper_tuning_run_20261029_03/ws_bot.py:1015-1021
```
        tahmini_cikis_ucreti = pos.qty_base * pos.entry_price * config.TAKER_FEE_RATE
        net_0 = -pos.entry_fee - tahmini_cikis_ucreti
        self.telemetri[anahtar] = {
            "exchange": s.exchange, "symbol": s.symbol, "side": s.yon,
            "opened_at": pos.opened_at, "entry_price": pos.entry_price,
            "qty_base": pos.qty_base, "entry_fee": pos.entry_fee,
            "signal_ret_pct": s.ret_pct, "signal_rvol": s.rvol,
```

#### drive/toplama/arsiv-2/Futures_Bot_v37_Deneysel_Paper_SON__ic/futures_bot_v37/ws_bot.py:86-92
```
# CASCADE EŞİĞİ: son 60 saniyede kaç sinyal geldiyse "tasfiye zinciri" sayılır.
# 7 gün kanıtı (104 sembol, nedensel test):
#   eşik 1 (filtresiz) 1593 sinyal %60,1 isabet +0,197%/işlem · 4/8 gün pozitif
#   eşik 2              881 sinyal %70,0 isabet +0,359%      · 5/8 gün
#   eşik 3              592 sinyal %80,7 isabet +0,563%      · 6/8 gün  <- SEÇİLEN
#   eşik 4              519 sinyal %86,3 isabet +0,670%      · 5/6 gün
# Eşik 3: eğitim +0,607 / test +0,459 · bootstrap 2000× %0 negatif
```

#### drive/toplama/arsiv-2/Futures_Bot_v37_Deneysel_Paper_SON__ic/futures_bot_v37/ws_bot.py:111-117
```
#     eşik 2,0 → 16.329 sinyal  -0,035%   (kenar yok)
#     eşik 3,0 →  6.983 sinyal  +0,081%
#     eşik 4,0 →  3.468 sinyal  +0,233%  %71,1 isabet · test +0,069  <-- SEÇİLEN
#     eşik 5,0 →  2.209 sinyal  +0,441%  %68,4 isabet · test +0,039
#     eşik 6,0 →  1.540 sinyal  +0,560%  ama sinyaller 2 güne sıkışıyor
# 4,0 seçildi: günde ~590 sinyal (15 dk'da ~6), dağılım düzenli, test pozitif.
# Üst eşikler daha yüksek kâr veriyor ama işlem sayısı çöküyor ve tek güne bağlı.
```

#### drive/toplama/arsiv-2/Futures_Bot_v37_Deneysel_Paper_SON__ic/futures_bot_v37/ws_bot.py:768-774
```
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))
```

#### drive/toplama/arsiv-1/Futures_Bot_Temiz_Kayitli_v34_v35n_v2 (1)__ic/bot/futures_bot_v34/ws_bot.py:85-91
```
# CASCADE EŞİĞİ: son 60 saniyede kaç sinyal geldiyse "tasfiye zinciri" sayılır.
# 7 gün kanıtı (104 sembol, nedensel test):
#   eşik 1 (filtresiz) 1593 sinyal %60,1 isabet +0,197%/işlem · 4/8 gün pozitif
#   eşik 2              881 sinyal %70,0 isabet +0,359%      · 5/8 gün
#   eşik 3              592 sinyal %80,7 isabet +0,563%      · 6/8 gün  <- SEÇİLEN
#   eşik 4              519 sinyal %86,3 isabet +0,670%      · 5/6 gün
# Eşik 3: eğitim +0,607 / test +0,459 · bootstrap 2000× %0 negatif
```

#### drive/toplama/arsiv-1/Futures_Bot_Temiz_Kayitli_v34_v35n_v2 (1)__ic/bot/futures_bot_v34/ws_bot.py:110-116
```
#     eşik 2,0 → 16.329 sinyal  -0,035%   (kenar yok)
#     eşik 3,0 →  6.983 sinyal  +0,081%
#     eşik 4,0 →  3.468 sinyal  +0,233%  %71,1 isabet · test +0,069  <-- SEÇİLEN
#     eşik 5,0 →  2.209 sinyal  +0,441%  %68,4 isabet · test +0,039
#     eşik 6,0 →  1.540 sinyal  +0,560%  ama sinyaller 2 güne sıkışıyor
# 4,0 seçildi: günde ~590 sinyal (15 dk'da ~6), dağılım düzenli, test pozitif.
# Üst eşikler daha yüksek kâr veriyor ama işlem sayısı çöküyor ve tek güne bağlı.
```

#### drive/toplama/arsiv-1/Futures_Bot_Temiz_Kayitli_v34_v35n_v2 (1)__ic/bot/futures_bot_v34/ws_bot.py:758-764
```
            stop = (giris_fiyat * (1 - marj_bitis / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + marj_bitis / 100))
        else:
            stop = (giris_fiyat * (1 - self.sl_pct / 100) if s.yon == "LONG"
                    else giris_fiyat * (1 + self.sl_pct / 100))
        tp = (giris_fiyat * (1 + self.tp_pct / 100) if s.yon == "LONG"
              else giris_fiyat * (1 - self.tp_pct / 100))
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:69-75
```
class FadeStrategyTests(unittest.TestCase):
    def test_down_impulse_and_rvol_threshold_produce_long(self):
        signal = FadeStrategy().evaluate(fade_setup())
        self.assertEqual(signal.side, "LONG")
        self.assertLess(signal.impulse_pct, -0.35)
        self.assertGreaterEqual(signal.rvol, 2.0)
        self.assertAlmostEqual(signal.stop_distance_fraction, abs(signal.impulse_pct) / 100)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:128-134
```
        down_signal = strategy.evaluate(falling)
        self.assertEqual(up_signal.side, "LONG")
        self.assertEqual(up_signal.motor, "trend")
        self.assertEqual(down_signal.side, "SHORT")
        self.assertEqual(down_signal.motor, "trend")
        self.assertGreater(up_signal.stop_distance_fraction, 0)
        self.assertEqual(up_signal.rvol, 3.0)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:1310-1316
```
            strategy=FixedSignal(Signal("LONG", -0.5, 2.0, 0.005, "fade")),
            trend_strategy=FixedSignal(Signal("HOLD", 0, 0, None, "trend")),
        )
        executor.process("binance:BTCUSDT", fade_setup())
        executor.strategy = FixedSignal(Signal("HOLD", 0, 0, None, "fade"))
        executor.trend_strategy = FixedSignal(
            Signal("SHORT", -0.1, 0, 0.01, "trend")
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:65-71
```
class FadeStrategyTests(unittest.TestCase):
    def test_down_impulse_and_rvol_threshold_produce_long(self):
        signal = FadeStrategy().evaluate(fade_setup())
        self.assertEqual(signal.side, "LONG")
        self.assertLess(signal.impulse_pct, -0.35)
        self.assertGreaterEqual(signal.rvol, 2.0)
        self.assertAlmostEqual(signal.stop_distance_fraction, abs(signal.impulse_pct) / 100)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:124-130
```
        down_signal = strategy.evaluate(falling)
        self.assertEqual(up_signal.side, "LONG")
        self.assertEqual(up_signal.motor, "trend")
        self.assertEqual(down_signal.side, "SHORT")
        self.assertEqual(down_signal.motor, "trend")
        self.assertGreater(up_signal.stop_distance_fraction, 0)
        self.assertEqual(up_signal.rvol, 3.0)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:1290-1296
```
            strategy=FixedSignal(Signal("LONG", -0.5, 2.0, 0.005, "fade")),
            trend_strategy=FixedSignal(Signal("HOLD", 0, 0, None, "trend")),
        )
        executor.process("binance:BTCUSDT", fade_setup())
        executor.strategy = FixedSignal(Signal("HOLD", 0, 0, None, "fade"))
        executor.trend_strategy = FixedSignal(
            Signal("SHORT", -0.1, 0, 0.01, "trend")
```

#### drive/toplama/arsiv-4/bot_final__ic/new-bot/tests/test_trading_system.py:62-68
```
class FadeStrategyTests(unittest.TestCase):
    def test_down_impulse_and_rvol_threshold_produce_long(self):
        signal = FadeStrategy().evaluate(fade_setup())
        self.assertEqual(signal.side, "LONG")
        self.assertLess(signal.impulse_pct, -0.35)
        self.assertGreaterEqual(signal.rvol, 2.0)
        self.assertAlmostEqual(signal.stop_distance_fraction, abs(signal.impulse_pct) / 100)
```

#### drive/toplama/arsiv-4/bot_final__ic/new-bot/tests/test_trading_system.py:113-119
```
        down_signal = strategy.evaluate(falling)
        self.assertEqual(up_signal.side, "LONG")
        self.assertEqual(up_signal.motor, "trend")
        self.assertEqual(down_signal.side, "SHORT")
        self.assertEqual(down_signal.motor, "trend")
        self.assertGreater(up_signal.stop_distance_fraction, 0)
        self.assertEqual(up_signal.rvol, 1.0)
```

#### drive/toplama/arsiv-4/bot_final__ic/new-bot/tests/test_trading_system.py:1079-1085
```
            strategy=FixedSignal(Signal("LONG", -0.5, 2.0, 0.005, "fade")),
            trend_strategy=FixedSignal(Signal("HOLD", 0, 0, None, "trend")),
        )
        executor.process("binance:BTCUSDT", fade_setup())
        executor.strategy = FixedSignal(Signal("HOLD", 0, 0, None, "fade"))
        executor.trend_strategy = FixedSignal(
            Signal("SHORT", -0.1, 0, 0.01, "trend")
```

#### drive/toplama/arsiv-1/kripto-bot-v9.4.5-yama-test-rapor-binance__ic/kripto-bot-v9.4.5/reports/v943_reference_sources/src/unified_engine.py:434-440
```
                self.v94_router = V94LiveRouter(self, AdaptivePolicy(**self.cfg["v94"].get("policy", {})))
            self.metrics["signals_evaluated"] += 1
            return await self.v94_router.evaluate(exchange, symbol, ohlcv_5m,
                mark_price=mark_price, spread_pct=spread_pct,
                now_ms=int(now_ms if now_ms is not None else time.time()*1000),
                allow_new_entries=allow_new_entries)
        self.metrics["signals_evaluated"] += 1
```

#### drive/toplama/arsiv-1/kripto-bot-v9.4.5-yama-test-rapor-binance__ic/kripto-bot-v9.4.5/reports/v943_reference_sources/src/unified_engine.py:748-754
```
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "yeni_giris_durduruldu_acik_pozisyon_bekleniyor",
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
```

#### drive/toplama/arsiv-1/kripto-bot-v9.4.5-yama-test-rapor-binance__ic/kripto-bot-v9.4.5/reports/v943_reference_sources/src/unified_engine.py:761-767
```
            self._record_block(symbol, side, "vwap_warmup_gate", "v4_vwap60_isinmadi_giris_kilitli", price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "v4_vwap60_isinmadi_giris_kilitli",
```

#### drive/toplama/arsiv-2/toplama 2/unified_engine.py:434-440
```
                self.v94_router = V94LiveRouter(self, AdaptivePolicy(**self.cfg["v94"].get("policy", {})))
            self.metrics["signals_evaluated"] += 1
            return await self.v94_router.evaluate(exchange, symbol, ohlcv_5m,
                mark_price=mark_price, spread_pct=spread_pct,
                now_ms=int(now_ms if now_ms is not None else time.time()*1000),
                allow_new_entries=allow_new_entries)
        self.metrics["signals_evaluated"] += 1
```

#### drive/toplama/arsiv-2/toplama 2/unified_engine.py:748-754
```
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "yeni_giris_durduruldu_acik_pozisyon_bekleniyor",
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
```

#### drive/toplama/arsiv-2/toplama 2/unified_engine.py:761-767
```
            self._record_block(symbol, side, "vwap_warmup_gate", "v4_vwap60_isinmadi_giris_kilitli", price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "v4_vwap60_isinmadi_giris_kilitli",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/executor.py:72-78
```
        self.pipeline = SignalPipeline(self.config)
        self.orderflow = OrderFlowEngine(self.config.v2.orderflow)
        self.mtf_analyzer = MtfAnalyzer(self.config.v2.mtf)
        self.rate_limiter = EntryRateLimiter(self.config.v2.gates)
        self.cooldown = ReentryCooldown(self.config.v2.gates)
        self.shadow_tracker = ShadowSignalTracker()
        self.beta_estimator = BetaEstimator(self.config.v2.gates)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/executor.py:93-99
```
            multiplier=self.config.signal.spike_multiplier,
            lookback_seconds=self.config.data.timeframe_ms // 1000,
            window_seconds=self.config.signal.spike_window_seconds,
            direction_seconds=self.config.signal.spike_direction_seconds,
            sanity_cap=self.config.signal.spike_rvol_sanity_cap,
            min_baseline_notional_per_second=(
                self.config.signal.spike_min_baseline_notional_per_second
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/executor.py:908-914
```
        stop_fraction = signal.stop_distance_fraction or 0.0
        record = self.shadow_tracker.record_blocked(
            symbol, signal.side, reason, entry_ref, stop_fraction, ts_ms,
        )
        if record is not None and self.store is not None:
            store_id = self.store.append_shadow_signal(
                ts_ms, symbol, signal.side, reason, entry_ref, {}, False,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/executor.py:72-78
```
        self.pipeline = SignalPipeline(self.config)
        self.orderflow = OrderFlowEngine(self.config.v2.orderflow)
        self.mtf_analyzer = MtfAnalyzer(self.config.v2.mtf)
        self.rate_limiter = EntryRateLimiter(self.config.v2.gates)
        self.cooldown = ReentryCooldown(self.config.v2.gates)
        self.shadow_tracker = ShadowSignalTracker()
        self.beta_estimator = BetaEstimator(self.config.v2.gates)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/executor.py:87-93
```
            multiplier=self.config.signal.spike_multiplier,
            lookback_seconds=self.config.data.timeframe_ms // 1000,
            window_seconds=self.config.signal.spike_window_seconds,
            direction_seconds=self.config.signal.spike_direction_seconds,
            sanity_cap=self.config.signal.spike_rvol_sanity_cap,
            min_baseline_notional_per_second=(
                self.config.signal.spike_min_baseline_notional_per_second
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/executor.py:839-845
```
        stop_fraction = signal.stop_distance_fraction or 0.0
        record = self.shadow_tracker.record_blocked(
            symbol, signal.side, reason, entry_ref, stop_fraction, ts_ms,
        )
        if record is not None and self.store is not None:
            store_id = self.store.append_shadow_signal(
                ts_ms, symbol, signal.side, reason, entry_ref, {}, False,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/executor.py:72-78
```
        self.pipeline = SignalPipeline(self.config)
        self.orderflow = OrderFlowEngine(self.config.v2.orderflow)
        self.mtf_analyzer = MtfAnalyzer(self.config.v2.mtf)
        self.rate_limiter = EntryRateLimiter(self.config.v2.gates)
        self.cooldown = ReentryCooldown(self.config.v2.gates)
        self.shadow_tracker = ShadowSignalTracker()
        self.beta_estimator = BetaEstimator(self.config.v2.gates)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.1__ic/ACARBOT_FINAL_v1.1/core/strategy.py:107-113
```
    """BTC son 15 dakikalık yönü, altcoin sinyallerini engelleyebilir (Y1-E).

    Kural: sinyal yönü BTC'nin 15dk hareketine TERS ise ve BTC o yönde
    `btc_block_change_pct`'i aşmışsa sinyal reddedilir (news şoku koruması).
    """

    def __init__(self, config: SignalConfig | None = None) -> None:
```
