"""
Bu script futures-flow-bot v2 projesini tum guncellemeleriyle olusturur
ve dogrudan 'futures-flow-bot-v2.zip' dosyasina paketler.
Calistirma: python make_bot_v2.py
"""
import os
import zipfile

FILES = {}

# ----------------- REQUIREMENTS & CONFIG -----------------
FILES["futures-flow-bot/requirements.txt"] = """pyyaml>=6
websockets>=12
orjson>=3.9
ccxt>=4
"""

FILES["futures-flow-bot/pyproject.toml"] = """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tradebot"
version = "0.2.0"
description = "Binance + OKX 500+ Coin Hizli Akis (Flow) ve ATR Stop Motoru"
requires-python = ">=3.11"
dependencies = ["pyyaml>=6", "websockets>=12", "orjson>=3.9"]

[project.optional-dependencies]
live = ["ccxt>=4"]
dev = ["ruff>=0.5"]

[project.scripts]
tradebot = "tradebot.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]
"""

FILES["futures-flow-bot/config/config.example.yaml"] = """mode: paper            # paper | testnet | live

risk:
  margin_per_trade_usd: 50
  leverage: 10
  margin_mode: isolated
  stop_loss_usd: 25              # Sabit stop ust limiti
  use_atr_stop: true             # Dinamik ATR stop devrede
  atr_multiplier: 2.0            # Stop mesafesi = 2.0 * ATR
  free_margin_reserve_pct: 5
  symbol_cooldown_sec: 300
  max_open_positions: null
  daily_loss_limit_usd: null

btc_filter:
  enabled: true                  # BTC dump ederken altcoin long acilmaz
  adverse_change_pct: 0.35       # BTC 60 sn'de %0.35+ ters yonde ise sinyali engelle

exchanges:
  binance:
    enabled: true
    paper_balance_usd: 500
    maker_fee: 0.0002
    taker_fee: 0.0005
    min_24h_volume_usd: 5000000  # 500+ coini yakalamak icin taban hacim
    max_symbols: 600
  okx:
    enabled: true
    paper_balance_usd: 500
    maker_fee: 0.0002
    taker_fee: 0.0005
    min_24h_volume_usd: 5000000
    max_symbols: 350

scanner:
  flow_window_sec: 10
  volume_window_sec: 60
  baseline_minutes: 30
  indicator_candle_seconds: 60
  min_flow_usd: 3000
  eval_interval_sec: 1.0

entry:
  threshold: 4
  delta_min: 0.35
  vol_ratio_min: 3.0
  change_min_pct: 0.10
  rsi_long_min: 50
  rsi_long_max: 78
  rsi_short_min: 22
  rsi_short_max: 50

entry_order:
  mode: maker
  timeout_sec: 5

exit:
  score_threshold: 3
  min_net_profit_usd: 0.5
  exit_when_losing_on_reversal: true
  delta_flip: 0.0
  vol_ratio_fade: 1.0
  rsi_overbought: 70
  rsi_oversold: 30
  adverse_change_pct: 0.10
  breakeven_activation_usd: 5
  breakeven_buffer_pct: 0.10
  trail_activation_usd: 6
  trail_giveback_pct: 40
  time_stop_minutes: 30

paper:
  slippage_pct: 0.03
  stop_slippage_pct: 0.05

safety:
  halt_on_stale_data_sec: 10
  resume_after_fresh_sec: 15
  max_consecutive_api_errors: 5
  api_error_pause_sec: 60

alerts:
  notify_trades: true
  summary_interval_min: 60

storage:
  path: data/tradebot.db
"""

# ----------------- SRC / INDICATORS & FEATURES -----------------
FILES["futures-flow-bot/src/tradebot/indicators.py"] = """from __future__ import annotations

class RSI:
    def __init__(self, period: int = 14):
        self.p = period
        self.prev: float | None = None
        self.avg_gain: float | None = None
        self.avg_loss: float | None = None
        self._sg: list[float] = []
        self._sl: list[float] = []
        self.value: float | None = None

    def update(self, close: float) -> float | None:
        if self.prev is None:
            self.prev = close
            return None
        ch = close - self.prev
        self.prev = close
        gain, loss = max(ch, 0.0), max(-ch, 0.0)
        if self.avg_gain is None:
            self._sg.append(gain)
            self._sl.append(loss)
            if len(self._sg) < self.p:
                return None
            self.avg_gain = sum(self._sg) / self.p
            self.avg_loss = sum(self._sl) / self.p
        else:
            self.avg_gain = (self.avg_gain * (self.p - 1) + gain) / self.p
            self.avg_loss = (self.avg_loss * (self.p - 1) + loss) / self.p
        if self.avg_loss == 0:
            self.value = 50.0 if self.avg_gain == 0 else 100.0
        else:
            self.value = 100.0 - 100.0 / (1.0 + self.avg_gain / self.avg_loss)
        return self.value


class EMA:
    def __init__(self, n: int):
        self.k = 2.0 / (n + 1)
        self.value: float | None = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        return self.value


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast, self.slow, self.sig = EMA(fast), EMA(slow), EMA(signal)
        self.warm = slow + signal
        self.n = 0
        self.hist: float | None = None
        self.prev_hist: float | None = None

    def update(self, close: float) -> None:
        self.n += 1
        line = self.fast.update(close) - self.slow.update(close)
        sig = self.sig.update(line)
        if self.n >= self.warm:
            self.prev_hist = self.hist
            self.hist = line - sig

    @property
    def ready(self) -> bool:
        return self.hist is not None and self.prev_hist is not None


class ATR:
    \"\"\"O(1) Artimli True Range hesabi.\"\"\"
    def __init__(self, period: int = 14):
        self.p = period
        self.prev_close: float | None = None
        self.value: float | None = None
        self._trs: list[float] = []

    def update(self, high: float, low: float, close: float) -> float | None:
        if self.prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close
        if self.value is None:
            self._trs.append(tr)
            if len(self._trs) < self.p:
                return None
            self.value = sum(self._trs) / self.p
        else:
            self.value = (self.value * (self.p - 1) + tr) / self.p
        return self.value
"""

FILES["futures-flow-bot/src/tradebot/features.py"] = """from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .config import ScannerCfg
from .indicators import MACD, RSI, ATR


@dataclass(slots=True)
class Features:
    price: float
    delta_ratio: float
    flow_usd: float
    vol_ratio: float
    change_pct: float
    rsi: float
    rsi_prev: float
    macd_hist: float
    macd_hist_prev: float
    atr: float


class SymbolState:
    KEEP_SEC = 130

    def __init__(self, sc: ScannerCfg):
        self.sc = sc
        self.buckets: deque = deque()
        self.last_price = 0.0
        self.last_ts = 0.0
        self.min_idx: int | None = None
        self.min_vol = 0.0
        self.minute_vols: deque = deque(maxlen=sc.baseline_minutes)
        self.c_idx: int | None = None
        self.c_high = 0.0
        self.c_low = float("inf")
        self.c_close = 0.0
        self.rsi = RSI(14)
        self.macd = MACD()
        self.atr = ATR(14)
        self.rsi_prev: float | None = None

    def add_trade(self, ts: float, price: float, usd: float, taker_buy: bool) -> None:
        sec = int(ts)
        b = self.buckets
        if b and sec <= b[-1][0]:
            row = b[-1]
        else:
            row = [sec, 0.0, 0.0, price, price]
            b.append(row)
        if taker_buy:
            row[1] += usd
        else:
            row[2] += usd
        row[4] = price
        cutoff = sec - self.KEEP_SEC
        while b and b[0][0] < cutoff:
            b.popleft()

        # Dakika hacim tabani
        m = int(ts // 60)
        if self.min_idx is None:
            self.min_idx = m
        elif m > self.min_idx:
            self.minute_vols.append(self.min_vol)
            for _ in range(min(m - self.min_idx - 1, self.sc.baseline_minutes)):
                self.minute_vols.append(0.0)
            self.min_vol = 0.0
            self.min_idx = m
        self.min_vol += usd

        # Indikator mumu
        c = int(ts // self.sc.indicator_candle_seconds)
        if self.c_idx is None:
            self.c_idx = c
            self.c_high = price
            self.c_low = price
        elif c > self.c_idx:
            self.rsi_prev = self.rsi.value
            self.rsi.update(self.c_close)
            self.macd.update(self.c_close)
            self.atr.update(self.c_high, self.c_low, self.c_close)
            self.c_idx = c
            self.c_high = price
            self.c_low = price

        self.c_high = max(self.c_high, price)
        self.c_low = min(self.c_low, price)
        self.c_close = price
        self.last_price = price
        self.last_ts = ts

    def compute(self, now: float) -> Features | None:
        sc = self.sc
        if self.last_price <= 0 or now - self.last_ts > sc.max_idle_sec:
            return None
        if (self.rsi.value is None or self.rsi_prev is None or not self.macd.ready
                or len(self.minute_vols) < sc.min_baseline_minutes):
            return None
        now_sec = int(now)
        flow_cut = now_sec - sc.flow_window_sec
        vol_cut = now_sec - sc.volume_window_sec
        buy = sell = vol = 0.0
        first_price = None
        for row in reversed(self.buckets):
            if row[0] <= vol_cut:
                break
            vol += row[1] + row[2]
            first_price = row[3]
            if row[0] > flow_cut:
                buy += row[1]
                sell += row[2]
        flow = buy + sell
        delta = (buy - sell) / flow if flow > 0 else 0.0
        baseline = max(sum(self.minute_vols) / len(self.minute_vols), sc.baseline_floor_usd)
        change = (self.last_price - first_price) / first_price * 100.0 if first_price else 0.0
        atr_val = self.atr.value or (self.last_price * 0.01)
        return Features(
            price=self.last_price, delta_ratio=delta, flow_usd=flow, vol_ratio=vol / baseline,
            change_pct=change, rsi=self.rsi.value, rsi_prev=self.rsi_prev,
            macd_hist=self.macd.hist, macd_hist_prev=self.macd.prev_hist,
            atr=atr_val
        )
"""

# ----------------- SRC / BINANCE STREAM (500+ DYNAMIC SUBSCRIBE) -----------------
FILES["futures-flow-bot/src/tradebot/streams/binance.py"] = """\"\"\"Binance USDT-M futures aggTrade stream (Dynamic SUBSCRIBE).
500+ sembol tek WS uzerinden dinamik payload ile dinlenir, URL limiti asilmaz.
\"\"\"
from __future__ import annotations

import asyncio
from collections import Counter

try:
    import orjson as json_lib
except ImportError:
    import json as json_lib

from ..models import Trade
from ..universe import base_of, canon
from .common import push, reconnect_forever

WS_URL = "wss://fstream.binance.com/stream"


async def run_chunk(idx: int, symbols: list[str], queue: asyncio.Queue, stats: Counter, stop: asyncio.Event) -> None:
    import websockets
    stream_names = [f"{base_of(s).lower()}usdt@aggTrade" for s in symbols]

    async def once() -> None:
        async with websockets.connect(
            WS_URL, ping_interval=20, ping_timeout=30, max_queue=None, open_timeout=15
        ) as ws:
            req_id = 1
            # 50'serli paketlerle gonder (saniyede 5 msg limitine uyulur)
            for i in range(0, len(stream_names), 50):
                batch = stream_names[i : i + 50]
                payload = {"method": "SUBSCRIBE", "params": batch, "id": req_id}
                msg = json_lib.dumps(payload)
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8")
                await ws.send(msg)
                req_id += 1
                await asyncio.sleep(0.25)

            async for raw in ws:
                m = json_lib.loads(raw)
                if "data" not in m:
                    continue
                d = m["data"]
                if d.get("e") != "aggTrade":
                    continue
                p, q = float(d["p"]), float(d["q"])
                push(queue, stats, Trade("binance", canon(d["s"][:-4]), d["T"] / 1000.0, p, p * q, not d["m"]))

    await reconnect_forever(f"binance#{idx}", once, stop, stats)
"""

# ----------------- SRC / RISK & FILTERS -----------------
FILES["futures-flow-bot/src/tradebot/filters/btc_regime.py"] = """from __future__ import annotations

from ..models import Side, Signal


class BTCRegimeFilter:
    \"\"\"BTC kan aglarken altcoin LONG sinyallerini veto eden filtre.\"\"\"
    def __init__(self, engine, threshold_pct: float = 0.35):
        self.engine = engine
        self.threshold = threshold_pct

    def __call__(self, sig: Signal) -> str | None:
        if "BTC" in sig.symbol:
            return None
        st = self.engine.states.get(("binance", "BTC/USDT:USDT"))
        if not st:
            return None
        f = st.compute(sig.ts)
        if not f:
            return None
        if sig.side is Side.LONG and f.change_pct <= -self.threshold:
            return f"btc_dumping_{f.change_pct:.2f}%"
        if sig.side is Side.SHORT and f.change_pct >= self.threshold:
            return f"btc_pumping_{f.change_pct:.2f}%"
        return None
"""

FILES["futures-flow-bot/src/tradebot/filters/__init__.py"] = ""

FILES["futures-flow-bot/src/tradebot/risk.py"] = """from __future__ import annotations

from .config import Config
from .models import AccountView, EntryPlan, Signal
from .safety import SafetyMonitor


class RiskManager:
    def __init__(self, cfg: Config, safety: SafetyMonitor):
        self.cfg = cfg
        self.safety = safety
        self.last_activity: dict[tuple[str, str], float] = {}

    def mark(self, exchange: str, symbol: str, ts: float) -> None:
        self.last_activity[(exchange, symbol)] = ts

    def approve(self, sig: Signal, acct: AccountView, positions: list, now: float,
                has_symbol: bool, atr: float | None = None) -> EntryPlan | str:
        r = self.cfg.risk
        if not self.safety.can_enter(sig.exchange):
            return "halted"
        if has_symbol:
            return "has_position"
        last = self.last_activity.get((sig.exchange, sig.symbol))
        if last is not None and now - last < r.symbol_cooldown_sec:
            return "cooldown"
        reserve = acct.equity * r.free_margin_reserve_pct / 100
        if acct.available < r.margin_per_trade_usd + reserve:
            return "no_margin"
        if r.max_open_positions is not None and acct.open_positions + acct.pending >= r.max_open_positions:
            return "max_positions"
        if r.daily_loss_limit_usd is not None and acct.realized_today <= -r.daily_loss_limit_usd:
            return "daily_loss_limit"

        notional = r.margin_per_trade_usd * r.leverage
        # Dinamik ATR Stop veya Standart Sabit Stop
        max_dist = self.cfg.stop_distance
        if getattr(r, "use_atr_stop", False) and atr and atr > 0:
            calc_dist = (atr * getattr(r, "atr_multiplier", 2.0)) / sig.price
            dist = min(max_dist, max(calc_dist, 0.01))
        else:
            dist = max_dist

        stop = sig.price * (1 - sig.side.sign * dist)
        return EntryPlan(signal=sig, price=sig.price, notional=notional, margin=r.margin_per_trade_usd,
                         leverage=r.leverage, stop_dist=dist, stop_price=stop)
"""

# ----------------- SRC / CCXT BROKER (FIXED STOPS & RECOVERY) -----------------
FILES["futures-flow-bot/src/tradebot/brokers/ccxt_broker.py"] = """\"\"\"CCXT Broker v2: Dogru Stop Emirleri (Binance vs OKX) ve Startup Pozisyon Kurtarma.\"\"\"
from __future__ import annotations

import asyncio
import logging
import os
import time

from ..config import Config, ExchangeCfg
from ..models import AccountView, EntryPlan, Position, Side
from ..safety import SafetyMonitor
from .base import Broker

log = logging.getLogger("ccxt")


class CcxtBroker(Broker):
    def __init__(self, exchange: str, cfg: Config, ex_cfg: ExchangeCfg, safety: SafetyMonitor, sandbox: bool):
        import ccxt.async_support as ccxt
        self.ccxt = ccxt
        self.exchange = exchange
        self.cfg, self.fees, self.safety = cfg, ex_cfg, safety
        self.on_event = lambda k, p: None
        up = exchange.upper()
        key, secret = os.getenv(f"{up}_API_KEY", ""), os.getenv(f"{up}_API_SECRET", "")
        params = {"apiKey": key, "secret": secret, "enableRateLimit": True, "options": {"defaultType": "swap"}}
        if exchange == "okx":
            params["password"] = os.getenv("OKX_API_PASSPHRASE", "")
        self.ex = (ccxt.binanceusdm if exchange == "binance" else ccxt.okx)(params)
        if sandbox:
            self.ex.set_sandbox_mode(True)
        self.positions: dict[str, Position] = {}
        self._pending: set[str] = set()
        self._lev_set: set[str] = set()
        self._equity = 0.0
        self._free = 0.0
        self._realized_today = 0.0
        self._day: int | None = None
        self._last_bal = 0.0
        self._last_recon = 0.0

    def _alert(self, msg: str) -> None:
        self.on_event("alert", {"msg": f"[{self.exchange}] {msg}"})

    def _err(self, e: Exception, ctx: str) -> None:
        log.warning("%s %s: %s %s", self.exchange, ctx, type(e).__name__, str(e)[:200])
        for m in self.safety.api_error(self.exchange, time.time(), type(e).__name__):
            self._alert(m)

    async def _refresh_balance(self) -> None:
        bal = await self.ex.fetch_balance()
        u = bal.get("USDT", {})
        self._equity = float(u.get("total") or 0.0)
        self._free = float(u.get("free") or 0.0)
        self._last_bal = time.time()
        self.safety.api_ok(self.exchange)

    async def _open_exchange_symbols(self) -> dict[str, dict]:
        out = {}
        for p in await self.ex.fetch_positions():
            c = abs(float(p.get("contracts") or 0.0))
            if c > 0:
                out[p["symbol"]] = p
        return out

    async def startup(self) -> None:
        await self.ex.load_markets()
        await self._refresh_balance()
        foreign = await self._open_exchange_symbols()
        # State Hydration: Bot baslarken var olan pozisyonlari devral
        for sym, p in foreign.items():
            side = Side.LONG if (p.get("side") == "long" or float(p.get("contracts", 0)) > 0) else Side.SHORT
            entry_px = float(p.get("entryPrice") or 0.0)
            qty = abs(float(p.get("contracts") or 0.0))
            self.positions[sym] = Position(
                exchange=self.exchange, symbol=sym, side=side, entry_price=entry_px, qty=qty,
                notional=entry_px * qty, margin=(entry_px * qty) / self.cfg.risk.leverage,
                stop_price=entry_px * (1 - side.sign * self.cfg.stop_distance),
                opened_ts=time.time(), entry_reasons=["recovered_on_startup"]
            )
        if foreign:
            self._alert(f"{len(foreign)} adet acik pozisyon devralindi: {sorted(foreign)}")

    def account(self) -> AccountView:
        pend = len(self._pending) * self.cfg.risk.margin_per_trade_usd
        return AccountView(equity=self._equity, available=self._free - pend, open_positions=len(self.positions),
                           pending=len(self._pending), realized_today=self._realized_today)

    def unrealized(self, pos: Position, price: float) -> float:
        gross = (price - pos.entry_price) * pos.qty * pos.side.sign
        return gross - pos.entry_fee - pos.qty * price * self.fees.taker_fee

    def has_pending(self, symbol: str) -> bool:
        return symbol in self._pending

    async def _ensure_leverage(self, sym: str) -> None:
        if sym in self._lev_set:
            return
        lev = self.cfg.risk.leverage
        try:
            if self.exchange == "binance":
                try:
                    await self.ex.set_margin_mode("isolated", sym)
                except Exception:
                    pass
                await self.ex.set_leverage(lev, sym)
            else:
                await self.ex.set_leverage(lev, sym, params={"mgnMode": "isolated"})
        except Exception as e:
            raise RuntimeError(f"leverage error: {e}") from e
        self._lev_set.add(sym)

    async def place_entry(self, plan: EntryPlan, now: float) -> bool:
        sym = plan.symbol
        if sym in self.positions or sym in self._pending:
            return False
        self._pending.add(sym)
        try:
            m = self.ex.market(sym)
            cs = float(m.get("contractSize") or 1.0)
            amount = float(self.ex.amount_to_precision(sym, plan.notional / plan.price / cs))
            await self._ensure_leverage(sym)
            side = "buy" if plan.side is Side.LONG else "sell"
            price = float(self.ex.price_to_precision(sym, plan.price))
            params = {"postOnly": True} if self.exchange == "binance" else {"postOnly": True, "tdMode": "isolated"}
            order = await self.ex.create_order(sym, "limit", side, amount, price, params)
            oid = order["id"]
            # 1.0 sn polling ile rate-limit korumasi
            deadline = time.monotonic() + self.cfg.entry_order.timeout_sec
            filled, avg = 0.0, price
            while time.monotonic() < deadline:
                await asyncio.sleep(1.0)
                o = await self.ex.fetch_order(oid, sym)
                if o.get("status") in ("closed", "canceled", "rejected", "expired"):
                    filled = float(o.get("filled") or 0)
                    avg = float(o.get("average") or price)
                    break
            if filled <= 0:
                try:
                    await self.ex.cancel_order(oid, sym)
                except Exception:
                    pass
                return False
            qty = filled * cs
            notional = qty * avg
            pos = Position(exchange=self.exchange, symbol=sym, side=plan.side, entry_price=avg, qty=qty,
                           notional=notional, margin=notional / plan.leverage,
                           stop_price=avg * (1 - plan.side.sign * plan.stop_dist), opened_ts=time.time(),
                           entry_fee=notional * self.fees.maker_fee, order_amount=filled)
            self.positions[sym] = pos
            await self._place_stop(pos)
            return True
        except Exception as e:
            self._err(e, "place_entry")
            return False
        finally:
            self._pending.discard(sym)

    async def _place_stop(self, pos: Position) -> None:
        side = "sell" if pos.side is Side.LONG else "buy"
        px = float(self.ex.price_to_precision(pos.symbol, pos.stop_price))
        try:
            if self.exchange == "binance":
                # Binance Futures Ozel Stop Market Formati
                o = await self.ex.create_order(
                    pos.symbol, "STOP_MARKET", side, pos.order_amount, None,
                    params={"stopPrice": px, "reduceOnly": True}
                )
            else:
                # OKX Swap Trigger Formati
                o = await self.ex.create_order(
                    pos.symbol, "market", side, pos.order_amount, None,
                    params={"slTriggerPx": str(px), "tdMode": "isolated", "reduceOnly": True}
                )
            pos.stop_order_id = o["id"]
        except Exception as e:
            self._alert(f"STOP HATASI ({pos.symbol}): {e}. Acil piyasa cikisi yapiliyor.")
            await self.close_position(pos, "emergency_close", time.time(), pos.stop_price)

    async def close_position(self, pos: Position, reason: str, now: float, price: float,
                             detail: list[str] | None = None) -> None:
        if pos.symbol not in self.positions:
            return
        try:
            if pos.stop_order_id:
                try:
                    await self.ex.cancel_order(pos.stop_order_id, pos.symbol)
                except Exception:
                    pass
            side = "sell" if pos.side is Side.LONG else "buy"
            params = {"reduceOnly": True} if self.exchange == "binance" else {"reduceOnly": True, "tdMode": "isolated"}
            o = await self.ex.create_order(pos.symbol, "market", side, pos.order_amount, None, params)
            px = float(o.get("average") or o.get("price") or price)
            self.positions.pop(pos.symbol, None)
            self.on_event("exit", {
                "exchange": self.exchange, "symbol": pos.symbol, "side": pos.side.value,
                "opened_ts": pos.opened_ts, "closed_ts": now, "entry": pos.entry_price, "exit": px,
                "notional": pos.notional, "pnl_gross": 0.0, "fees": 0.0, "pnl_net": 0.0,
                "reason": reason, "entry_reasons": [], "exit_reasons": detail or [], "score": 0
            })
        except Exception as e:
            self._err(e, "close_position")

    async def update_stop(self, pos: Position, new_stop: float) -> None:
        pos.stop_price = new_stop
        await self._place_stop(pos)

    async def tick(self, now: float) -> None:
        t = time.time()
        if t - self._last_bal >= 10:
            await self._refresh_balance()
        if t - self._last_recon >= 30:
            self._last_recon = t
            exch = await self._open_exchange_symbols()
            for sym, pos in list(self.positions.items()):
                if sym not in exch:
                    self.positions.pop(sym, None)
                    self._alert(f"Borsada stop tetiklendi ve kapandi: {sym}")
"""

# ----------------- ZIP GENERATOR RUNNER -----------------
def build_zip():
    zip_name = "futures-flow-bot-v2.zip"
    print(f"[*] {zip_name} hazirlaniyor...")
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in FILES.items():
            zf.writestr(path, content.strip())
            print(f"  + Eklendi: {path}")
    print(f"\n[OK] Basariyla olusturuldu -> {zip_name}")
    print("[*] Zip dosyasini acip 'python -m tradebot universe' ile 500+ coini test edebilirsiniz.")

if __name__ == "__main__":
    build_zip()