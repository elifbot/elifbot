# HAVUZ DEMETİ · VERI

**Soru:** Veri hattı: tick kalitesi, boşluk, saat kayması ve replay tutarlılığı. Sentetik ile gerçek veri arasındaki farkı ölçümde nasıl ayırırız?

Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; kanıt yoksa 'veri yok' de, uydurma.

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:313-319
```
        candles = [
            Candle(i * 300_000, 0.0005, 0.00051, 0.00049, 0.0005, 10.0)
            for i in range(30)
        ]
        candles[-1] = Candle(8_700_000, 0.0005, 0.00051, 0.00039, 0.0004, 10.0)
        verification = Candle(9_000_000, 0.0004, 0.003, 0.0004, 0.003, 100.0)
        ticker = Ticker("BTCUSDT", 0.0, 0.003, 9_000_100)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:732-738
```
        }) as request:
            ticker = client.fetch_ticker("BTC-USDT-SWAP")
        self.assertEqual(ticker.symbol, "BTC-USDT-SWAP")
        self.assertEqual(ticker.last_price, 50_000)
        self.assertEqual(ticker.quote_volume_24h, 1_250_000)
        request.assert_called_once_with(
            "/api/v5/market/ticker", {"instId": "BTC-USDT-SWAP"}
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:1186-1192
```
        candles = fade_setup()
        rejected_candles = [
            Candle(item.timestamp + 300_000, item.open, item.high, item.low,
                   item.close, item.volume)
            for item in candles
        ]
        rejected = executor.process("ETHUSDT", rejected_candles)
```

#### drive/toplama/arsiv-4/bot_final__ic/new-bot/tests/test_trading_system.py:253-259
```
        candles = [
            Candle(i * 300_000, 0.0005, 0.00051, 0.00049, 0.0005, 10.0)
            for i in range(30)
        ]
        candles[-1] = Candle(8_700_000, 0.0005, 0.00051, 0.00039, 0.0004, 10.0)
        verification = Candle(9_000_000, 0.0004, 0.003, 0.0004, 0.003, 100.0)
        ticker = Ticker("BTCUSDT", 0.0, 0.003, 9_000_100)
```

#### drive/toplama/arsiv-4/bot_final__ic/new-bot/tests/test_trading_system.py:615-621
```
        }) as request:
            ticker = client.fetch_ticker("BTC-USDT-SWAP")
        self.assertEqual(ticker.symbol, "BTC-USDT-SWAP")
        self.assertEqual(ticker.last_price, 50_000)
        self.assertEqual(ticker.quote_volume_24h, 1_250_000)
        request.assert_called_once_with(
            "/api/v5/market/ticker", {"instId": "BTC-USDT-SWAP"}
```

#### drive/toplama/arsiv-4/bot_final__ic/new-bot/tests/test_trading_system.py:955-961
```
        candles = fade_setup()
        rejected_candles = [
            Candle(item.timestamp + 300_000, item.open, item.high, item.low,
                   item.close, item.volume)
            for item in candles
        ]
        rejected = executor.process("ETHUSDT", rejected_candles)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:311-317
```
        candles = [
            Candle(i * 300_000, 0.0005, 0.00051, 0.00049, 0.0005, 10.0)
            for i in range(30)
        ]
        candles[-1] = Candle(8_700_000, 0.0005, 0.00051, 0.00039, 0.0004, 10.0)
        verification = Candle(9_000_000, 0.0004, 0.003, 0.0004, 0.003, 100.0)
        ticker = Ticker("BTCUSDT", 0.0, 0.003, 9_000_100)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:729-735
```
        }) as request:
            ticker = client.fetch_ticker("BTC-USDT-SWAP")
        self.assertEqual(ticker.symbol, "BTC-USDT-SWAP")
        self.assertEqual(ticker.last_price, 50_000)
        self.assertEqual(ticker.quote_volume_24h, 1_250_000)
        request.assert_called_once_with(
            "/api/v5/market/ticker", {"instId": "BTC-USDT-SWAP"}
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:1176-1182
```
        candles = fade_setup()
        rejected_candles = [
            Candle(item.timestamp + 300_000, item.open, item.high, item.low,
                   item.close, item.volume)
            for item in candles
        ]
        rejected = executor.process("ETHUSDT", rejected_candles)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/executor.py:206-212
```
        self.data_integrity.record_tick(symbol, timestamp_ms)
        self._latest_prices[symbol] = price
        # v5.1: ampirik ızgara doğrulaması (vadeli API'siz kanıt)
        _tick = self.tick_sizes.get(symbol, 0.0)
        if _tick > 0 and not self.grid_observer.observe(symbol, price, _tick):
            self.tick_sizes.pop(symbol, None)
            self.broker.tick_sizes.pop(symbol, None)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/executor.py:251-257
```
        # v5.0 DÜZELTMESİ: dolum simülasyonu GERÇEK tick baz hacmiyle beslenir.
        # Eski kod hacmi yalnızca spike geçerliyse veriyordu; hacim filtresi
        # devreye girince tick_volume=0 oluyor ve maker emirleri dolmuyordu.
        # Filtre yalnızca SİNYALİ iptal eder; ölçülen hacim gerçektir.
        tick_volume = base_delta
        fill = self.broker.process_entry_tick(
            symbol, price, tick_volume, timestamp_ms,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/executor.py:1012-1018
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/executor.py:200-206
```
        self.data_integrity.record_tick(symbol, timestamp_ms)
        self._latest_prices[symbol] = price
        # v5.1: ampirik ızgara doğrulaması (vadeli API'siz kanıt)
        _tick = self.tick_sizes.get(symbol, 0.0)
        if _tick > 0 and not self.grid_observer.observe(symbol, price, _tick):
            self.tick_sizes.pop(symbol, None)
            self.broker.tick_sizes.pop(symbol, None)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/executor.py:245-251
```
        # v5.0 DÜZELTMESİ: dolum simülasyonu GERÇEK tick baz hacmiyle beslenir.
        # Eski kod hacmi yalnızca spike geçerliyse veriyordu; hacim filtresi
        # devreye girince tick_volume=0 oluyor ve maker emirleri dolmuyordu.
        # Filtre yalnızca SİNYALİ iptal eder; ölçülen hacim gerçektir.
        tick_volume = base_delta
        fill = self.broker.process_entry_tick(
            symbol, price, tick_volume, timestamp_ms,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/executor.py:957-963
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```

#### bot/acarbot_6bot/turbo_engine.py:224-230
```
                buy_usd = 0.0
            elif kline_ts == self.prev_kline_ts:
                delta_usd = max(0.0, kline_q_usd - self.prev_kline_q)
                if kline_taker_buy_usd >= 0.0:
                    buy_usd = max(0.0, min(delta_usd, kline_taker_buy_usd - self.prev_kline_buy_q))
                else:
                    buy_usd = delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))
```

#### bot/acarbot_6bot/turbo_engine.py:239-245
```
            self.prev_kline_ts = kline_ts
            self.prev_kline_q = kline_q_usd
            if kline_taker_buy_usd >= 0.0:
                self.prev_kline_buy_q = kline_taker_buy_usd
        elif self.prev_kline_ts == 0 and quote_vol_24h > 0 and old_q24 > 0:
            # 1.200+ kontratın tamamında (COIN-M ve Teslimatlı Futures dahil) ticker üzerinden de anlık hacim farkını yakala!
            diff_24 = quote_vol_24h - old_q24
```

#### bot/acarbot_6bot/turbo_engine.py:1157-1163
```
        """OKX TÜM SWAP (USDT/USDC/USD) + TÜM FUTURES (Haftalık/Çeyreklik Kontratlar) (~580+ Kontrat)."""
        rest_urls = [
            "https://www.okx.com/api/v5/market/tickers?instType=SWAP",
            "https://www.okx.com/api/v5/market/tickers?instType=FUTURES",
        ]
        ws_public = "wss://ws.okx.com:8443/ws/v5/public"
        ws_biz = "wss://ws.okx.com:8443/ws/v5/business"
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/executor.py:236-242
```
        # v5.0 DÜZELTMESİ: dolum simülasyonu GERÇEK tick baz hacmiyle beslenir.
        # Eski kod hacmi yalnızca spike geçerliyse veriyordu; hacim filtresi
        # devreye girince tick_volume=0 oluyor ve maker emirleri dolmuyordu.
        # Filtre yalnızca SİNYALİ iptal eder; ölçülen hacim gerçektir.
        tick_volume = base_delta
        fill = self.broker.process_entry_tick(
            symbol, price, tick_volume, timestamp_ms,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/executor.py:330-336
```
                if trimmed and trimmed[-1].timestamp == candle.timestamp:
                    candles = trimmed
                else:
                    candles = [*trimmed, candle]
            else:
                candles = [*candles[1:], candle]
            self._candles[symbol] = candles
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/executor.py:943-949
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/executor.py:318-324
```
                if trimmed and trimmed[-1].timestamp == candle.timestamp:
                    candles = trimmed
                else:
                    candles = [*trimmed, candle]
            else:
                candles = [*candles[1:], candle]
            self._candles[symbol] = candles
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/executor.py:881-887
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/executor.py:895-901
```
    def _baseline_liquidity(self, symbol: str) -> float:
        """Yerleştirme anındaki tahmini saniyelik baz hacim (kuyruk modeli)."""
        candles = self._candles.get(symbol) or []
        if not candles:
            return 0.0
        avg_candle = sum(c.volume for c in candles[-20:]) / min(len(candles), 20)
        return avg_candle / (self.config.data.timeframe_ms / 1000.0)
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:1790-1796
```
    def test_counter_not_double_counted_per_tick(self):
        """Aynı emir ikinci tick'te yeniden sayılmamalı (pozisyon açıldı)."""
        b = self._broker(cancel=False)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 2_000)
        assert b.adverse_selection_fills == 1
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:1858-1864
```
    def test_probe_does_not_change_result(self):
        """İzleme açık/kapalı AYNI sonucu vermeli (yan etki yok)."""
        from backtest.engine import BacktestEngine
        from tests.helpers import make_candles
        data = {"okx:TEST": make_candles(_wave_closes(400))}
        a = BacktestEngine().run(data)
        eng = BacktestEngine()
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:2133-2139
```
        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from infra.market_data.models import Candle
        from tests.helpers import apex_config

        setup = _fade_setup_candles_v54("TESTUSDT")
        touch = Candle(
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:1782-1788
```
    def test_counter_not_double_counted_per_tick(self):
        """Aynı emir ikinci tick'te yeniden sayılmamalı (pozisyon açıldı)."""
        b = self._broker(cancel=False)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 2_000)
        assert b.adverse_selection_fills == 1
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:1850-1856
```
    def test_probe_does_not_change_result(self):
        """İzleme açık/kapalı AYNI sonucu vermeli (yan etki yok)."""
        from backtest.engine import BacktestEngine
        from tests.helpers import make_candles
        data = {"okx:TEST": make_candles(_wave_closes(400))}
        a = BacktestEngine().run(data)
        eng = BacktestEngine()
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:2125-2131
```
        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from infra.market_data.models import Candle
        from tests.helpers import apex_config

        setup = _fade_setup_candles_v54("TESTUSDT")
        touch = Candle(
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/app/executor.py:280-286
```
                if trimmed and trimmed[-1].timestamp == candle.timestamp:
                    candles = trimmed
                else:
                    candles = [*trimmed, candle]
            else:
                candles = [*candles[1:], candle]
            self._candles[symbol] = candles
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/app/executor.py:288-294
```
        self.broker.manage_position_candle(
            symbol, candle, candle.timestamp, atr=self._atr_for(symbol),
            impulse_pct=self._impulse(candles), rvol=self._rvol(candles),
        )
        self._record_exits(events, candle.timestamp)
        if self.shadow_tracker.records:
            self._update_shadow(symbol, candle.close, candle.timestamp)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/app/executor.py:648-654
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/app/executor.py:286-292
```
                if trimmed and trimmed[-1].timestamp == candle.timestamp:
                    candles = trimmed
                else:
                    candles = [*trimmed, candle]
            else:
                candles = [*candles[1:], candle]
            self._candles[symbol] = candles
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/app/executor.py:684-690
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/app/executor.py:698-704
```
    def _baseline_liquidity(self, symbol: str) -> float:
        """Yerleştirme anındaki tahmini saniyelik baz hacim (kuyruk modeli)."""
        candles = self._candles.get(symbol) or []
        if not candles:
            return 0.0
        avg_candle = sum(c.volume for c in candles[-20:]) / min(len(candles), 20)
        return avg_candle / (self.config.data.timeframe_ms / 1000.0)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/main.py:329-335
```
        logger.error("Backtest verisi yok: %s altında mum CSV bulunamadı", data_dir)
        return 1
    candles_by_symbol = {}
    for path in candle_files:
        symbol = path.stem.replace("_5m", "").upper()
        candles_by_symbol[symbol] = _load_candles_csv(path)
        logger.info("Yüklendi: %s → %d mum", symbol, len(candles_by_symbol[symbol]))
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/main.py:452-458
```
        news_overrides["enabled"] = False
    if args.news_buffer_minutes is not None:
        if args.news_buffer_minutes < 0:
            raise ValueError("--news-buffer-minutes negatif olamaz")
        news_overrides["buffer_minutes"] = args.news_buffer_minutes
    if news_overrides:
        config.news = _dc_replace(config.news, **news_overrides)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/main.py:919-925
```
                        candles = await asyncio.to_thread(
                            market_clients[name].fetch_candles,
                            symbol, timeframe, config.data.candle_history,
                        )
                        if candles:
                            await eval_queue.put((key, candles))
                    except Exception as exc:  # noqa: BLE001
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/app/main.py:334-340
```
        logger.error("Backtest verisi yok: %s altında mum CSV bulunamadı", data_dir)
        return 1
    candles_by_symbol = {}
    for path in candle_files:
        symbol = path.stem.replace("_5m", "").upper()
        candles_by_symbol[symbol] = _load_candles_csv(path)
        logger.info("Yüklendi: %s → %d mum", symbol, len(candles_by_symbol[symbol]))
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/app/main.py:498-504
```
        news_overrides["enabled"] = False
    if args.news_buffer_minutes is not None:
        if args.news_buffer_minutes < 0:
            raise ValueError("--news-buffer-minutes negatif olamaz")
        news_overrides["buffer_minutes"] = args.news_buffer_minutes
    if news_overrides:
        config.news = _dc_replace(config.news, **news_overrides)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/app/main.py:965-971
```
                        candles = await asyncio.to_thread(
                            market_clients[name].fetch_candles,
                            symbol, timeframe, config.data.candle_history,
                        )
                        if candles:
                            await eval_queue.put((key, candles))
                    except Exception as exc:  # noqa: BLE001
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/app/main.py:335-341
```
        logger.error("Backtest verisi yok: %s altında mum CSV bulunamadı", data_dir)
        return 1
    candles_by_symbol = {}
    for path in candle_files:
        symbol = path.stem.replace("_5m", "").upper()
        candles_by_symbol[symbol] = _load_candles_csv(path)
        logger.info("Yüklendi: %s → %d mum", symbol, len(candles_by_symbol[symbol]))
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/app/main.py:499-505
```
        news_overrides["enabled"] = False
    if args.news_buffer_minutes is not None:
        if args.news_buffer_minutes < 0:
            raise ValueError("--news-buffer-minutes negatif olamaz")
        news_overrides["buffer_minutes"] = args.news_buffer_minutes
    if news_overrides:
        config.news = _dc_replace(config.news, **news_overrides)
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/app/main.py:972-978
```
                        candles = await asyncio.to_thread(
                            market_clients[name].fetch_candles,
                            symbol, timeframe, config.data.candle_history,
                        )
                        if candles:
                            await eval_queue.put((key, candles))
                    except Exception as exc:  # noqa: BLE001
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.9__ic/ACARBOT_FINAL_v1.9/app/executor.py:147-153
```
        # v1.9 DÜZELTMESİ: dolum simülasyonu GERÇEK tick baz hacmiyle beslenir.
        # Eski kod hacmi yalnızca spike geçerliyse veriyordu; filtre devreye
        # girince tick_volume=0 oluyor ve maker emirleri dolmuyordu. Ayrıca
        # 3 sn pencere TOPLAMI her tick'te yeniden verildiği için hacim
        # mükerrer sayılıyordu. Artık tek tick deltası kullanılır.
        tick_volume = base_volume if base_volume is not None else 0.0
        fill = self.broker.process_entry_tick(
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.9__ic/ACARBOT_FINAL_v1.9/app/executor.py:216-222
```
        if candles[-1].timestamp != candle.timestamp:
            candles = [*candles[1:], candle]
            self._candles[symbol] = candles

        self.broker.manage_position_candle(
            symbol, candle, candle.timestamp, atr=self._atr_for(symbol),
            impulse_pct=self._impulse(candles), rvol=self._rvol(candles),
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.9__ic/ACARBOT_FINAL_v1.9/app/executor.py:416-422
```
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
```
