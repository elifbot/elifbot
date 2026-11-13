"""Pozisyon yöneticisi: giriş/çıkış, %5 stop, sınırsız kârda ekleme (pyramiding),
terste kalan pozisyonu çapraz kurtarma (ikili kapama), Dinamik Kaldıraç (20x/10x/5x),
Maksimum Kayma Filtresi + Chase Order, SQLite durum kalıcılığı, Circuit Breaker
ve Gizli Anahtar Maskeleme entegrasyonu.
"""
from __future__ import annotations

import time

from .risk import Position
from .security import mask_secrets, safe_exception_msg


class Executor:
    def __init__(
        self,
        broker,
        risk,
        strategy,
        sizer=None,
        alert=None,
        cooldown_sec: int = 300,
        order_type: str = "maker",
        maker_timeout: float = 3.0,
        protection_on: bool = True,
        state_store=None,
        circuit_breaker=None,
    ):
        self.broker = broker
        self.risk = risk
        self.strategy = strategy
        self.sizer = sizer
        self.alert = alert
        self.cooldown_sec = cooldown_sec
        self.order_type = order_type
        self.maker_timeout = maker_timeout
        self.protection_on = protection_on
        self.state_store = state_store
        self.circuit_breaker = circuit_breaker

        self.positions: dict[str, Position] = {}
        self.last_prices: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._atr: dict[str, float] = {}
        self._mtf_trends: dict[str, dict | str] = {}
        self._veto_approaching: bool = False
        self._fear_greed: float = 50.0
        self.active_leverage: dict[str, int] = {}
        self._prot: dict[str, dict] = {}
        self._prot_stop: dict[str, float] = {}
        self._last_replace: dict[str, float] = {}
        self._last_add_ts: dict[str, float] = {}
        self.add_cooldown_sec: float = 10.0
        self.stats = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "pnl_pct_sum": 0.0,
            "pnl_usdt_sum": 0.0,
            "pyramids": 0,
            "pair_rescues": 0,
            "chase_orders": 0,
            "mtf_filtered": 0,
        }

        if self.state_store is not None:
            self.restore_state()

    def restore_state(self) -> list[str]:
        """SQLite veritabanından açık pozisyonları geri yükler."""
        if self.state_store is None:
            return []
        try:
            loaded = self.state_store.load_positions()
            msgs = self.state_store.startup_recovery_report()
            for sym, pos in loaded.items():
                self.positions[sym] = pos
                self.last_prices[sym] = pos.entry
                self.active_leverage[sym] = pos.leverage
            for m in msgs:
                print(mask_secrets(m), flush=True)
            return msgs
        except Exception as e:
            print(
                f"⚠️ Durum geri yükleme hatası: {safe_exception_msg(e)}",
                flush=True,
            )
            return []

    async def _say(self, msg: str):
        clean = mask_secrets(msg)
        print(clean, flush=True)
        if self.alert:
            try:
                await self.alert(clean)
            except Exception:
                pass

    def set_atr(self, symbol: str, atr: float):
        self._atr[symbol] = atr

    def set_mtf_trend(self, symbol: str, mtf_info: dict | str):
        """Sembol için `1h`/`4h` Multi-Timeframe ana trend bilgisini günceller."""
        self._mtf_trends[symbol] = mtf_info

    def get_mtf_trend(self, symbol: str) -> dict | str | None:
        return self._mtf_trends.get(symbol)

    def set_market_mood(self, fear_greed: float = 50.0, veto_approaching: bool = False):
        self._fear_greed = float(fear_greed)
        self._veto_approaching = bool(veto_approaching)

    def get_dynamic_leverage(self, symbol: str, price: float) -> tuple[int, str]:
        atr = self._atr.get(symbol)
        if hasattr(self.risk, "compute_dynamic_leverage"):
            lev, why = self.risk.compute_dynamic_leverage(
                price=price,
                atr=atr,
                veto_approaching=self._veto_approaching,
                fear_greed=self._fear_greed,
            )
            self.active_leverage[symbol] = lev
            return lev, why
        lev = int(getattr(self.risk, "leverage", 20))
        self.active_leverage[symbol] = lev
        return lev, f"sabit {lev}x"

    def in_cooldown(self, symbol: str) -> bool:
        return time.time() < self._cooldown_until.get(symbol, 0)

    def _all_positions_in_profit(self) -> bool:
        if not self.positions:
            return False
        for sym, pos in self.positions.items():
            px = self.last_prices.get(sym, pos.entry)
            if self.risk.profit_pct(pos, px) <= 0:
                return False
        return True

    def total_unrealized_usdt(self) -> float:
        tot = 0.0
        for sym, pos in self.positions.items():
            px = self.last_prices.get(sym, pos.entry)
            tot += self.risk.pnl_usdt(pos, px)
        return round(tot, 2)

    # -- 1) HER TICK: stop / trailing / kâr kilidi + Çapraz Kurtarma -------------
    async def on_price_tick(self, symbol: str, price: float):
        self.last_prices[symbol] = price
        if self.circuit_breaker is not None:
            if self.circuit_breaker.check_price_shock(symbol, price):
                await self._say(
                    f"🚨 CIRCUIT BREAKER: {self.circuit_breaker.trip_reason}"
                )
                await self.close_all_positions("FLASH CRASH SİGORTASI")
                return

        pos = self.positions.get(symbol)
        if pos is not None:
            old_stop_before = pos.stop
            old_lock_before = pos.locked_profit
            res = self.risk.update(pos, price)
            if res["action"] == "close":
                await self._close(symbol, price, res["reason"], res["pnl_pct"])
                return

            if (
                self.state_store is not None
                and (pos.stop != old_stop_before or pos.locked_profit != old_lock_before)
            ):
                try:
                    self.state_store.save_position(pos)
                except Exception:
                    pass

            if (
                self.protection_on
                and self.broker.mode != "paper"
                and symbol in self._prot
                and self._prot[symbol].get("native")
            ):
                old_stop = self._prot_stop.get(symbol, pos.stop)
                moved = abs(res["stop"] - old_stop) / max(old_stop, 1e-12)
                due = time.time() - self._last_replace.get(symbol, 0) > 30
                if moved > 0.004 and due and res["pnl_pct"] > 0:
                    try:
                        new = await self.broker.replace_protection(
                            symbol,
                            pos.side,
                            pos.qty,
                            res["stop"],
                            self._prot[symbol],
                        )
                        self._prot[symbol] = new
                        self._prot_stop[symbol] = res["stop"]
                        self._last_replace[symbol] = time.time()
                        await self._say(
                            f"🔒 {symbol}: borsa stopu güncellendi → {res['stop']:,.4f}"
                        )
                    except Exception as e:
                        print(
                            f"⚠️ {symbol} koruma güncelleme hatası: {safe_exception_msg(e)}",
                            flush=True,
                        )

        # ÇAPRAZ KURTARMA (Biri artıda biri ekside ise ufak zarar/kârla ikisini kapat)
        if len(self.positions) >= 2:
            rescue = self.risk.find_pair_rescue(self.positions, self.last_prices)
            if rescue and rescue.get("action") == "pair_close":
                await self.execute_pair_rescue(rescue)

    async def execute_pair_rescue(self, rescue: dict):
        """Terste kalan pozisyon ile artıdaki pozisyonu aynı anda kapatır."""
        w_sym = rescue["winner_symbol"]
        l_sym = rescue["loser_symbol"]
        if w_sym not in self.positions or l_sym not in self.positions:
            return
        w_px = rescue["winner_price"]
        l_px = rescue["loser_price"]
        w_pct = rescue["winner_pnl_pct"]
        l_pct = rescue["loser_pnl_pct"]
        reason = rescue["reason"]

        self.stats["pair_rescues"] += 1
        await self._say(f"⚖️ {reason}")
        await self._close(
            w_sym,
            w_px,
            f"ÇAPRAZ KURTARMA (ARTI BACAK): {l_sym} ile netlendi",
            w_pct,
        )
        await self._close(
            l_sym,
            l_px,
            f"ÇAPRAZ KURTARMA (TERSTEKİ BACAK): {w_sym} ile kurtarıldı",
            l_pct,
        )

    # -- 2) SİNYAL ANI: giriş, artıda sınırsız ekleme veya bot-çözümü çıkış -------
    async def on_signal(
        self,
        symbol: str,
        price: float,
        combined: dict,
        flow_score: float,
        veto: bool,
        veto_long: bool = False,
        veto_short: bool = False,
        mtf_trend: dict | str | None = None,
    ):
        self.last_prices[symbol] = price
        active_mtf = (
            mtf_trend if mtf_trend is not None else self._mtf_trends.get(symbol)
        )

        if len(self.positions) >= 2:
            rescue = self.risk.find_pair_rescue(self.positions, self.last_prices)
            if rescue and rescue.get("action") == "pair_close":
                await self.execute_pair_rescue(rescue)
                return

        pos = self.positions.get(symbol)

        if pos is not None:
            pnl = self.risk.profit_pct(pos, price)
            ex = self.strategy.exit_decision(
                pos.side, combined, flow_score, veto, pnl
            )
            if ex["action"] == "close":
                await self._close(
                    symbol, price, f"BOT ÇIKIŞI: {ex['reason']}", pnl
                )
                return

            if self.circuit_breaker is not None:
                cb_ok, _ = self.circuit_breaker.can_trade()
                if not cb_ok:
                    return
            can_add, add_why = self.risk.can_add_to_winner(pos, price)
            add_due = (
                time.time() - self._last_add_ts.get(symbol, 0.0)
            ) >= self.add_cooldown_sec
            if can_add and add_due:
                dec = self.strategy.entry_decision(
                    combined,
                    veto,
                    has_position=True,
                    veto_long=veto_long,
                    veto_short=veto_short,
                    can_pyramid=True,
                    current_side=pos.side,
                    mtf_trend=active_mtf,
                )
                if dec["action"] in ("ADD_LONG", "ADD_SHORT"):
                    await self._add_layer(
                        symbol, price, f"{add_why} | {dec['reason']}"
                    )
            return

        if self.circuit_breaker is not None:
            cb_ok, _ = self.circuit_breaker.can_trade()
            if not cb_ok:
                return

        if self.in_cooldown(symbol):
            return
        dec = self.strategy.entry_decision(
            combined,
            veto,
            has_position=False,
            veto_long=veto_long,
            veto_short=veto_short,
            mtf_trend=active_mtf,
        )
        if dec["action"] == "yok" and "MTF TREND FİLTRESİ" in str(
            dec.get("reason", "")
        ):
            self.stats["mtf_filtered"] = self.stats.get("mtf_filtered", 0) + 1
            return
        if dec["action"] in ("LONG", "SHORT"):
            all_green = self._all_positions_in_profit()
            ok, why = self.risk.can_open(
                len(self.positions), all_in_profit=all_green
            )
            if not ok:
                await self._say(f"⛔ {symbol}: giriş engellendi — {why}")
                return
            await self._open(symbol, dec["action"], price, dec["reason"])

    # -- emir işlemleri --------------------------------------------------------------
    def _calc_qty(
        self,
        balance: float,
        price: float,
        stop: float,
        symbol: str,
        leverage_override: int | None = None,
    ) -> tuple[float, dict]:
        if self.sizer is not None:
            atr = self._atr.get(symbol)
            return self.sizer.size(
                balance, price, stop, atr, leverage_override=leverage_override
            )
        qty = self.risk.position_size(max(balance, 0), price, stop)
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        return qty, {
            "kaynak": "sabit",
            "risk_pct": self.risk.risk_per_trade_pct,
            "leverage": lev,
            "margin_usdt": round((qty * price) / max(1, lev), 2),
            "notional": round(qty * price, 2),
        }

    async def _open(self, symbol: str, side: str, price: float, reason: str):
        balance = await self.broker.fetch_balance_usdt()
        stop = self.risk.initial_stop(side, price)
        dyn_lev, lev_why = self.get_dynamic_leverage(symbol, price)
        qty, info = self._calc_qty(
            balance, price, stop, symbol, leverage_override=dyn_lev
        )
        if qty <= 0:
            await self._say(
                f"⛔ {symbol}: miktar hesaplanamadı "
                f"({info.get('neden', 'yetersiz bakiye')})."
            )
            return
        try:
            ex_name, best_px = await self.broker.best_price(symbol, side)
        except Exception:
            ex_name, best_px = self.broker.primary, price
        order_side = "buy" if side == "LONG" else "sell"
        try:
            try:
                fill = await self.broker.execute_entry(
                    symbol,
                    order_side,
                    qty,
                    price_hint=best_px,
                    order_type=self.order_type,
                    timeout=self.maker_timeout,
                    exchange=ex_name,
                    expected_price=price,
                    leverage=dyn_lev,
                )
            except TypeError:
                fill = await self.broker.execute_entry(
                    symbol,
                    order_side,
                    qty,
                    price_hint=best_px,
                    order_type=self.order_type,
                    timeout=self.maker_timeout,
                    exchange=ex_name,
                )
            if fill.get("emir_tipi") in ("chase_limit", "maker+chase-limit"):
                self.stats["chase_orders"] += 1
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_success()
        except Exception as e:
            err_safe = safe_exception_msg(e)
            await self._say(f"⛔ {symbol} emir hatası: {err_safe}")
            if self.circuit_breaker is not None:
                if self.circuit_breaker.record_order_error(e):
                    await self._say(
                        f"🚨 SİGORTA ATTI: {self.circuit_breaker.trip_reason}"
                    )
                    await self.close_all_positions(
                        self.circuit_breaker.trip_reason or "EMİR/YETKİ HATASI SİGORTASI"
                    )
            return

        fill_px = fill.get("price") or best_px
        lev = int(info.get("leverage") or dyn_lev)
        margin_usdt = float(
            info.get("margin_usdt") or (fill_px * qty) / max(1, lev)
        )

        pos = Position(
            symbol=symbol,
            side=side,
            entry=fill_px,
            qty=qty,
            stop=self.risk.initial_stop(side, fill_px),
            leverage=lev,
            margin_usdt=round(margin_usdt, 2),
            layers=1,
            last_add_price=fill_px,
        )
        self.positions[symbol] = pos
        self.last_prices[symbol] = fill_px
        self._last_add_ts[symbol] = time.time()

        if self.state_store is not None:
            try:
                self.state_store.save_position(pos, exchange=ex_name)
            except Exception:
                pass

        prot_note = "bot-taraflı"
        if self.protection_on:
            try:
                prot = await self.broker.place_protection(
                    symbol, side, qty, pos.stop, None, ex_name
                )
                self._prot[symbol] = prot
                self._prot_stop[symbol] = pos.stop
                prot_note = (
                    f"borsa-native ({prot.get('kind')})"
                    if prot.get("native")
                    else "bot-taraflı (borsa desteklemedi)"
                )
            except Exception as e:
                print(
                    f"⚠️ {symbol} koruma hatası: {safe_exception_msg(e)} (bot-taraflı devam)",
                    flush=True,
                )

        await self._say(
            f"🟢 {side} AÇILDI | {symbol} @ {fill_px:,.4f} | {lev}x Kaldıraç ({lev_why}) | "
            f"Marj: ${margin_usdt:,.2f} (%{info.get('risk_pct')}) | "
            f"Emir: {fill.get('emir_tipi', '?')} | Stop: {pos.stop:,.4f} (-%5) | "
            f"Koruma: {prot_note} | Neden: {reason}"
        )

    async def _add_layer(self, symbol: str, price: float, reason: str):
        """Artıdaki açık pozisyona %10 kasa × aktif kaldıraç ile yeni kademe ekler."""
        pos = self.positions.get(symbol)
        if pos is None:
            return
        balance = await self.broker.fetch_balance_usdt()
        stop = self.risk.initial_stop(pos.side, price)
        dyn_lev, _ = self.get_dynamic_leverage(symbol, price)
        add_qty, info = self._calc_qty(
            balance, price, stop, symbol, leverage_override=dyn_lev
        )
        if add_qty <= 0:
            return
        try:
            ex_name, best_px = await self.broker.best_price(symbol, pos.side)
        except Exception:
            ex_name, best_px = self.broker.primary, price
        order_side = "buy" if pos.side == "LONG" else "sell"
        try:
            try:
                fill = await self.broker.execute_entry(
                    symbol,
                    order_side,
                    add_qty,
                    price_hint=best_px,
                    order_type=self.order_type,
                    timeout=self.maker_timeout,
                    exchange=ex_name,
                    expected_price=price,
                    leverage=dyn_lev,
                )
            except TypeError:
                fill = await self.broker.execute_entry(
                    symbol,
                    order_side,
                    add_qty,
                    price_hint=best_px,
                    order_type=self.order_type,
                    timeout=self.maker_timeout,
                    exchange=ex_name,
                )
            if fill.get("emir_tipi") in ("chase_limit", "maker+chase-limit"):
                self.stats["chase_orders"] += 1
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_success()
        except Exception as e:
            err_safe = safe_exception_msg(e)
            await self._say(f"⛔ {symbol} kademe ekleme hatası: {err_safe}")
            if self.circuit_breaker is not None:
                if self.circuit_breaker.record_order_error(e):
                    await self.close_all_positions(
                        self.circuit_breaker.trip_reason or "ARD ARDA 3 EMİR HATASI"
                    )
            return

        fill_px = fill.get("price") or best_px
        lev = int(info.get("leverage") or pos.leverage)
        add_margin = float(
            info.get("margin_usdt") or (fill_px * add_qty) / max(1, lev)
        )

        pos.add_layer(
            add_price=fill_px,
            add_qty=add_qty,
            add_margin_usdt=add_margin,
            stop_loss_pct=self.risk.stop_loss_pct,
        )
        self._last_add_ts[symbol] = time.time()
        self.stats["pyramids"] += 1

        if self.state_store is not None:
            try:
                self.state_store.save_position(pos, exchange=ex_name)
            except Exception:
                pass

        if self.protection_on and symbol in self._prot:
            try:
                new_prot = await self.broker.replace_protection(
                    symbol, pos.side, pos.qty, pos.stop, self._prot[symbol], ex_name
                )
                self._prot[symbol] = new_prot
                self._prot_stop[symbol] = pos.stop
            except Exception:
                pass

        await self._say(
            f"➕ ARTIDA KADEME EKLENDİ ({pos.layers}. Kademe) | {pos.side} {symbol} @ {fill_px:,.4f} | "
            f"Yeni Ort. Giriş: {pos.entry:,.4f} | Toplam Marj: ${pos.margin_usdt:,.2f} ({pos.leverage}x) | "
            f"Yeni Stop: {pos.stop:,.4f} | Neden: {reason}"
        )

    async def _close(
        self, symbol: str, price: float, reason: str, pnl_pct: float
    ):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return
        pnl_usdt = self.risk.pnl_usdt(pos, price)
        roe_pct = self.risk.roe_pct(pos, price)

        prot = self._prot.pop(symbol, None)
        self._prot_stop.pop(symbol, None)
        try:
            await self.broker.cancel_protection(symbol, prot)
        except Exception:
            pass
        order_side = "sell" if pos.side == "LONG" else "buy"
        try:
            await self.broker.market_order(
                symbol, order_side, pos.qty, price_hint=price
            )
            if getattr(self.broker, "mode", "paper") == "paper" and hasattr(
                self.broker, "paper"
            ):
                self.broker.paper.realize_pnl(pnl_usdt)
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_success()
        except Exception as e:
            err_safe = safe_exception_msg(e)
            await self._say(
                f"⚠️ {symbol} kapatma emri hatası: {err_safe} (pozisyon kayıtta kapatıldı)"
            )
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_error(e)

        if self.state_store is not None:
            try:
                self.state_store.delete_position(symbol)
                self.state_store.record_trade(
                    symbol=symbol,
                    side=pos.side,
                    entry=pos.entry,
                    exit_price=price,
                    qty=pos.qty,
                    pnl_pct=pnl_pct,
                    reason=reason,
                    leverage=pos.leverage,
                    margin_usdt=pos.margin_usdt,
                    pnl_usdt=pnl_usdt,
                    layers=pos.layers,
                )
            except Exception:
                pass

        self.risk.register_close(pnl_pct)
        if self.circuit_breaker is not None:
            if self.circuit_breaker.record_trade_pnl(pnl_pct):
                await self._say(
                    f"🚨 SİGORTA ATTI: {self.circuit_breaker.trip_reason}"
                )

        if self.sizer is not None:
            try:
                self.sizer.kelly.record(pnl_pct)
            except Exception:
                pass

        self._cooldown_until[symbol] = time.time() + self.cooldown_sec
        self.stats["trades"] += 1
        self.stats["pnl_pct_sum"] += pnl_pct
        self.stats["pnl_usdt_sum"] = round(self.stats["pnl_usdt_sum"] + pnl_usdt, 2)
        if pnl_pct >= 0:
            self.stats["wins"] += 1
            emoji = "✅"
        else:
            self.stats["losses"] += 1
            emoji = "🔴"
        kilit = " 🔒(kâr kilidi aktifti)" if pos.locked_profit else ""
        await self._say(
            f"{emoji} POZİSYON KAPANDI | {pos.side} {symbol} ({pos.layers} kademe, {pos.leverage}x) @ {price:,.4f} | "
            f"Fiyat PnL: %{pnl_pct:+.2f} | ROE: %{roe_pct:+.1f} | Net: ${pnl_usdt:+.2f}{kilit} | Neden: {reason}"
        )

    async def close_all_positions(self, reason: str = "ACİL DURUM KILL-SWITCH"):
        """Tüm açık pozisyonları tek tuşla anında market emriyle kapatır."""
        symbols = list(self.positions.keys())
        if not symbols:
            await self._say(f"🛑 [{reason}] Açık pozisyon yok, bot kilitlendi.")
            return 0
        await self._say(
            f"🚨 [{reason}] {len(symbols)} açık pozisyon ACİL KAPATILIYOR: {', '.join(symbols)}"
        )
        closed_count = 0
        for sym in symbols:
            pos = self.positions.get(sym)
            if not pos:
                continue
            px = self.last_prices.get(sym) or pos.entry
            pnl = self.risk.profit_pct(pos, px)
            await self._close(sym, px, reason, pnl)
            closed_count += 1
        return closed_count
