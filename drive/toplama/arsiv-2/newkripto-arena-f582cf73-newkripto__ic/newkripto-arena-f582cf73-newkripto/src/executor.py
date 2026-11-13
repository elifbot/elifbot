"""Pozisyon yöneticisi: sabit marj/ATR/yüzde stop, trailing + order-flow kâr çıkışı,
isteğe bağlı 1R/2R ve kademe, çapraz kurtarma, sabit veya dinamik kaldıraç,
Maksimum Kayma Filtresi + Chase Order, SQLite durum kalıcılığı, Circuit Breaker
ve Gizli Anahtar Maskeleme entegrasyonu.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid

from .attribution import build_entry_attribution
from .exit_rules import (
    apply_supertrend_trailing,
    position_age_seconds,
    runner_exit_reason,
    stagnant_adverse_exit_reason,
)
from .futures_catalog import canonical_underlying_asset
from .risk import Position
from .security import mask_secrets, safe_exception_msg
from .trade_quality import volatility_quality


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
        supertrend_trailing: bool = False,
        trade_plan_cfg: dict | None = None,
        runner_exit_cfg: dict | None = None,
        exit_fee_pct: float = 0.0,
        net_breakeven_enabled: bool = False,
        net_profit_buffer_usdt: float = 0.0,
        min_bb_width_pct: float = 0.0,
        min_atr_pct: float = 0.0,
        dedup_twin_assets: bool = True,
        opportunity_swap_enabled: bool = False,
        opportunity_swap_min_age_sec: float = 480.0,
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
        self.supertrend_trailing = bool(supertrend_trailing)
        self.trade_plan_cfg = dict(trade_plan_cfg or {})
        self.trade_plan_enabled = bool(self.trade_plan_cfg.get("aktif", False))
        self.runner_exit_cfg = dict(runner_exit_cfg or {})
        self.runner_exit_enabled = bool(self.runner_exit_cfg.get("kosan_kar", False))
        self.exit_fee_pct = max(0.0, float(exit_fee_pct or 0.0))
        self.net_breakeven_enabled = bool(net_breakeven_enabled)
        self.net_profit_buffer_usdt = max(0.0, float(net_profit_buffer_usdt or 0.0))
        self.min_bb_width_pct = max(0.0, float(min_bb_width_pct or 0.0))
        self.min_atr_pct = max(0.0, float(min_atr_pct or 0.0))
        self.dedup_twin_assets = bool(dedup_twin_assets)
        self.opportunity_swap_enabled = bool(opportunity_swap_enabled)
        self.opportunity_swap_min_age_sec = max(60.0, float(opportunity_swap_min_age_sec or 480.0))
        self._last_orderflow_exit_check: dict[str, float] = {}
        self._position_observers: list = []

        self.positions: dict[str, Position] = {}
        self.last_prices: dict[str, float] = {}
        # Her sembol için tek bir kapanış yaşam döngüsü. Stop, trailing,
        # order-flow ve flash-crash geri çağrıları aynı event-loop'ta yarışsa
        # bile yalnız ilk istek broker'a reduce-only emir gönderebilir.
        self._close_locks: dict[str, asyncio.Lock] = {}
        self._pair_rescue_lock = asyncio.Lock()
        # Giriş anındaki ölçümler açık pozisyonla birlikte taşınır ve kapanış
        # kaydına aynı UUID ile bağlanır; böylece modül bazlı analiz yapılabilir.
        self._position_meta: dict[str, dict] = {}
        self._cooldown_until: dict[str, float] = {}
        self._atr: dict[str, float] = {}
        self._structure: dict[str, dict] = {}
        self._trade_plans: dict[str, dict] = {}
        self._supertrend: dict[str, dict[str, float]] = {}
        self._mtf_trends: dict[str, dict | str] = {}
        self._veto_approaching: bool = False
        self._fear_greed: float = 50.0
        self.active_leverage: dict[str, int] = {}
        self._prot: dict[str, dict] = {}
        self._prot_stop: dict[str, float] = {}
        self._last_replace: dict[str, float] = {}
        self._last_add_ts: dict[str, float] = {}
        self._funding_last: dict[str, float] = {}
        self._position_opened_ts: dict[str, float] = {}
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
            "regime_filtered": 0,
            "supertrend_trail_updates": 0,
            "funding_usdt": 0.0,
            "tp1_partial_closes": 0,
            "tp2_closes": 0,
            "atr_plan_rejects": 0,
            "orderflow_filtered": 0,
            "runner_orderflow_exits": 0,
            "stagnant_adverse_exits": 0,
            "volatility_filtered": 0,
            "twin_symbol_filtered": 0,
            "altcoin_shock_isolated": 0,
            "altcoin_shock_filtered": 0,
            "flow_warmup_filtered": 0,
            "exhaustion_filtered": 0,
            "crowding_filtered": 0,
            "range_filtered": 0,
            "harmony_filtered": 0,
            "opportunity_swaps": 0,
        }

        self._last_balance = 0.0

        if self.state_store is not None:
            self.restore_state()

    def restore_state(self) -> list[str]:
        """SQLite veritabanından açık pozisyonları geri yükler."""
        if self.state_store is None:
            return []
        try:
            loaded = self.state_store.load_positions()
            msgs = self.state_store.startup_recovery_report()
            funding_clock = self.state_store.get_meta("paper_funding_clock", {}) or {}
            saved_meta = self.state_store.get_meta("position_meta", {}) or {}
            paper = getattr(self.broker, "paper", None)
            for sym, pos in loaded.items():
                self.positions[sym] = pos
                self.last_prices[sym] = pos.entry
                self.active_leverage[sym] = pos.leverage
                meta = saved_meta.get(sym) if isinstance(saved_meta, dict) else None
                if not isinstance(meta, dict):
                    meta = {}
                meta = dict(meta)
                meta.setdefault("position_id", f"recovered-{uuid.uuid4().hex}")
                meta.setdefault("entry_context", {"recovery": "giriş bileşenleri eski oturumda kaydedilmemiş"})
                pos.entry_fee_usdt = float(meta.get("entry_fee_usdt", 0.0) or 0.0)
                pos.funding_usdt = float(meta.get("funding_usdt", 0.0) or 0.0)
                pos.exit_fee_pct = self.exit_fee_pct
                if meta.get("opened_ts"):
                    self._position_opened_ts[sym] = float(meta["opened_ts"])
                self._position_meta[sym] = meta
                # Paper broker yeni bir nesne olarak açılır; restore edilen
                # pozisyonları reduce-only doğrulamasına da geri yüklemeliyiz.
                if paper is not None and hasattr(paper, "sync_position"):
                    paper.sync_position(sym, pos.side, pos.qty)
                self._funding_last[sym] = float(
                    funding_clock.get(sym, time.time()) or time.time()
                )
            if self._position_meta:
                self.state_store.set_meta("position_meta", self._position_meta)
            saved_plans = self.state_store.get_meta("trade_plans", {}) or {}
            if not self.trade_plan_enabled:
                if saved_plans:
                    self.state_store.set_meta("trade_plans", {})
                saved_plans = {}
            for sym, pos in self.positions.items():
                plan = saved_plans.get(sym) if isinstance(saved_plans, dict) else None
                required = {"initial_risk", "initial_stop", "tp1", "tp2", "tp1_hit"}
                if not isinstance(plan, dict) and not self.trade_plan_enabled:
                    continue
                if not isinstance(plan, dict) or not required.issubset(plan):
                    already_tp1 = (
                        pos.side == "LONG" and pos.stop >= pos.entry
                    ) or (
                        pos.side == "SHORT" and pos.stop <= pos.entry
                    )
                    plan = self._make_position_plan(
                        pos.side,
                        pos.entry,
                        pos.stop,
                        source="RECOVERED",
                        tp1_hit=already_tp1,
                    )
                if plan is not None:
                    self._trade_plans[sym] = dict(plan)
            for m in msgs:
                print(mask_secrets(m), flush=True)
            return msgs
        except Exception as e:
            print(
                f"⚠️ Durum geri yükleme hatası: {safe_exception_msg(e)}",
                flush=True,
            )
            return []

    async def reconcile_with_exchange(self) -> dict | None:
        """Başlangıçta/periyodik: yerel pozisyonları borsadaki gerçekle karşılaştırır.

        Hayalet pozisyonları (borsada yok) yerelden siler; sahipsiz pozisyonlar ve
        yön/miktar farklarını yalnızca ALARM olarak bildirir (otomatik işlem yapmaz).
        """
        from .reconcile import reconcile_positions, norm_symbol

        fetch = getattr(self.broker, "fetch_open_positions", None)
        if fetch is None:
            return None
        remote = await fetch()
        if remote is None:
            await self._say("⚠️ MUTABAKAT: borsa pozisyonları okunamadı, atlandı.")
            return None
        if getattr(self.broker, "mode", "paper") == "paper":
            return None
        rep = reconcile_positions(self.positions, remote)
        for g in rep["ghosts"]:
            local_symbol = g.get("local_symbol")
            candidates = (
                [local_symbol]
                if local_symbol in self.positions
                else [s for s in self.positions if norm_symbol(s) == g["symbol"]]
            )
            for sym in candidates:
                self.positions.pop(sym, None)
                self._funding_last.pop(sym, None)
                self._prot.pop(sym, None)
                self._prot_stop.pop(sym, None)
                self._trade_plans.pop(sym, None)
                self._save_trade_plans()
                if self.state_store is not None:
                    try:
                        self.state_store.delete_position(sym)
                    except Exception:
                        pass
            await self._say(
                f"👻 MUTABAKAT: {g['symbol']} {g['side']} botta vardı ama borsada YOK "
                f"(stop/likidasyon ile kapanmış olabilir) → yerel kayıt silindi."
            )
        for o in rep["orphans"]:
            await self._say(
                f"🚨 MUTABAKAT: borsada bot tarafından YÖNETİLMEYEN pozisyon: "
                f"{o['symbol']} {o['side']} {o['qty']:.6f} — stop korumasını elle kontrol et!"
            )
        for m in rep["mismatches"]:
            await self._say(f"⚠️ MUTABAKAT: {m['symbol']} — {m['neden']}")
        return rep

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

    def set_market_structure(
        self, symbol: str, swing_low: float | None, swing_high: float | None
    ):
        """Son kapanmış mumların swing yapısını ATR stop planına aktarır."""
        self._structure[symbol] = {
            "swing_low": float(swing_low) if swing_low is not None else None,
            "swing_high": float(swing_high) if swing_high is not None else None,
        }

    def _make_position_plan(
        self,
        side: str,
        entry: float,
        stop: float,
        source: str = "RECOVERED",
        atr: float = 0.0,
        tp1_hit: bool = False,
    ) -> dict | None:
        risk_distance = abs(float(entry) - float(stop))
        if entry <= 0 or stop <= 0 or risk_distance <= 0:
            return None
        direction = 1.0 if side == "LONG" else -1.0
        tp1_r = float(self.trade_plan_cfg.get("tp1_r", 1.0))
        tp2_r = float(self.trade_plan_cfg.get("tp2_r", 2.0))
        return {
            "source": source,
            "side": side,
            "entry": float(entry),
            "initial_stop": float(stop),
            "initial_risk": float(risk_distance),
            "atr": float(atr or 0.0),
            "tp1": float(entry + direction * risk_distance * tp1_r),
            "tp2": float(entry + direction * risk_distance * tp2_r),
            "tp1_r": tp1_r,
            "tp2_r": tp2_r,
            "tp1_fraction": float(self.trade_plan_cfg.get("tp1_kapatma_orani", 0.5)),
            "tp1_hit": bool(tp1_hit),
        }

    def _prepare_entry_plan(
        self, symbol: str, side: str, price: float, leverage: int
    ) -> dict:
        if not self.trade_plan_enabled:
            return {
                "accepted": True,
                "stop": self.risk.initial_stop(side, price, leverage),
                "leverage": leverage,
                "source": "YUZDE",
                "atr": 0.0,
                "risk_distance": abs(price - self.risk.initial_stop(side, price, leverage)),
            }
        atr = self._atr.get(symbol)
        structure = self._structure.get(symbol, {})
        plan = self.risk.atr_structure_plan(
            side,
            price,
            float(atr or 0.0),
            leverage,
            swing_low=structure.get("swing_low"),
            swing_high=structure.get("swing_high"),
            atr_mult=float(self.trade_plan_cfg.get("atr_stop_katsayi", 1.5)),
            structure_buffer_atr=float(self.trade_plan_cfg.get("swing_atr_buffer", 0.2)),
            max_stop_pct=float(self.trade_plan_cfg.get("max_stop_yuzde", 12.0)),
        )
        return plan

    def _save_trade_plans(self):
        if self.state_store is not None:
            try:
                self.state_store.set_meta("trade_plans", self._trade_plans)
            except Exception:
                pass

    def _save_position_meta(self):
        if self.state_store is not None:
            try:
                self.state_store.set_meta("position_meta", self._position_meta)
            except Exception as exc:
                print(f"⚠️ Pozisyon ölçüm metadatası kaydedilemedi: {safe_exception_msg(exc)}", flush=True)

    def _close_lock_for(self, symbol: str) -> asyncio.Lock:
        lock = self._close_locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._close_locks[symbol] = lock
        return lock

    def add_position_observer(self, observer) -> None:
        """Salt-okunur paper gözlemcisi ekle; ana emir yolunu asla değiştirme."""
        if observer is not None and observer not in self._position_observers:
            self._position_observers.append(observer)

    def _notify_position_observers(self, method: str, *args) -> None:
        for observer in list(self._position_observers):
            try:
                callback = getattr(observer, method, None)
                if callback is not None:
                    callback(*args)
            except Exception as exc:
                # Telemetri/Shadow hatası gerçek paper pozisyonunu etkilememeli.
                print(
                    f"⚠️ Pozisyon gözlemcisi {method} hatası: {safe_exception_msg(exc)}",
                    flush=True,
                )

    def get_trade_plan(self, symbol: str) -> dict | None:
        plan = self._trade_plans.get(symbol)
        return dict(plan) if plan else None

    def set_supertrend(self, symbol: str, direction: int, value: float):
        """Son kapanmış mumun Supertrend yönünü ve stop çizgisini saklar."""
        try:
            value = float(value)
            if not math.isfinite(value) or value <= 0:
                self._supertrend.pop(symbol, None)
                return
            self._supertrend[symbol] = {
                "direction": 1.0 if int(direction) >= 0 else -1.0,
                "value": value,
            }
        except (TypeError, ValueError, OverflowError):
            self._supertrend.pop(symbol, None)

    def _apply_supertrend_trailing(self, symbol: str, pos: Position, price: float):
        """Kârdaki pozisyonun stopunu yalnızca kâr yönünde sıkılaştırır."""
        if not self.supertrend_trailing:
            return
        if apply_supertrend_trailing(
            pos, price, self._supertrend.get(symbol), self.risk
        ):
            self.stats["supertrend_trail_updates"] = (
                self.stats.get("supertrend_trail_updates", 0) + 1
            )

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

    def _save_funding_clock(self):
        if self.state_store is not None:
            try:
                self.state_store.set_meta("paper_funding_clock", self._funding_last)
            except Exception:
                pass

    def apply_funding(
        self, symbol: str, rate: float | None, mark_price: float, enabled: bool = True
    ) -> float:
        """Gerçek funding oranını geçen süreye oranlayarak paper kasaya uygular."""
        if not enabled or getattr(self.broker, "mode", "paper") != "paper":
            return 0.0
        pos = self.positions.get(symbol)
        now = time.time()
        last = self._funding_last.setdefault(symbol, now)
        if pos is None or rate is None or not math.isfinite(float(rate)) or mark_price <= 0:
            self._funding_last[symbol] = now
            return 0.0
        elapsed = max(0.0, now - last)
        if elapsed < 1.0:
            return 0.0
        direction = 1.0 if pos.side == "LONG" else -1.0
        notional = pos.qty * float(mark_price)
        cash_delta = -direction * notional * float(rate) * elapsed / (8 * 3600.0)
        self._funding_last[symbol] = now
        paper = getattr(self.broker, "paper", None)
        if paper is not None and hasattr(paper, "apply_funding"):
            paper.apply_funding(symbol, cash_delta, float(rate), elapsed)
        self.stats["funding_usdt"] = self.stats.get("funding_usdt", 0.0) + cash_delta
        pos.funding_usdt += cash_delta
        meta = self._position_meta.setdefault(
            symbol, {"position_id": f"recovered-{uuid.uuid4().hex}", "entry_context": {}}
        )
        meta["funding_usdt"] = float(meta.get("funding_usdt", 0.0) or 0.0) + cash_delta
        self._save_position_meta()
        self._save_funding_clock()
        return cash_delta

    def runner_exit_reason(self, pos: Position, price: float, snap: dict) -> str | None:
        """Kâr koşusunda Long satış / Short alış baskısı çıkışını doğrular."""
        return runner_exit_reason(
            pos, price, self.risk.profit_pct(pos, price), snap, self.runner_exit_cfg
        )

    def _position_hold_sec(self, symbol: str, pos: Position) -> float:
        return position_age_seconds(
            pos, opened_ts=self._position_opened_ts.get(symbol)
        )

    @staticmethod
    def _is_risk_free_position(pos: Position) -> bool:
        """Stop seviyesi kâr kilidine veya girişin kâr tarafına geçmiş pozisyon ortak kasada risk taşımaz."""
        if getattr(pos, "locked_profit", False):
            return True
        if pos.side == "LONG" and pos.stop > pos.entry:
            return True
        if pos.side == "SHORT" and 0 < pos.stop < pos.entry:
            return True
        return False

    async def _try_opportunity_swap(self, incoming_symbol: str) -> bool:
        """Çapraz ortak kasa tam doluyken yeni güçlü sinyale yer açmak için en durgun pozisyonu kapatır."""
        candidates: list[tuple[float, float, str, float]] = []
        for sym, pos in list(self.positions.items()):
            if sym == incoming_symbol or self._is_risk_free_position(pos):
                continue
            age_s = self._position_hold_sec(sym, pos)
            if age_s < self.opportunity_swap_min_age_sec:
                continue
            px = float(self.last_prices.get(sym, pos.entry))
            pnl = self.risk.profit_pct(pos, px)
            # Kâr koşusundaki (+%0.25 üstü) pozisyonlara dokunma; durgun/hafif eksidekini seç
            if -1.50 <= pnl <= 0.25:
                candidates.append((pnl, -age_s, sym, px))
        if not candidates:
            return False
        candidates.sort(key=lambda item: (item[0], item[1]))
        weak_pnl, _, weak_sym, weak_px = candidates[0]
        closed = await self._close(
            weak_sym,
            weak_px,
            f"ÇAPRAZ KASA FIRSAT TAKASI ({incoming_symbol} sinyaline yer açıldı)",
            weak_pnl,
        )
        if closed:
            self.stats["opportunity_swaps"] = (
                self.stats.get("opportunity_swaps", 0) + 1
            )
        return closed

    async def maybe_orderflow_exit(self, symbol: str, price: float, snapshot_provider):
        """Order-flow çıkışını sembol başına sınırlı sıklıkta değerlendirir."""
        if not self.runner_exit_enabled:
            return
        pos = self.positions.get(symbol)
        if pos is None:
            return
        now = time.monotonic()
        interval = float(self.runner_exit_cfg.get("orderflow_kontrol_saniye", 1.0))
        if now - self._last_orderflow_exit_check.get(symbol, 0.0) < interval:
            return
        self._last_orderflow_exit_check[symbol] = now
        try:
            snap = snapshot_provider() if callable(snapshot_provider) else snapshot_provider
        except Exception:
            return
        if not isinstance(snap, dict):
            return
        reason = self.runner_exit_reason(pos, price, snap)
        if reason:
            pnl = self.risk.profit_pct(pos, price)
            if await self._close(symbol, price, f"KÂR KOŞUSU: {reason}", pnl):
                self.stats["runner_orderflow_exits"] += 1
            return
        if self.runner_exit_cfg.get("erken_bozulma_cikisi_aktif", False):
            pnl = self.risk.profit_pct(pos, price)
            adverse_reason = stagnant_adverse_exit_reason(
                pos,
                price,
                pnl,
                self._position_hold_sec(symbol, pos),
                snap,
                self._supertrend.get(symbol),
                None,
                self.runner_exit_cfg,
            )
            if adverse_reason:
                if await self._close(symbol, price, adverse_reason, pnl):
                    self.stats["stagnant_adverse_exits"] = (
                        self.stats.get("stagnant_adverse_exits", 0) + 1
                    )

    # -- 1) HER TICK: stop / trailing / kâr kilidi + Çapraz Kurtarma -------------
    async def on_price_tick(self, symbol: str, price: float):
        self.last_prices[symbol] = price
        if self.circuit_breaker is not None:
            if hasattr(self.circuit_breaker, "evaluate_price_shock"):
                shock = self.circuit_breaker.evaluate_price_shock(symbol, price)
                if shock.get("triggered"):
                    if shock.get("scope") == "global":
                        await self._say(
                            f"🚨 CIRCUIT BREAKER: {self.circuit_breaker.trip_reason}"
                        )
                        await self.close_all_positions("FLASH CRASH SİGORTASI")
                        return
                    if shock.get("scope") == "symbol":
                        self.stats["altcoin_shock_isolated"] = (
                            self.stats.get("altcoin_shock_isolated", 0) + 1
                        )
                        pos_shocked = self.positions.get(symbol)
                        if pos_shocked is not None:
                            move_pct = float(shock.get("move_pct") or 0.0)
                            pnl_shock = self.risk.profit_pct(pos_shocked, price)
                            await self._say(
                                f"⚠️ TEKİL PARİTE ŞOKU KORUMASI: {symbol} %{move_pct:.2f} hareket — "
                                f"yalnızca {symbol} kapatılıyor (diğer pozisyonlar korunuyor)."
                            )
                            await self._close(
                                symbol,
                                price,
                                f"ALTCOIN FİYAT ŞOKU KORUMASI (%{move_pct:.2f})",
                                pnl_shock,
                            )
                            return
            elif self.circuit_breaker.check_price_shock(symbol, price):
                await self._say(
                    f"🚨 CIRCUIT BREAKER: {self.circuit_breaker.trip_reason}"
                )
                await self.close_all_positions("FLASH CRASH SİGORTASI")
                return

        pos = self.positions.get(symbol)
        if pos is not None:
            old_stop_before = pos.stop
            old_lock_before = pos.locked_profit
            plan = self._trade_plans.get(symbol)
            if plan:
                tp2_hit = (
                    pos.side == "LONG" and price >= float(plan["tp2"])
                ) or (
                    pos.side == "SHORT" and price <= float(plan["tp2"])
                )
                if tp2_hit:
                    pnl = self.risk.profit_pct(pos, price)
                    closed = await self._close(
                        symbol, price, f"{plan.get('source', 'R')} TP2 (2R)", pnl
                    )
                    if closed:
                        self.stats["tp2_closes"] += 1
                    return
                tp1_hit = (
                    pos.side == "LONG" and price >= float(plan["tp1"])
                ) or (
                    pos.side == "SHORT" and price <= float(plan["tp1"])
                )
                if not plan.get("tp1_hit") and tp1_hit:
                    before_qty = pos.qty
                    if pos.side == "LONG":
                        pos.stop = max(pos.stop, pos.entry)
                    else:
                        pos.stop = min(pos.stop, pos.entry)
                    fraction = min(0.95, max(0.05, float(plan.get("tp1_fraction", 0.5))))
                    pnl = self.risk.profit_pct(pos, price)
                    await self._close(
                        symbol,
                        price,
                        f"{plan.get('source', 'R')} TP1 (1R) başabaş",
                        pnl,
                        qty_override=before_qty * fraction,
                    )
                    if symbol not in self.positions:
                        return
                    if pos.qty < before_qty:
                        plan["tp1_hit"] = True
                        plan["tp1_qty"] = before_qty - pos.qty
                        self.stats["tp1_partial_closes"] += 1
                    self._save_trade_plans()
            self._apply_supertrend_trailing(symbol, pos, price)
            res = self.risk.update(pos, price)
            if res["action"] == "close":
                await self._close(symbol, price, res["reason"], res["pnl_pct"])
                return

            if (
                self.state_store is not None
                and (pos.stop != old_stop_before or pos.locked_profit != old_lock_before)
            ):
                try:
                    self.state_store.save_position(pos, exchange=pos.exchange or None)
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
        """Çapraz kurtarmayı tek sıraya alır ve kararı güncel durumla yeniler."""
        async with self._pair_rescue_lock:
            # İlk karar ile sıra bekleme arasında fiyat/pozisyon değişmiş
            # olabilir. Eski rescue sözlüğünü kullanmak yerine yeniden hesapla.
            fresh = self.risk.find_pair_rescue(self.positions, self.last_prices)
            if not fresh or fresh.get("action") != "pair_close":
                return False
            return await self._execute_pair_rescue_unlocked(fresh)

    async def _execute_pair_rescue_unlocked(self, rescue: dict):
        """Kilit altında iki bacağı kapatır; her bacak ayrıca idempotenttir."""
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
        entry_context: dict | None = None,
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
            if self.runner_exit_cfg.get("erken_bozulma_cikisi_aktif", False):
                snap_ctx = (entry_context or {}).get("orderflow")
                if not isinstance(snap_ctx, dict):
                    snap_ctx = {"score": flow_score}
                adverse_reason = stagnant_adverse_exit_reason(
                    pos,
                    price,
                    pnl,
                    self._position_hold_sec(symbol, pos),
                    snap_ctx,
                    self._supertrend.get(symbol),
                    combined,
                    self.runner_exit_cfg,
                )
                if adverse_reason:
                    if await self._close(symbol, price, adverse_reason, pnl):
                        self.stats["stagnant_adverse_exits"] = (
                            self.stats.get("stagnant_adverse_exits", 0) + 1
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
            if hasattr(self.circuit_breaker, "is_symbol_in_shock"):
                in_shock, _ = self.circuit_breaker.is_symbol_in_shock(symbol)
                if in_shock:
                    self.stats["altcoin_shock_filtered"] = (
                        self.stats.get("altcoin_shock_filtered", 0) + 1
                    )
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
        if dec["action"] == "yok" and combined.get("orderflow_veto"):
            self.stats["orderflow_filtered"] = self.stats.get("orderflow_filtered", 0) + 1
            return
        if dec["action"] == "yok" and "PİYASA REJİMİ/ONAY FİLTRESİ" in str(
            dec.get("reason", "")
        ):
            self.stats["regime_filtered"] = self.stats.get("regime_filtered", 0) + 1
            return
        if dec["action"] in ("LONG", "SHORT"):
            if self.dedup_twin_assets:
                cand_root = canonical_underlying_asset(symbol)
                if cand_root:
                    twin_sym = next(
                        (
                            open_sym
                            for open_sym in self.positions
                            if open_sym != symbol
                            and canonical_underlying_asset(open_sym) == cand_root
                        ),
                        None,
                    )
                    if twin_sym is not None:
                        self.stats["twin_symbol_filtered"] = (
                            self.stats.get("twin_symbol_filtered", 0) + 1
                        )
                        await self._say(
                            f"⛔ {symbol}: giriş engellendi — ikiz dayanak varlık zaten açık ({twin_sym})"
                        )
                        return

            if self.min_bb_width_pct > 0 or self.min_atr_pct > 0:
                ind_ctx = (entry_context or {}).get("indicators") or {}
                snap_ctx = ind_ctx.get("snapshot") or {}
                has_vol_metric = any(
                    float(ind_ctx.get(k, snap_ctx.get(k, 0.0)) or 0.0) > 0
                    for k in ("atr_pct", "bollinger_bandwidth_pct", "bb_width_pct", "atr")
                )
                if has_vol_metric:
                    vq = volatility_quality(
                        ind_ctx,
                        {
                            "min_bb_genisligi_yuzde": self.min_bb_width_pct,
                            "min_atr_yuzde": self.min_atr_pct,
                            "komisyon_taker_yuzde": self.exit_fee_pct,
                            "orderflow_min_kar_yuzde": float(
                                self.runner_exit_cfg.get("orderflow_min_kar_yuzde", 0.5)
                            ),
                        },
                    )
                    if not vq["accepted"]:
                        self.stats["volatility_filtered"] = (
                            self.stats.get("volatility_filtered", 0) + 1
                        )
                        return

            all_green = self._all_positions_in_profit()
            ok, why = self.risk.can_open(
                len(self.positions),
                all_in_profit=all_green,
                side=dec["action"],
                open_sides=[p.side for p in self.positions.values()],
            )
            if not ok:
                await self._say(f"⛔ {symbol}: giriş engellendi — {why}")
                return
            await self._open(
                symbol, dec["action"], price, dec["reason"], entry_context=entry_context
            )

    # -- emir işlemleri --------------------------------------------------------------
    def _calc_qty(
        self,
        balance: float,
        price: float,
        stop: float,
        symbol: str,
        leverage_override: int | None = None,
        force_risk_based: bool = False,
    ) -> tuple[float, dict]:
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        fixed_margin_mode = self.sizer is None or getattr(self.sizer, "mode", None) == "kasa_10_20x"
        if force_risk_based and fixed_margin_mode:
            qty = self.risk.position_size(max(balance, 0), price, stop)
            return qty, {
                "kaynak": "ATR_YAPI_RISK",
                "risk_pct": self.risk.risk_per_trade_pct,
                "leverage": lev,
                "margin_usdt": round((qty * price) / max(1, lev), 2),
                "notional": round(qty * price, 2),
                "neden": "ATR/swing başlangıç stopu mesafesi",
            }
        if self.sizer is not None:
            atr = self._atr.get(symbol)
            return self.sizer.size(
                balance, price, stop, atr, leverage_override=leverage_override
            )
        qty = self.risk.position_size(max(balance, 0), price, stop)
        return qty, {
            "kaynak": "sabit",
            "risk_pct": self.risk.risk_per_trade_pct,
            "leverage": lev,
            "margin_usdt": round((qty * price) / max(1, lev), 2),
            "notional": round(qty * price, 2),
        }

    async def _open(
        self,
        symbol: str,
        side: str,
        price: float,
        reason: str,
        entry_context: dict | None = None,
    ):
        balance = await self.broker.fetch_balance_usdt()
        self._last_balance = balance
        is_cross = getattr(self.risk, "margin_mode", "isolated") == "cross"
        pool_balance = (
            balance + self.total_unrealized_usdt() if is_cross else balance
        )
        dyn_lev, lev_why = self.get_dynamic_leverage(symbol, price)
        prepared = self._prepare_entry_plan(symbol, side, price, dyn_lev)
        if not prepared.get("accepted"):
            self.stats["atr_plan_rejects"] += 1
            await self._say(
                f"⛔ {symbol}: ATR/swing işlem planı reddedildi — {prepared.get('reason')}"
            )
            return
        stop = float(prepared["stop"])
        dyn_lev = int(prepared.get("leverage") or dyn_lev)
        self.active_leverage[symbol] = dyn_lev
        if prepared.get("leverage_reduced"):
            lev_why += f" | {prepared.get('reason')}"
        qty, info = self._calc_qty(
            pool_balance,
            price,
            stop,
            symbol,
            leverage_override=dyn_lev,
            force_risk_based=self.trade_plan_enabled,
        )
        if qty <= 0:
            await self._say(
                f"⛔ {symbol}: miktar hesaplanamadı "
                f"({info.get('neden', 'yetersiz bakiye')})."
            )
            return
        add_margin = float(info.get("margin_usdt") or 0.0)
        if is_cross and hasattr(self.risk, "cross_pool_ok"):
            active_margin = sum(
                p.margin_usdt
                for p in self.positions.values()
                if not self._is_risk_free_position(p)
            )
            total_notional = sum(
                abs(p.qty) * float(self.last_prices.get(sym, p.entry))
                for sym, p in self.positions.items()
            ) + abs(qty * price)
            m_ok, m_why = self.risk.cross_pool_ok(
                active_margin, add_margin, pool_balance, total_notional
            )
            if not m_ok and self.opportunity_swap_enabled:
                swapped = await self._try_opportunity_swap(symbol)
                if swapped:
                    balance = await self.broker.fetch_balance_usdt()
                    self._last_balance = balance
                    pool_balance = balance + self.total_unrealized_usdt()
                    active_margin = sum(
                        p.margin_usdt
                        for p in self.positions.values()
                        if not self._is_risk_free_position(p)
                    )
                    total_notional = sum(
                        abs(p.qty) * float(self.last_prices.get(sym, p.entry))
                        for sym, p in self.positions.items()
                    ) + abs(qty * price)
                    m_ok, m_why = self.risk.cross_pool_ok(
                        active_margin, add_margin, pool_balance, total_notional
                    )
        else:
            used_margin = sum(p.margin_usdt for p in self.positions.values())
            m_ok, m_why = self.risk.margin_cap_ok(
                used_margin, add_margin, balance
            )
        if not m_ok:
            await self._say(f"⛔ {symbol}: giriş engellendi — {m_why}")
            return
        try:
            ex_name, best_px = await self.broker.best_price(symbol, side)
        except Exception as e:
            if getattr(self.broker, "mode", "paper") != "paper":
                await self._say(f"⛔ {symbol}: güncel fiyat alınamadığı için giriş yapılmadı ({safe_exception_msg(e)})")
                return
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

        requested_qty = qty
        qty = float(fill.get("qty") if fill.get("qty") is not None else requested_qty)
        fill_px = float(fill.get("price") or best_px)
        if qty <= 0 or fill_px <= 0:
            await self._say(f"⛔ {symbol}: emir dolmadı; yerel pozisyon oluşturulmadı.")
            return
        lev = int(info.get("leverage") or dyn_lev)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        margin_usdt = float(
            fill.get("margin_usdt")
            or (estimated_margin * qty / requested_qty if estimated_margin and requested_qty else 0.0)
            or (fill_px * qty) / max(1, lev)
        )
        if abs(qty - requested_qty) > requested_qty * 1e-6:
            await self._say(
                f"ℹ️ {symbol}: emir kısmi doldu; istenen {requested_qty:.8f}, gerçekleşen {qty:.8f}."
            )

        if self.trade_plan_enabled:
            direction = 1.0 if side == "LONG" else -1.0
            final_stop = fill_px - direction * float(prepared["risk_distance"])
            trade_plan = self._make_position_plan(
                side,
                fill_px,
                final_stop,
                source=str(prepared.get("source") or "ATR"),
                atr=float(prepared.get("atr") or 0.0),
            )
        else:
            final_stop = self.risk.initial_stop(side, fill_px, lev)
            trade_plan = None
        pos = Position(
            symbol=symbol,
            side=side,
            entry=fill_px,
            qty=qty,
            stop=final_stop,
            leverage=lev,
            margin_usdt=round(margin_usdt, 2),
            layers=1,
            last_add_price=fill_px,
            exchange=ex_name,
            entry_fee_usdt=float(fill.get("fee") or 0.0),
            exit_fee_pct=self.exit_fee_pct,
            net_breakeven_enabled=self.net_breakeven_enabled,
            net_profit_buffer_usdt=self.net_profit_buffer_usdt,
        )
        self.positions[symbol] = pos
        opened_now_ts = time.time()
        self._position_opened_ts[symbol] = opened_now_ts
        position_id = uuid.uuid4().hex
        context = json.loads(
            json.dumps(dict(entry_context or {}), ensure_ascii=False, default=str)
        )
        context.update(
            {
                "entry_reason": reason,
                "side": side,
                "entry_price": float(fill_px),
                "leverage": int(lev),
                "margin_usdt": float(margin_usdt),
                "exchange": ex_name,
            }
        )
        # Yalnız gerçek fill sonrası ölçülür; reddedilen sinyaller veya risk
        # tarafından kabul edilmeyen adaylar performans kohortuna girmez.
        try:
            context["attribution"] = build_entry_attribution(
                self.strategy, context, side
            )
        except Exception as exc:
            context["attribution_error"] = safe_exception_msg(exc)
        self._position_meta[symbol] = {
            "position_id": position_id,
            "opened_ts": opened_now_ts,
            "entry_context": context,
            "entry_fee_usdt": float(fill.get("fee") or 0.0),
            "funding_usdt": 0.0,
        }
        self._save_position_meta()
        print(
            "🧾 GİRİŞ VERİSİ | "
            f"{position_id} | {symbol} | "
            + json.dumps(context, ensure_ascii=False, default=str, separators=(",", ":")),
            flush=True,
        )
        if trade_plan is not None:
            self._trade_plans[symbol] = trade_plan
            self._save_trade_plans()
        self.last_prices[symbol] = fill_px
        self._last_add_ts[symbol] = time.time()
        self._funding_last[symbol] = time.time()
        self._save_funding_clock()

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

        self._notify_position_observers(
            "on_baseline_open", symbol, pos, position_id, context, fill
        )
        actual_stop_pct = abs(fill_px - pos.stop) / fill_px * 100.0
        estimated_stop_loss = abs(fill_px - pos.stop) * qty
        plan_note = ""
        if trade_plan is not None:
            plan_note = (
                f" | TP1: {trade_plan['tp1']:,.4f} (1R/%{trade_plan['tp1_fraction'] * 100:.0f})"
                f" | TP2: {trade_plan['tp2']:,.4f} (2R)"
            )
        await self._say(
            f"🟢 {side} AÇILDI | {symbol} @ {fill_px:,.4f} | {lev}x Kaldıraç ({lev_why}) | "
            f"Marj: ${margin_usdt:,.2f} (%{info.get('risk_pct')}) | "
            f"Emir: {fill.get('emir_tipi', '?')} | Stop: {pos.stop:,.4f} "
            f"(%{actual_stop_pct:.2f} / ~${estimated_stop_loss:,.2f} fiyat K/Z)"
            f"{plan_note} | Koruma: {prot_note} | Neden: {reason}"
        )

    async def _add_layer(self, symbol: str, price: float, reason: str):
        """Artıdaki pozisyona aktif risk/boyutlandırma modeliyle kademe ekler."""
        pos = self.positions.get(symbol)
        if pos is None:
            return
        existing_plan = self._trade_plans.get(symbol)
        if existing_plan and existing_plan.get("tp1_hit"):
            return  # TP1 sonrası kalan 2R koşusuna yeni risk eklenmez.
        balance = await self.broker.fetch_balance_usdt()
        self._last_balance = balance
        dyn_lev, _ = self.get_dynamic_leverage(symbol, price)
        prepared = self._prepare_entry_plan(symbol, pos.side, price, dyn_lev)
        if not prepared.get("accepted"):
            self.stats["atr_plan_rejects"] += 1
            return
        stop = float(prepared["stop"])
        dyn_lev = int(prepared.get("leverage") or dyn_lev)
        add_qty, info = self._calc_qty(
            balance,
            price,
            stop,
            symbol,
            leverage_override=dyn_lev,
            force_risk_based=self.trade_plan_enabled,
        )
        if add_qty <= 0:
            return
        used_margin = sum(p.margin_usdt for p in self.positions.values())
        m_ok, m_why = self.risk.margin_cap_ok(
            used_margin, float(info.get("margin_usdt") or 0.0), balance
        )
        if not m_ok:
            self._last_add_ts[symbol] = time.time()  # tekrar tekrar denemesin
            await self._say(f"⛔ {symbol}: kademe eklenmedi — {m_why}")
            return
        try:
            if pos.exchange:
                # Kademe, mevcut pozisyonla AYNI borsada açılır. Failover yalnızca
                # yeni pozisyonlar içindir; iki borsadaki miktar birleştirilemez.
                ex_name = pos.exchange
                best_px = await self.broker.fetch_price(symbol, ex_name)
            else:
                ex_name, best_px = await self.broker.best_price(symbol, pos.side)
        except Exception as e:
            if getattr(self.broker, "mode", "paper") != "paper":
                await self._say(f"⛔ {symbol}: güncel fiyat alınamadığı için kademe eklenmedi ({safe_exception_msg(e)})")
                return
            ex_name, best_px = pos.exchange or self.broker.primary, price
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

        requested_add_qty = add_qty
        add_qty = float(fill.get("qty") if fill.get("qty") is not None else requested_add_qty)
        fill_px = float(fill.get("price") or best_px)
        if add_qty <= 0 or fill_px <= 0:
            await self._say(f"⛔ {symbol}: kademe emri dolmadı; mevcut pozisyon değiştirilmedi.")
            return
        lev = int(info.get("leverage") or pos.leverage)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        add_margin = float(
            fill.get("margin_usdt")
            or (estimated_margin * add_qty / requested_add_qty if estimated_margin and requested_add_qty else 0.0)
            or (fill_px * add_qty) / max(1, lev)
        )

        pos.add_layer(
            add_price=fill_px,
            add_qty=add_qty,
            add_margin_usdt=add_margin,
            stop_loss_pct=self.risk.effective_stop_pct(lev),
        )
        if self.trade_plan_enabled or existing_plan:
            new_plan = self._make_position_plan(
                pos.side,
                pos.entry,
                pos.stop,
                source=str(prepared.get("source") or "ATR"),
                atr=float(prepared.get("atr") or 0.0),
            )
            if new_plan is not None:
                self._trade_plans[symbol] = new_plan
                self._save_trade_plans()
        layer_meta = self._position_meta.get(symbol)
        if layer_meta is not None:
            layer_meta["entry_fee_usdt"] = float(
                layer_meta.get("entry_fee_usdt", 0.0) or 0.0
            ) + float(fill.get("fee") or 0.0)
            pos.entry_fee_usdt += float(fill.get("fee") or 0.0)
            self._save_position_meta()
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
        self,
        symbol: str,
        price: float,
        reason: str,
        pnl_pct: float,
        qty_override: float | None = None,
    ) -> bool:
        """Kapanışları sembol bazında sıraya alır; tekrarlar emir üretmez."""
        async with self._close_lock_for(symbol):
            return await self._close_unlocked(
                symbol, price, reason, pnl_pct, qty_override=qty_override
            )

    async def _close_unlocked(
        self,
        symbol: str,
        price: float,
        reason: str,
        pnl_pct: float,
        qty_override: float | None = None,
    ) -> bool:
        """Kilit altındaki gerçek kapama; yalnız gerçekleşen miktarı düşer.

        Emir hatasında yerel pozisyon, native koruma ve SQLite kaydı bilinçli
        olarak korunur. Aksi davranış borsada açık kalan pozisyonun bot
        tarafından izlenmemesine (sahipsiz pozisyona) yol açar.
        """
        pos = self.positions.get(symbol)
        if not pos:
            return False
        position_meta = dict(self._position_meta.get(symbol) or {})
        position_id = str(position_meta.get("position_id") or f"legacy-{uuid.uuid4().hex}")
        entry_context = position_meta.get("entry_context") or {}
        if symbol not in self._position_meta:
            self._position_meta[symbol] = {
                "position_id": position_id,
                "entry_context": entry_context,
            }
            self._save_position_meta()

        requested_qty = pos.qty if qty_override is None else min(pos.qty, float(qty_override))
        if requested_qty <= 0:
            return False
        order_side = "sell" if pos.side == "LONG" else "buy"
        try:
            # reduceOnly, kapama sırasında ters yönde yeni pozisyon açılmasını
            # önler. Eski paper double'ları için geriye dönük uyumluluk korunur.
            if getattr(self.broker, "mode", "paper") == "paper":
                try:
                    fill = await self.broker.market_order(
                        symbol, order_side, requested_qty, price_hint=price,
                        exchange=pos.exchange or None, reduce_only=True
                    )
                except TypeError:
                    fill = await self.broker.market_order(
                        symbol, order_side, requested_qty, price_hint=price,
                        exchange=pos.exchange or None
                    )
            else:
                fill = await self.broker.market_order(
                    symbol, order_side, requested_qty, price_hint=price,
                    exchange=pos.exchange or None, reduce_only=True
                )
            if not isinstance(fill, dict):
                fill = {}
            fill_price = float(fill.get("price") or price)
            if fill_price <= 0:
                raise RuntimeError("Kapama emri için geçerli gerçekleşme fiyatı yok")
            filled_qty = float(fill.get("qty") if fill.get("qty") is not None else requested_qty)
            if filled_qty <= 0:
                raise RuntimeError("Kapama emri dolmadı")
            closed_qty = min(requested_qty, filled_qty)
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_success()
        except Exception as e:
            err_safe = safe_exception_msg(e)
            await self._say(
                f"⚠️ {symbol} kapama emri hatası: {err_safe} — "
                "pozisyon ve koruması izlenmeye devam ediyor; işlem geçmişi yazılmadı."
            )
            if self.circuit_breaker is not None:
                if self.circuit_breaker.record_order_error(e):
                    await self._say(f"🚨 SİGORTA ATTI: {self.circuit_breaker.trip_reason}")
            return False

        original_qty = pos.qty
        closed_margin = pos.margin_usdt * (closed_qty / original_qty)
        remaining_qty = max(0.0, original_qty - closed_qty)
        fully_closed = remaining_qty <= max(original_qty * 1e-9, 1e-12)
        actual_pnl_pct = self.risk.profit_pct(pos, fill_price)
        roe_pct = self.risk.roe_pct(pos, fill_price)
        direction = 1.0 if pos.side == "LONG" else -1.0
        pnl_usdt = direction * (fill_price - pos.entry) * closed_qty
        excursion_usdt = direction * (fill_price - pos.entry) * original_qty
        pos.mfe_usdt = max(pos.mfe_usdt, excursion_usdt)
        pos.mae_usdt = min(pos.mae_usdt, excursion_usdt)
        close_fraction = closed_qty / original_qty
        entry_fee = float(position_meta.get("entry_fee_usdt", 0.0) or 0.0) * close_fraction
        funding = float(position_meta.get("funding_usdt", 0.0) or 0.0) * close_fraction
        exit_fee = float(fill.get("fee") or 0.0)
        if filled_qty > 0:
            exit_fee *= closed_qty / filled_qty
        net_pnl = pnl_usdt - entry_fee - exit_fee + funding

        if fully_closed:
            self.positions.pop(symbol, None)
            self._position_opened_ts.pop(symbol, None)
            self._position_meta.pop(symbol, None)
            self._save_position_meta()
            self._trade_plans.pop(symbol, None)
            self._save_trade_plans()
            self._funding_last.pop(symbol, None)
            self._save_funding_clock()
            prot = self._prot.pop(symbol, None)
            self._prot_stop.pop(symbol, None)
            try:
                cancelled = await self.broker.cancel_protection(symbol, prot)
                if cancelled is False:
                    await self._say(f"⚠️ {symbol}: kapandı ancak eski koruma emri iptal edilemedi; borsada kontrol edin.")
            except Exception as e:
                await self._say(
                    f"⚠️ {symbol}: kapandı ancak koruma iptali başarısız: {safe_exception_msg(e)}"
                )
        else:
            pos.qty = remaining_qty
            pos.margin_usdt *= remaining_qty / original_qty
            remaining_meta = self._position_meta.setdefault(symbol, position_meta)
            remaining_meta["entry_fee_usdt"] = max(
                0.0, float(remaining_meta.get("entry_fee_usdt", 0.0) or 0.0) - entry_fee
            )
            remaining_meta["funding_usdt"] = (
                float(remaining_meta.get("funding_usdt", 0.0) or 0.0) - funding
            )
            pos.entry_fee_usdt = max(0.0, pos.entry_fee_usdt - entry_fee)
            pos.funding_usdt -= funding
            self._save_position_meta()
            if (
                self.protection_on
                and getattr(self.broker, "mode", "paper") != "paper"
                and symbol in self._prot
            ):
                try:
                    new_prot = await self.broker.replace_protection(
                        symbol,
                        pos.side,
                        pos.qty,
                        pos.stop,
                        self._prot[symbol],
                        pos.exchange or None,
                    )
                    self._prot[symbol] = new_prot
                    self._prot_stop[symbol] = pos.stop
                    self._last_replace[symbol] = time.time()
                except Exception as e:
                    await self._say(
                        f"⚠️ {symbol}: kısmî kapama sonrası koruma miktarı güncellenemedi: {safe_exception_msg(e)}"
                    )

        if getattr(self.broker, "mode", "paper") == "paper" and hasattr(self.broker, "paper"):
            self.broker.paper.realize_pnl(pnl_usdt)

        trade_record = {
            "ts": time.time(),
            "symbol": symbol,
            "side": pos.side,
            "entry": pos.entry,
            "exit_price": fill_price,
            "qty": closed_qty,
            "pnl_pct": actual_pnl_pct,
            "reason": reason if fully_closed else f"KISMİ KAPAMA — {reason}",
            "leverage": pos.leverage,
            "margin_usdt": closed_margin,
            "pnl_usdt": pnl_usdt,
            "layers": pos.layers,
            "position_id": position_id,
            "entry_context": entry_context,
            "exchange": pos.exchange or "",
            "entry_fee_usdt": entry_fee,
            "exit_fee_usdt": exit_fee,
            "funding_usdt": funding,
            "net_pnl_usdt": net_pnl,
            "mfe_usdt": pos.mfe_usdt,
            "mae_usdt": pos.mae_usdt,
            "stop_price": pos.stop,
            "net_breakeven_price": (
                self.risk.net_breakeven_price(pos)
                if pos.net_breakeven_enabled and pos.exit_fee_pct > 0
                else None
            ),
        }
        if self.state_store is not None:
            try:
                if fully_closed:
                    self.state_store.delete_position(symbol)
                else:
                    self.state_store.save_position(pos)
            except Exception as e:
                await self._say(f"⚠️ {symbol} açık pozisyon kaydı güncellenemedi: {safe_exception_msg(e)}")
            try:
                self.state_store.record_trade(**trade_record)
            except Exception as e:
                await self._say(f"⚠️ {symbol} işlem geçmişi kaydedilemedi: {safe_exception_msg(e)}")
        self._notify_position_observers(
            "on_baseline_close", symbol, pos, trade_record, fully_closed
        )
        print(
            "🧾 KAPANIŞ VERİSİ | "
            f"{position_id} | {symbol} | {reason} | "
            f"gerçekleşen miktar={closed_qty:.10g} | brüt K/Z=${pnl_usdt:+.2f} | "
            f"ücret=${entry_fee + exit_fee:.4f} | funding=${funding:+.4f} | "
            f"net K/Z=${net_pnl:+.2f}",
            flush=True,
        )

        if self._last_balance > 0:
            eq_pct = self.risk.equity_pnl_pct(pnl_usdt, self._last_balance)
        else:
            eq_pct = (
                actual_pnl_pct
                * max(1, pos.leverage)
                * self.risk.capital_pct_per_entry
                / 100.0
            )
        self.risk.register_close(eq_pct)
        if self.circuit_breaker is not None:
            if self.circuit_breaker.record_trade_pnl(eq_pct):
                await self._say(f"🚨 SİGORTA ATTI: {self.circuit_breaker.trip_reason}")

        if self.sizer is not None:
            try:
                self.sizer.kelly.record(actual_pnl_pct)
            except Exception as e:
                print(f"⚠️ Kelly kaydı yazılamadı: {safe_exception_msg(e)}", flush=True)

        self.stats["trades"] += 1
        self.stats["pnl_pct_sum"] += actual_pnl_pct
        self.stats["pnl_usdt_sum"] = round(self.stats["pnl_usdt_sum"] + pnl_usdt, 2)
        if actual_pnl_pct >= 0:
            self.stats["wins"] += 1
            emoji = "✅"
        else:
            self.stats["losses"] += 1
            emoji = "🔴"

        if fully_closed:
            self._cooldown_until[symbol] = time.time() + self.cooldown_sec
            kilit = " 🔒(kâr kilidi aktifti)" if pos.locked_profit else ""
            await self._say(
                f"{emoji} POZİSYON KAPANDI | {pos.side} {symbol} ({pos.layers} kademe, {pos.leverage}x) "
                f"@ {fill_price:,.4f} | Fiyat PnL: %{actual_pnl_pct:+.2f} | ROE: %{roe_pct:+.1f} | "
                f"Fiyat K/Z: ${pnl_usdt:+.2f} | Net K/Z: ${net_pnl:+.2f} "
                f"(ücret ${entry_fee + exit_fee:.4f}, funding ${funding:+.4f})"
                f"{kilit} | Neden: {reason}"
            )
            return True

        await self._say(
            f"⚠️ {symbol} KISMİ KAPANDI | {closed_qty:.8f} kapandı, {remaining_qty:.8f} açık | "
            f"Gerçekleşme: {fill_price:,.4f} | Fiyat K/Z: ${pnl_usdt:+.2f}"
        )
        return False

    async def close_all_positions(
        self, reason: str = "ACİL DURUM KILL-SWITCH", urgent: bool = True
    ):
        """Tüm açık pozisyonları kapat; süre sonu ile acil mesajı birbirinden ayır."""
        symbols = list(self.positions.keys())
        if not symbols:
            if urgent:
                await self._say(f"🛑 [{reason}] Açık pozisyon yok, bot kilitlendi.")
            else:
                await self._say(f"🕒 [{reason}] Açık pozisyon yok; rapor hazırlanıyor.")
            return 0
        if urgent:
            await self._say(
                f"🚨 [{reason}] {len(symbols)} açık pozisyon ACİL KAPATILIYOR: {', '.join(symbols)}"
            )
        else:
            await self._say(
                f"🕒 [{reason}] {len(symbols)} açık pozisyon kontrollü kapatılıyor."
            )
        closed_count = 0
        for sym in symbols:
            pos = self.positions.get(sym)
            if not pos:
                continue
            px = self.last_prices.get(sym) or pos.entry
            pnl = self.risk.profit_pct(pos, px)
            if await self._close(sym, px, reason, pnl):
                closed_count += 1
        return closed_count
