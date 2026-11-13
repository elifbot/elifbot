"""Borsa bağlantıları: Binance + OKX üzerinden ccxt
+ Multi-Exchange Failover (Borsa Kesinti Sigortası: 3 Timeout → Otomatik Yedek Borsa)
+ Dinamik 20x/10x/5x Vadeli + %0.30 Kayma Filtresi & Chase Order + OCO/Stop Koruma.

Multi-Exchange Failover (Yedekleme):
  • Bir borsadan (örn. Binance) ard arda 3 kez zaman aşımı (timeout) veya ağ/kesinti
    hatası alınırsa, bot o borsayı geçici olarak devre dışı (degraded) işaretler ve
    tüm yeni pozisyonları / veri isteklerini anında yedek borsaya (OKX) kaydırır.
"""
from __future__ import annotations

import asyncio
import time

from .security import mask_secrets, safe_exception_msg

_TIMEOUT_KEYWORDS = (
    "timeout",
    "timed out",
    "requesttimeout",
    "networkerror",
    "exchangenotavailable",
    "ddosprotection",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "http 502",
    "http 503",
    "http 504",
    "connection reset",
    "connection refused",
)


def is_timeout_or_network_error(err: object) -> bool:
    """Hatanın zaman aşımı (timeout) veya borsa erişim kesintisi olup olmadığını döner."""
    if isinstance(err, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    cls_name = type(err).__name__.lower()
    txt = f"{cls_name} {err}".lower()
    return any(k in txt for k in _TIMEOUT_KEYWORDS)


class PaperBroker:
    """Sanal borsa: gerçek fiyatlarla, 20x kaldıraç, komisyon ve kayma (slippage) simülasyonu."""

    def __init__(
        self,
        balance_usdt: float = 10_000.0,
        fee_taker_pct: float = 0.05,
        fee_maker_pct: float = 0.02,
        max_slippage_pct: float = 0.30,
    ):
        self.balance = balance_usdt
        self.start_balance = balance_usdt
        self.fee_taker_pct = fee_taker_pct
        self.fee_maker_pct = fee_maker_pct
        self.max_slippage_pct = max_slippage_pct
        self.trades: list[dict] = []
        self.protections: dict[str, dict] = {}

    def _fill(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee_pct: float,
        kind: str,
        slippage_pct: float = 0.0,
        exchange: str = "binance",
    ) -> dict:
        fee = qty * price * fee_pct / 100
        self.balance -= fee
        fill = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "fee": round(fee, 2),
            "slippage_pct": round(slippage_pct, 4),
            "ts": time.time(),
            "mode": "paper",
            "exchange": exchange,
            "emir_tipi": kind,
            "status": "filled",
        }
        self.trades.append(fill)
        return fill

    def realize_pnl(self, pnl_usdt: float):
        """Pozisyon kapandığında gerçekleşen dolar kâr/zararını kasaya işler."""
        self.balance = round(self.balance + float(pnl_usdt), 4)

    def market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        exchange: str = "binance",
    ) -> dict:
        return self._fill(
            symbol, side, qty, price, self.fee_taker_pct, "market", exchange=exchange
        )

    def maker_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        exchange: str = "binance",
    ) -> dict:
        return self._fill(
            symbol, side, qty, price, self.fee_maker_pct, "maker", exchange=exchange
        )

    def chase_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        expected_price: float,
        current_market_price: float,
        max_slip_pct: float | None = None,
        exchange: str = "binance",
    ) -> dict:
        """Fiyat emir seviyesinden >%0.3 uzaklaştığında devreye giren Chase Order (Takip Eden Limit)."""
        tol = max_slip_pct if max_slip_pct is not None else self.max_slippage_pct
        raw_slip = (
            abs(current_market_price - expected_price)
            / max(expected_price, 1e-12)
            * 100.0
        )
        if side == "buy":
            cap_px = expected_price * (1.0 + tol / 100.0)
            chase_px = min(current_market_price, cap_px)
        else:
            cap_px = expected_price * (1.0 - tol / 100.0)
            chase_px = max(current_market_price, cap_px)

        eff_slip = (
            abs(chase_px - expected_price) / max(expected_price, 1e-12) * 100.0
        )
        fill = self._fill(
            symbol,
            side,
            qty,
            round(chase_px, 6),
            self.fee_maker_pct,
            "chase_limit",
            slippage_pct=eff_slip,
            exchange=exchange,
        )
        fill["raw_slippage_pct"] = round(raw_slip, 4)
        fill["saved_slippage_pct"] = round(max(0.0, raw_slip - eff_slip), 4)
        return fill


class ExchangeManager:
    def __init__(self, cfg: dict):
        api = cfg.get("api", {})
        self.mode = cfg["genel"].get("mod", "paper")
        self.symbols = cfg["genel"].get("semboller", ["BTC/USDT"])
        self.leverage = int(cfg["genel"].get("kaldıraç", 20) or 20)
        em = cfg.get("emirler", {})
        rk = cfg.get("risk", {})
        sg = cfg.get("sigorta", {})
        self.max_slippage_pct = float(
            em.get("max_kayma_yuzde", rk.get("max_kayma_yuzde", 0.30))
        )
        self.max_exchange_timeouts = int(sg.get("borsa_timeout_esik", 3))
        self.failover_cooldown_sec = float(sg.get("failover_suresi_sn", 300.0))

        self.paper = PaperBroker(
            fee_taker_pct=em.get("komisyon_taker_yuzde", 0.05),
            fee_maker_pct=em.get("komisyon_maker_yuzde", 0.02),
            max_slippage_pct=self.max_slippage_pct,
        )
        self._ex = {}
        self._leverage_set: set[str] = set()

        import ccxt.async_support as ccxt

        default_type = "swap" if self.leverage > 1 else "spot"

        if "binance" in cfg["genel"].get("borsalar", []):
            b = ccxt.binance(
                {
                    "apiKey": api.get("binance_key", ""),
                    "secret": api.get("binance_secret", ""),
                    "enableRateLimit": True,
                    "options": {"defaultType": default_type},
                }
            )
            if self.mode == "testnet":
                b.set_sandbox_mode(True)
            self._ex["binance"] = b

        if "okx" in cfg["genel"].get("borsalar", []):
            o = ccxt.okx(
                {
                    "apiKey": api.get("okx_key", ""),
                    "secret": api.get("okx_secret", ""),
                    "password": api.get("okx_passphrase", ""),
                    "enableRateLimit": True,
                    "options": {"defaultType": default_type},
                }
            )
            if self.mode == "testnet":
                try:
                    o.set_sandbox_mode(True)
                except Exception:
                    pass
            self._ex["okx"] = o

        if not self._ex:
            raise ValueError(
                "En az bir borsa aktif olmalı (config.yaml → genel.borsalar)"
            )

        # Multi-Exchange Failover durum takibi
        self._default_primary: str = next(iter(self._ex))
        self._active_primary: str = self._default_primary
        self._ex_timeouts: dict[str, int] = {name: 0 for name in self._ex}
        self._ex_total_timeouts: dict[str, int] = {name: 0 for name in self._ex}
        self._ex_degraded_until: dict[str, float] = {name: 0.0 for name in self._ex}
        self.failover_count: int = 0
        self.failover_history: list[dict] = []

    @property
    def primary(self) -> str:
        """Aktif ana borsayı döner. Ana borsa kesintideyse otomatik yedek borsayı döner."""
        now = time.time()
        if (
            self._active_primary in self._ex
            and now >= self._ex_degraded_until.get(self._active_primary, 0.0)
        ):
            return self._active_primary
        for name in self._ex:
            if now >= self._ex_degraded_until.get(name, 0.0):
                self._active_primary = name
                return name
        return self._active_primary

    # -- A) Multi-Exchange Failover (Borsa Kesinti Sigortası) ------------------
    def is_exchange_healthy(self, exchange: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return now >= self._ex_degraded_until.get(exchange, 0.0)

    def record_exchange_success(self, exchange: str):
        """Borsadan başarılı yanıt alındığında ardışık timeout sayacını sıfırlar."""
        if exchange in self._ex_timeouts:
            self._ex_timeouts[exchange] = 0
            self._ex_degraded_until[exchange] = 0.0
            if exchange == self._default_primary:
                self._active_primary = self._default_primary

    def record_exchange_timeout(self, exchange: str, error: object = "") -> bool:
        """Borsa zaman aşımı / kesinti hatasını kaydeder.
        Ard arda 3 timeout olursa işlemleri otomatik yedek borsaya (örn. OKX) kaydırır!"""
        if exchange not in self._ex:
            return False
        self._ex_timeouts[exchange] = self._ex_timeouts.get(exchange, 0) + 1
        self._ex_total_timeouts[exchange] = self._ex_total_timeouts.get(exchange, 0) + 1

        if self._ex_timeouts[exchange] >= self.max_exchange_timeouts:
            now = time.time()
            self._ex_degraded_until[exchange] = now + self.failover_cooldown_sec
            # Yedek sağlıklı borsayı seç
            backup_ex = None
            for cand in self._ex:
                if cand != exchange and self.is_exchange_healthy(cand, now):
                    backup_ex = cand
                    break
            if backup_ex is None:
                # Diğer borsa da degraded ise en az hata alanı seç
                others = [c for c in self._ex if c != exchange]
                backup_ex = others[0] if others else exchange

            old_primary = self._active_primary
            self._active_primary = backup_ex
            self.failover_count += 1
            ev = {
                "ts": now,
                "failed_exchange": exchange,
                "new_primary": backup_ex,
                "timeouts": self._ex_timeouts[exchange],
                "error": safe_exception_msg(error) if isinstance(error, BaseException) else mask_secrets(error),
            }
            self.failover_history.append(ev)
            print(
                mask_secrets(
                    f"🔀 [MULTI-EXCHANGE FAILOVER] {exchange.upper()} borsasından ard arda "
                    f"{self._ex_timeouts[exchange]} timeout/kesinti alındı! "
                    f"İşlemler otomatik olarak {backup_ex.upper()} borsasına kaydırıldı "
                    f"(önceki: {old_primary.upper()} → yeni aktif: {backup_ex.upper()})."
                ),
                flush=True,
            )
            return True
        return False

    def choose_healthy_exchange(self, preferred: str | None = None) -> str:
        """Tercih edilen borsa sağlıklıysa onu, değilse yedek sağlıklı borsayı döner."""
        now = time.time()
        if preferred and preferred in self._ex and self.is_exchange_healthy(preferred, now):
            return preferred
        return self.primary

    def get_failover_order(self, preferred: str | None = None) -> list[str]:
        """Önce sağlıklı borsaları, en sonda kesintideki borsaları içeren deneme sırası."""
        now = time.time()
        first = self.choose_healthy_exchange(preferred)
        healthy = [first] + [
            n for n in self._ex if n != first and self.is_exchange_healthy(n, now)
        ]
        degraded = [n for n in self._ex if n not in healthy]
        return healthy + degraded

    def exchange_health_snapshot(self) -> dict:
        now = time.time()
        per_ex = {}
        for name in self._ex:
            healthy = self.is_exchange_healthy(name, now)
            rem = max(0.0, self._ex_degraded_until.get(name, 0.0) - now)
            per_ex[name] = {
                "healthy": healthy,
                "consecutive_timeouts": self._ex_timeouts.get(name, 0),
                "total_timeouts": self._ex_total_timeouts.get(name, 0),
                "degraded_remaining_sec": round(rem, 1),
            }
        return {
            "default_primary": self._default_primary,
            "active_primary": self.primary,
            "failover_active": self.primary != self._default_primary
            or any(not v["healthy"] for v in per_ex.values()),
            "failover_count": self.failover_count,
            "exchanges": per_ex,
            "last_failover": self.failover_history[-1] if self.failover_history else None,
        }

    async def ensure_leverage(
        self, symbol: str, leverage: int | None = None, exchange: str | None = None
    ):
        lev = int(leverage or self.leverage)
        if self.mode == "paper" or lev <= 1:
            return
        ex_name = self.choose_healthy_exchange(exchange)
        key = f"{ex_name}:{symbol}:{lev}"
        if key in self._leverage_set:
            return
        ex = self._ex.get(ex_name)
        if not ex:
            return
        try:
            await ex.set_leverage(lev, symbol)
            self._leverage_set.add(key)
        except Exception:
            pass

    # -- piyasa verisi (Failover destekli) -------------------------------------
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 300,
        exchange: str | None = None,
    ) -> list:
        last_err = None
        for ex_name in self.get_failover_order(exchange):
            ex = self._ex[ex_name]
            try:
                rows = await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
                self.record_exchange_success(ex_name)
                return rows
            except Exception as e:
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                continue
        raise last_err or RuntimeError("OHLCV alınamadı")

    async def fetch_price(
        self, symbol: str, exchange: str | None = None
    ) -> float:
        last_err = None
        for ex_name in self.get_failover_order(exchange):
            ex = self._ex[ex_name]
            try:
                t = await ex.fetch_ticker(symbol)
                self.record_exchange_success(ex_name)
                return float(t["last"])
            except Exception as e:
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                continue
        raise last_err or RuntimeError("Fiyat alınamadı")

    async def fetch_bid_ask(
        self, symbol: str, exchange: str | None = None
    ) -> tuple[float, float]:
        last_err = None
        for ex_name in self.get_failover_order(exchange):
            ex = self._ex[ex_name]
            try:
                t = await ex.fetch_ticker(symbol)
                self.record_exchange_success(ex_name)
                bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
                if not bid or not ask:
                    last = float(t["last"])
                    bid, ask = last, last
                return bid, ask
            except Exception as e:
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                continue
        raise last_err or RuntimeError("Bid/Ask alınamadı")

    async def fetch_all_quotes(self, symbol: str) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {}
        for name in self._ex:
            try:
                t = await self._ex[name].fetch_ticker(symbol)
                self.record_exchange_success(name)
                bid = float(t.get("bid") or t.get("last") or 0)
                ask = float(t.get("ask") or t.get("last") or 0)
                if bid > 0 and ask > 0:
                    out[name] = (bid, ask)
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                continue
        return out

    async def best_price(self, symbol: str, side: str) -> tuple[str, float]:
        """Sağlıklı borsalarda fiyata bak, avantajlı olanı seç."""
        quotes = {}
        for name in self.get_failover_order():
            if not self.is_exchange_healthy(name) and quotes:
                continue
            try:
                t = await self._ex[name].fetch_ticker(symbol)
                self.record_exchange_success(name)
                quotes[name] = float(t["last"])
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                pass
        if not quotes:
            raise RuntimeError("Fiyat alınamadı")
        if side == "LONG":
            name = min(quotes, key=quotes.get)
        else:
            name = max(quotes, key=quotes.get)
        return name, quotes[name]

    async def fetch_funding(self, symbol: str) -> float | None:
        swap = symbol if ":" in symbol else symbol + ":USDT"
        for name in self.get_failover_order():
            ex = self._ex[name]
            try:
                fr = await ex.fetch_funding_rate(swap)
                self.record_exchange_success(name)
                return float(fr.get("fundingRate") or 0)
            except Exception:
                continue
        return None

    async def fetch_open_interest(self, symbol: str) -> float | None:
        swap = symbol if ":" in symbol else symbol + ":USDT"
        for name in self.get_failover_order():
            ex = self._ex[name]
            try:
                oi = await ex.fetch_open_interest(swap)
                val = (
                    oi.get("openInterestValue")
                    or oi.get("openInterestAmount")
                    or oi.get("info", {}).get("openInterest")
                )
                if val is not None:
                    self.record_exchange_success(name)
                    return float(val)
            except Exception:
                continue
        return None

    async def fetch_balance_usdt(self) -> float:
        if self.mode == "paper":
            return self.paper.balance
        for name in self.get_failover_order():
            try:
                bal = await self._ex[name].fetch_balance()
                self.record_exchange_success(name)
                return float(bal["total"].get("USDT", 0))
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                continue
        return 0.0

    # -- emirler + Failover + Kayma (Slippage) Filtresi + Chase Order ----------
    async def market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        exchange: str | None = None,
    ) -> dict:
        target_ex = self.choose_healthy_exchange(exchange)
        if self.mode == "paper":
            px = price_hint or await self.fetch_price(symbol, target_ex)
            return self.paper.market_order(symbol, side, qty, px, exchange=target_ex)

        last_err = None
        for ex_name in self.get_failover_order(target_ex):
            await self.ensure_leverage(symbol, self.leverage, ex_name)
            ex = self._ex[ex_name]
            try:
                order = await ex.create_market_order(symbol, side, qty)
                self.record_exchange_success(ex_name)
                return {
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": float(order.get("average") or price_hint or 0),
                    "id": order.get("id"),
                    "mode": self.mode,
                    "exchange": ex_name,
                    "emir_tipi": "market",
                }
            except Exception as e:
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                    continue
                raise
        raise last_err or RuntimeError("Market emri gönderilemedi")

    async def _chase_limit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        expected_price: float,
        current_price: float,
        exchange: str | None = None,
        steps: int = 3,
    ) -> dict:
        ex_name = self.choose_healthy_exchange(exchange)
        if self.mode == "paper":
            return self.paper.chase_order(
                symbol,
                side,
                qty,
                expected_price,
                current_price,
                self.max_slippage_pct,
                exchange=ex_name,
            )

        ex = self._ex[ex_name]
        cap_px = (
            expected_price * (1.0 + self.max_slippage_pct / 100.0)
            if side == "buy"
            else expected_price * (1.0 - self.max_slippage_pct / 100.0)
        )
        rem = qty
        filled_tot = 0.0
        cost_tot = 0.0
        last_oid = None

        for _ in range(max(1, steps)):
            if rem <= qty * 0.001:
                break
            bid, ask = await self.fetch_bid_ask(symbol, ex_name)
            touch = ask if side == "buy" else bid
            limit_px = min(touch, cap_px) if side == "buy" else max(touch, cap_px)
            try:
                limit_px = float(ex.price_to_precision(symbol, limit_px))
            except Exception:
                pass
            o = await ex.create_limit_order(
                symbol, side, rem, limit_px, params={"postOnly": True}
            )
            last_oid = o.get("id")
            await asyncio.sleep(0.8)
            try:
                st = await ex.fetch_order(last_oid, symbol)
                f_step = float(st.get("filled") or 0.0)
                avg_step = float(st.get("average") or limit_px)
                if f_step > 0:
                    filled_tot += f_step
                    cost_tot += f_step * avg_step
                    rem = max(0.0, qty - filled_tot)
                if rem > 0:
                    await ex.cancel_order(last_oid, symbol)
            except Exception:
                break

        avg_px = (cost_tot / filled_tot) if filled_tot > 0 else cap_px
        return {
            "symbol": symbol,
            "side": side,
            "qty": filled_tot if filled_tot > 0 else qty,
            "price": avg_px,
            "id": last_oid,
            "mode": self.mode,
            "exchange": ex_name,
            "emir_tipi": "chase_limit",
        }

    async def execute_entry(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        order_type: str = "market",
        timeout: float = 3.0,
        exchange: str | None = None,
        expected_price: float | None = None,
        leverage: int | None = None,
    ) -> dict:
        """Pozisyon GİRİŞ emri (Failover + Maksimum Kayma Filtresi + Chase Order + Maker)."""
        ex_name = self.choose_healthy_exchange(exchange)
        if leverage is not None and leverage > 0:
            await self.ensure_leverage(symbol, leverage, ex_name)

        if expected_price and expected_price > 0 and price_hint > 0:
            slip_pct = abs(price_hint - expected_price) / expected_price * 100.0
            if slip_pct > self.max_slippage_pct:
                print(
                    mask_secrets(
                        f"⚠️ {symbol}: Anlık kayma %{slip_pct:.3f} > maks %{self.max_slippage_pct:.2f}! "
                        f"Market emri iptal edildi → Chase Order (Takip Eden Limit) devreye girdi."
                    ),
                    flush=True,
                )
                return await self._chase_limit_order(
                    symbol, side, qty, expected_price, price_hint, ex_name
                )

        if self.mode == "paper" or order_type != "maker":
            if self.mode == "paper" and order_type == "maker":
                px = price_hint or await self.fetch_price(symbol, ex_name)
                return self.paper.maker_order(
                    symbol, side, qty, px, exchange=ex_name
                )
            return await self.market_order(symbol, side, qty, price_hint, ex_name)

        await self.ensure_leverage(symbol, leverage or self.leverage, ex_name)
        ex = self._ex[ex_name]
        try:
            bid, ask = await self.fetch_bid_ask(symbol, ex_name)
            base = price_hint or (ask if side == "buy" else bid)
            ref_exp = expected_price or base
            slip_pct = abs(base - ref_exp) / max(ref_exp, 1e-12) * 100.0
            if slip_pct > self.max_slippage_pct:
                return await self._chase_limit_order(
                    symbol, side, qty, ref_exp, base, ex_name
                )

            tick = max(base * 0.0001, 1e-8)
            raw_px = (ask - tick) if side == "buy" else (bid + tick)
            try:
                limit_px = float(ex.price_to_precision(symbol, raw_px))
            except Exception:
                limit_px = raw_px
            order = await ex.create_limit_order(
                symbol, side, qty, limit_px, params={"postOnly": True}
            )
            self.record_exchange_success(ex_name)
            oid = order.get("id")
            filled, avg_px, t0 = 0.0, limit_px, time.time()
            while time.time() - t0 < timeout:
                await asyncio.sleep(0.4)
                try:
                    o = await ex.fetch_order(oid, symbol)
                except Exception:
                    break
                filled = float(o.get("filled") or 0)
                if o.get("average"):
                    avg_px = float(o["average"])
                if o.get("status") == "closed" or filled >= qty * 0.999:
                    filled = max(filled, qty)
                    break
            remainder = max(0.0, qty - filled)
            if remainder > 0:
                try:
                    await ex.cancel_order(oid, symbol)
                except Exception:
                    pass
                cur_bid, cur_ask = await self.fetch_bid_ask(symbol, ex_name)
                cur_px = cur_ask if side == "buy" else cur_bid
                rem_slip = abs(cur_px - ref_exp) / max(ref_exp, 1e-12) * 100.0
                if rem_slip > self.max_slippage_pct:
                    chase_res = await self._chase_limit_order(
                        symbol, side, remainder, ref_exp, cur_px, ex_name
                    )
                    mkt_px = chase_res.get("price") or cur_px
                    kind_lbl = "maker+chase-limit"
                else:
                    mkt = await self.market_order(
                        symbol, side, remainder, price_hint, ex_name
                    )
                    mkt_px = mkt.get("price") or base
                    kind_lbl = "maker+kalan-market"
                avg_px = (filled * avg_px + remainder * mkt_px) / qty
                return {
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": avg_px,
                    "id": oid,
                    "mode": self.mode,
                    "exchange": ex_name,
                    "emir_tipi": kind_lbl,
                    "maker_dolum": round(filled / qty * 100, 1),
                }
            return {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": avg_px,
                "id": oid,
                "mode": self.mode,
                "exchange": ex_name,
                "emir_tipi": "maker",
            }
        except Exception as e:
            if is_timeout_or_network_error(e):
                self.record_exchange_timeout(ex_name, e)
                ex_name = self.choose_healthy_exchange()
            print(
                f"⚠️ maker emir kurulamadı ({safe_exception_msg(e)}), {ex_name} market kullanılıyor.",
                flush=True,
            )
            return await self.market_order(symbol, side, qty, price_hint, ex_name)

    # -- borsa koruması (native stop / OCO) --------------------------------------
    async def place_protection(
        self,
        symbol: str,
        side: str,
        qty: float,
        sl_price: float,
        tp_price: float | None = None,
        exchange: str | None = None,
    ) -> dict:
        ex_name = self.choose_healthy_exchange(exchange)
        if self.mode == "paper":
            prot = {
                "native": True,
                "kind": "paper",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "sl": sl_price,
                "tp": tp_price,
                "exchange": ex_name,
            }
            self.paper.protections[symbol] = prot
            return prot

        ex = self._ex[ex_name]
        try:
            await ex.load_markets()
        except Exception:
            pass
        trig_side = "sell" if side == "LONG" else "buy"

        def _px(v: float) -> float:
            try:
                return float(ex.price_to_precision(symbol, v))
            except Exception:
                return v

        def _amt(v: float):
            try:
                return ex.amount_to_precision(symbol, v)
            except Exception:
                return v

        if (
            ex_name == "binance"
            and tp_price
            and ":" not in symbol
            and self.leverage <= 1
        ):
            try:
                fn = getattr(ex, "private_post_order_oco", None)
                if fn is not None:
                    coin = symbol.replace("/", "")
                    lim = _px(
                        sl_price * 0.999 if side == "LONG" else sl_price * 1.001
                    )
                    resp = await fn(
                        {
                            "symbol": coin,
                            "side": trig_side.upper(),
                            "quantity": _amt(qty),
                            "price": _px(tp_price),
                            "stopPrice": _px(sl_price),
                            "stopLimitPrice": lim,
                            "stopLimitTimeInForce": "GTC",
                        }
                    )
                    return {
                        "native": True,
                        "kind": "oco",
                        "orderListId": resp.get("orderListId"),
                        "sl": sl_price,
                        "tp": tp_price,
                        "exchange": ex_name,
                    }
            except Exception as e:
                print(
                    f"⚠️ OCO kurulamadı ({safe_exception_msg(e)}), stop-only deneniyor.",
                    flush=True,
                )

        if ":" in symbol or self.leverage > 1:
            try:
                sl_o = await ex.create_order(
                    symbol,
                    "STOP_MARKET",
                    trig_side,
                    qty,
                    None,
                    {"stopPrice": _px(sl_price), "reduceOnly": True},
                )
                ids = [sl_o.get("id")]
                if tp_price:
                    tp_o = await ex.create_order(
                        symbol,
                        "TAKE_PROFIT_MARKET",
                        trig_side,
                        qty,
                        None,
                        {"stopPrice": _px(tp_price), "reduceOnly": True},
                    )
                    ids.append(tp_o.get("id"))
                return {
                    "native": True,
                    "kind": "futures_pair",
                    "ids": ids,
                    "sl": sl_price,
                    "tp": tp_price,
                    "exchange": ex_name,
                }
            except Exception as e:
                print(
                    f"⚠️ vadeli koruma kurulamadı ({safe_exception_msg(e)}).",
                    flush=True,
                )

        attempts = []
        if ex_name == "binance":
            lim_px = _px(sl_price * 0.999 if side == "LONG" else sl_price * 1.001)
            attempts.append(
                ("STOP_LOSS_LIMIT", lim_px, {"stopPrice": _px(sl_price)})
            )
        if ex_name == "okx":
            attempts.append(
                ("market", None, {"stopLoss": {"triggerPrice": _px(sl_price)}})
            )
            attempts.append(
                ("limit", _px(sl_price), {"stopLoss": {"triggerPrice": _px(sl_price)}})
            )
        for typ, px, params in attempts:
            try:
                o = await ex.create_order(
                    symbol, typ, trig_side, _amt(qty), px, params
                )
                return {
                    "native": True,
                    "kind": "stop_only",
                    "ids": [o.get("id")],
                    "sl": sl_price,
                    "tp": None,
                    "exchange": ex_name,
                }
            except Exception:
                continue

        print(
            f"⚠️ {symbol}: borsa-native koruma kurulamadı, "
            f"bot-taraflı stop aktif (tek katman).",
            flush=True,
        )
        return {"native": False, "kind": "bot_only", "sl": sl_price}

    async def cancel_protection(
        self, symbol: str, prot: dict | None, exchange: str | None = None
    ) -> bool:
        if not prot:
            return True
        if self.mode == "paper" or prot.get("kind") == "paper":
            self.paper.protections.pop(symbol, None)
            return True
        if not prot.get("native"):
            return True
        ex = self._ex[exchange or prot.get("exchange") or self.primary]
        try:
            if prot.get("kind") == "oco" and prot.get("orderListId"):
                fn = getattr(ex, "private_delete_order_list", None)
                if fn is not None:
                    await fn(
                        {
                            "symbol": symbol.replace("/", ""),
                            "orderListId": prot["orderListId"],
                        }
                    )
                    return True
            for oid in prot.get("ids", []) or []:
                if oid:
                    try:
                        await ex.cancel_order(oid, symbol)
                    except Exception:
                        pass
            return True
        except Exception:
            return False

    async def replace_protection(
        self,
        symbol: str,
        side: str,
        qty: float,
        sl_price: float,
        old: dict | None,
        exchange: str | None = None,
    ) -> dict:
        try:
            await self.cancel_protection(symbol, old, exchange)
        except Exception:
            pass
        return await self.place_protection(
            symbol, side, qty, sl_price, None, exchange
        )

    async def close(self):
        for ex in self._ex.values():
            try:
                await ex.close()
            except Exception:
                pass
