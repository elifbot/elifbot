"""Live market-data and optional execution pipeline for Binance/OKX Futures (ACARBOT V22).

Modes (decided by CLI flags, never by accident):
    default   READ_ONLY  - market data + scoring only, nothing is simulated or sent
    --paper   PAPER      - signals go through SIZING -> RISK -> CORRELATION -> PAPER ACCEPT/REJECT
    --live    LIVE       - real orders; requires PHOENIX_CONFIRM_LIVE=YES and credentials
"""
from __future__ import annotations
import argparse, json, logging, os, time
from collections import defaultdict, deque
from dataclasses import dataclass
try:
    import ccxt
except ImportError:
    ccxt = None
from .config import Config
from .models import Market, Snapshot
from .strategy import Strategy
from .trading import TradingService
from .utils_retry import RetryPolicy, with_retry, is_ban, parse_ban_until, ExchangeBanned
from .telemetry import Telemetry, VERSION
from .paper import PaperBroker
from .binance_route import apply_binance_www_route, restrict_to_linear

log = logging.getLogger("phoenix.live")


@dataclass
class LiveConfig:
    duration_sec: int = 300
    poll_sec: int = 15
    detail_symbols_per_exchange: int = 100     # 0 = every eligible market (WAF-ban risk on Binance)
    rotation_slots: int = 25                   # extra symbols/exchange/cycle, rotated through the tail
    max_cycles: int = 0                        # 0 = unlimited (bounded by duration)
    max_cycle_sec: int = 180                     # 0 = unlimited; >0 truncates a cycle's detail loop
    include_dated_futures: bool = True
    exchange_timeout_ms: int = 10000
    orderbook_limit: int = 20
    liquidation_limit: int = 50
    max_market_age_sec: float = 20.0
    htf_cache_sec: int = 600
    funding_cache_sec: int = 300
    live_trading: bool = False
    paper_trading: bool = False
    paper_equity: float = 1000.0
    paper_resume: bool = False
    reconcile_sec: int = 15
    report_path: str = "live_test_report.json"
    score_log_path: str = ""
    checkpoint_every: int = 25

    @property
    def mode(self) -> str:
        return "LIVE" if self.live_trading else ("PAPER" if self.paper_trading else "READ_ONLY")

    @classmethod
    def from_env(cls):
        def i(name, default):
            raw = os.getenv(name); return default if raw in (None, "") else int(raw)
        def f(name, default):
            raw = os.getenv(name); return default if raw in (None, "") else float(raw)
        def b(name, default=False):
            raw = os.getenv(name); return default if raw in (None, "") else raw.strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            duration_sec=i("PHOENIX_LIVE_DURATION_SEC", 300), poll_sec=i("PHOENIX_LIVE_POLL_SEC", 15),
            detail_symbols_per_exchange=i("PHOENIX_LIVE_DETAIL_PER_CYCLE", 100), rotation_slots=i("PHOENIX_ROTATION_SLOTS", 25),
            max_cycles=i("PHOENIX_MAX_CYCLES", 0), max_cycle_sec=i("PHOENIX_MAX_CYCLE_SEC", 180),
            include_dated_futures=b("PHOENIX_INCLUDE_DATED_FUTURES", True),
            exchange_timeout_ms=i("PHOENIX_EXCHANGE_TIMEOUT_MS", 10000),
            orderbook_limit=i("PHOENIX_ORDERBOOK_LIMIT", 20), liquidation_limit=i("PHOENIX_LIQUIDATION_LIMIT", 50),
            max_market_age_sec=f("PHOENIX_MAX_MARKET_AGE_SEC", 20), htf_cache_sec=i("PHOENIX_HTF_CACHE_SEC", 600),
            funding_cache_sec=i("PHOENIX_FUNDING_CACHE_SEC", 300), live_trading=False,
            paper_trading=b("PHOENIX_PAPER_TRADING", False), paper_equity=f("PHOENIX_PAPER_EQUITY", 1000),
            reconcile_sec=i("PHOENIX_RECONCILE_SEC", 15), report_path=os.getenv("PHOENIX_LIVE_REPORT_PATH", "live_test_report.json"),
            score_log_path=os.getenv("PHOENIX_SCORE_LOG", ""), checkpoint_every=i("PHOENIX_CHECKPOINT_EVERY", 25),
        )


class CCXTAdapter:
    def __init__(self, exchange_id, timeout_ms=10000, api_key=None, secret=None, password=None, sandbox=False):
        if ccxt is None:
            raise RuntimeError("ccxt is required")
        klass = getattr(ccxt, exchange_id)
        cfg = {"enableRateLimit": True, "timeout": timeout_ms}
        if api_key:
            cfg["apiKey"] = api_key
        if secret:
            cfg["secret"] = secret
        if password:
            cfg["password"] = password
        self.exchange_id = exchange_id.upper()
        self.client = klass(cfg)
        self.banned_until = 0.0
        self.ban_message = ""
        self._leverage_done = set()
        self._markets = None
        self.sandbox = bool(sandbox)
        # Set sandbox first. Public WWW routing is only for production public data;
        # applying it after set_sandbox_mode would silently overwrite testnet URLs.
        if self.sandbox:
            self.client.set_sandbox_mode(True)
        self.www_mode = os.getenv("PHOENIX_BINANCE_PUBLIC_WWW", os.getenv("BINANCE_PUBLIC_WWW", "auto")).strip().lower()
        if self.exchange_id == "BINANCE":
            restrict_to_linear(self.client)
            if not self.sandbox and self.www_mode == "1":
                self._enable_www()
        self.retry_policy = RetryPolicy(attempts=4, base_delay=0.5, max_delay=8.0)

    def _enable_www(self):
        try:
            changed = apply_binance_www_route(self.client, force=True)
            if changed:
                log.info("BINANCE public WWW route enabled: %s", changed)
            return bool(changed)
        except Exception as exc:
            log.warning("BINANCE WWW route could not be applied: %s", exc)
            return False

    # ---- ban handling -----------------------------------------------------------
    def banned(self) -> bool:
        return time.time() < self.banned_until

    def ban_remaining(self) -> float:
        return max(0.0, self.banned_until - time.time())

    def _register_ban(self, exc):
        until = parse_ban_until(exc) or (time.time() + 600)      # unknown expiry: back off 10 min
        self.banned_until = max(self.banned_until, until + 5)
        self.ban_message = str(exc)[:300]
        log.error("%s BAN detected, pausing this exchange for %.0f s: %s", self.exchange_id, self.ban_remaining(), self.ban_message)

    def _check_ban(self):
        if self.banned():
            raise ExchangeBanned(f"{self.exchange_id} banned for another {self.ban_remaining():.0f}s", self.banned_until)

    def _call(self, fn, *args, **kwargs):
        self._check_ban()
        try:
            return with_retry(lambda: fn(*args, **kwargs), self.retry_policy)
        except Exception as exc:
            if is_ban(exc) and not isinstance(exc, ExchangeBanned):
                self._register_ban(exc)
            raise

    def _call_once(self, fn, *args, **kwargs):
        """No retry: used for order creation (a retried timeout could double-submit)."""
        self._check_ban()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if is_ban(exc) and not isinstance(exc, ExchangeBanned):
                self._register_ban(exc)
            raise

    # ---- symbols / precision ------------------------------------------------------
    def unify_symbol(self, symbol):
        return str(symbol).strip().upper()

    def exchange_symbol(self, symbol):
        key = self.unify_symbol(symbol)
        if self._markets:
            for ccxt_symbol in self._markets:
                if self.unify_symbol(ccxt_symbol) == key:
                    return ccxt_symbol
        return symbol

    def _step(self, value):
        """Convert ccxt precision to a step size (ccxt precisionMode: 2=DECIMAL_PLACES, 3=SIGNIFICANT_DIGITS, 4=TICK_SIZE)."""
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            return 0.0
        if v <= 0:
            return 0.0
        mode = getattr(self.client, "precisionMode", 4)
        if mode == 2:
            return 10.0 ** (-int(v))
        if mode == 3:
            return 0.0
        return v

    def load_markets(self):
        try:
            self._markets = self._call(self.client.load_markets)
        except Exception as exc:
            msg = str(exc)
            if self.exchange_id == "BINANCE" and not self.sandbox and self.www_mode == "auto" and ("451" in msg or "restricted location" in msg.lower()):
                log.warning("BINANCE returned 451; switching public routes to the WWW host and retrying once")
                if self._enable_www():
                    self._markets = self._call(self.client.load_markets, True)
                else:
                    raise
            else:
                raise
        out = []
        for s, m in self._markets.items():
            if m.get("active") is False or not (m.get("swap") or m.get("future")) or m.get("quote") != "USDT" or m.get("settle") != "USDT":
                continue
            prec = m.get("precision") or {}
            limits = m.get("limits") or {}
            amt = limits.get("amount") or {}
            cost = limits.get("cost") or {}
            out.append(Market(self.exchange_id, s, m.get("base", ""), "USDT", "USDT", "swap" if m.get("swap") else "future",
                              float(m.get("contractSize") or 1), True, self._step(prec.get("price")), self._step(prec.get("amount")),
                              float(amt.get("min") or 0), float(cost.get("min") or 0), dict(m.get("info") or {})))
        return out

    def market(self, symbol):
        if self._markets is None:
            self.load_markets()
        return self._markets[symbol]

    def market_info(self, symbol):
        return dict(self.market(symbol).get("info") or {})

    def price_tick(self, symbol):
        try:
            return self._step((self.market(symbol).get("precision") or {}).get("price"))
        except Exception:
            return 0.0

    def market_meta(self, symbol):
        m = self.market(symbol)
        prec = m.get("precision") or {}
        limits = m.get("limits") or {}
        return {"min_amount": float((limits.get("amount") or {}).get("min") or 0),
                "min_cost": float((limits.get("cost") or {}).get("min") or 0),
                "amount_step": self._step(prec.get("amount")), "price_tick": self._step(prec.get("price")),
                "contract_size": float(m.get("contractSize") or 1.0)}

    def ensure_leverage(self, symbol, leverage, td_mode="cross"):
        """Enforce cross margin and requested leverage before any entry order.

        Fail closed: only the venue's explicit 'already cross' response is benign.
        Other mode/leverage errors must prevent the order from being submitted.
        """
        if td_mode != "cross":
            raise RuntimeError("cross margin is mandatory; isolated mode is disabled")
        key = (symbol, int(leverage))
        if key in self._leverage_done:
            return
        if self.exchange_id == "OKX":
            self._call_once(self.client.set_leverage, int(leverage), symbol, {"mgnMode": "cross"})
        else:
            try:
                self._call_once(self.client.set_margin_mode, "cross", symbol)
            except Exception as exc:
                msg = str(exc).lower()
                code = str(getattr(exc, "code", ""))
                already_cross = code == "-4046" or "no need to change margin type" in msg
                if not already_cross:
                    raise RuntimeError(f"could not confirm cross margin for {symbol}: {exc}") from exc
            self._call_once(self.client.set_leverage, int(leverage), symbol)
        self._leverage_done.add(key)

    # ---- market data --------------------------------------------------------------
    def tickers(self, symbols):
        if self.client.has.get("fetchTickers"):
            return self._call(self.client.fetch_tickers, symbols)
        return {s: self._call(self.client.fetch_ticker, s) for s in symbols}

    def bids_asks(self, symbols):
        """Binance 24hr tickers carry no bid/ask; /fapi/v1/ticker/bookTicker does (fetch_bids_asks)."""
        if not self.client.has.get("fetchBidsAsks"):
            return {}
        return self._call(self.client.fetch_bids_asks, symbols)

    def ticker(self, symbol): return self._call(self.client.fetch_ticker, symbol)
    def order_book(self, symbol, limit=20): return self._call(self.client.fetch_order_book, symbol, limit)
    def ohlcv(self, symbol, tf, limit=100): return self._call(self.client.fetch_ohlcv, symbol, tf, limit=limit)

    def funding(self, symbol):
        try:
            if self.client.has.get("fetchFundingRate"):
                r = self._call(self.client.fetch_funding_rate, self.exchange_symbol(symbol))
                v = r.get("fundingRate")
                if v is not None: return float(v)
        except ExchangeBanned:
            raise
        except Exception as exc:
            if is_ban(exc): raise
        # REST fallback for exchanges where CCXT capability metadata is incomplete.
        try:
            if self.exchange_id == "BINANCE" and hasattr(self.client, "fapiPublicGetFundingRate"):
                rows = self._call(self.client.fapiPublicGetFundingRate, {"symbol": self.client.market(self.exchange_symbol(symbol))["id"], "limit": 1})
                if rows: return float(rows[-1].get("fundingRate"))
            if self.exchange_id == "OKX" and hasattr(self.client, "publicGetPublicFundingRate"):
                inst = self.client.market(self.exchange_symbol(symbol))["id"]
                rows = self._call(self.client.publicGetPublicFundingRate, {"instId": inst})
                data = (rows.get("data") if isinstance(rows, dict) else rows) or []
                if data: return float(data[0].get("fundingRate"))
        except ExchangeBanned:
            raise
        except Exception as exc:
            if is_ban(exc): raise
            return None
        return None

    def oi(self, symbol):
        try:
            if self.client.has.get("fetchOpenInterest"):
                r = self._call(self.client.fetch_open_interest, self.exchange_symbol(symbol))
                v = r.get("openInterestAmount")
                if v is None: v = r.get("openInterestValue")
                if v is not None: return float(v)
        except ExchangeBanned:
            raise
        except Exception as exc:
            if is_ban(exc): raise
        try:
            if self.exchange_id == "BINANCE" and hasattr(self.client, "fapiPublicGetOpenInterest"):
                row = self._call(self.client.fapiPublicGetOpenInterest, {"symbol": self.client.market(self.exchange_symbol(symbol))["id"]})
                if row.get("openInterest") is not None: return float(row["openInterest"])
            if self.exchange_id == "OKX" and hasattr(self.client, "publicGetPublicOpenInterest"):
                inst = self.client.market(self.exchange_symbol(symbol))["id"]
                rows = self._call(self.client.publicGetPublicOpenInterest, {"instType": "SWAP", "instId": inst})
                data = (rows.get("data") if isinstance(rows, dict) else rows) or []
                if data:
                    for k in ("oi", "oiCcy", "oiUsd"):
                        if data[0].get(k) is not None: return float(data[0][k])
        except ExchangeBanned:
            raise
        except Exception as exc:
            if is_ban(exc): raise
            return None
        return None

    def liquidations(self, symbol, limit=50):
        if not self.client.has.get("fetchLiquidations"):
            return []
        try:
            return self._call(self.client.fetch_liquidations, symbol, limit=limit) or []
        except ExchangeBanned:
            raise
        except Exception as exc:
            if is_ban(exc): raise
            return []

    # ---- account --------------------------------------------------------------------
    def fetch_balance(self): return self._call(self.client.fetch_balance, {"type": "swap"})
    def fetch_positions(self): return self._call(self.client.fetch_positions)
    def fetch_open_orders(self, symbol=None): return self._call(self.client.fetch_open_orders, symbol)
    def fetch_my_trades(self, since=None, limit=1000):
        return self._call(self.client.fetch_my_trades, None, since, limit)

    def fetch_my_trades_paginated(self, since=None, until=None, max_records=5000, page_limit=1000):
        """Fetch realized-trade history in bounded pages; deduplicate by exchange id/timestamp."""
        if max_records <= 0:
            return []
        out, seen = [], set()
        cursor = since
        while len(out) < max_records:
            request_limit = min(page_limit, max_records - len(out))
            page = self.fetch_my_trades(since=cursor, limit=request_limit) or []
            if not page:
                break
            page_new = 0
            newest_ts = cursor or 0
            for row in page:
                info = row.get("info") or {}
                rid = row.get("id") or info.get("id")
                ts = row.get("timestamp") or info.get("time") or info.get("ts")
                key = (str(rid), ts) if rid is not None else (str(row.get("symbol")), ts, row.get("price"), row.get("amount"), row.get("side"))
                if key in seen:
                    continue
                if until is not None and ts is not None and int(ts) > int(until):
                    continue
                seen.add(key); out.append(row); page_new += 1
                if ts is not None:
                    newest_ts = max(newest_ts, int(ts))
                if len(out) >= max_records:
                    break
            if page_new == 0:
                break
            if newest_ts and newest_ts >= (cursor or 0):
                cursor = newest_ts + 1
            else:
                break
            if len(page) < request_limit:
                break
        return out

    def amount_to_precision(self, s, a): return float(self.client.amount_to_precision(s, a))
    def price_to_precision(self, s, p): return float(self.client.price_to_precision(s, p))
    def create_order(self, *a, **kw): return self._call_once(self.client.create_order, *a, **kw)
    def cancel_order(self, oid, s): return self._call(self.client.cancel_order, oid, s)
    def fetch_order(self, oid, s): return self._call(self.client.fetch_order, oid, s)


class LiveSignalRunner:
    def __init__(self, cfg=None, live_cfg=None, adapters=None, clock=time.time):
        self.cfg = cfg or Config.from_env()
        self.lcfg = live_cfg or LiveConfig.from_env()
        self.clock = clock
        if self.lcfg.live_trading and self.lcfg.paper_trading:
            raise RuntimeError("--live and --paper are mutually exclusive")
        self.strategy = Strategy(self.cfg)
        self.adapters = adapters or self._make_adapters()
        self._validate_live_credentials()
        self.tm = Telemetry(extra_thresholds=(self.cfg.min_score,))
        self.markets = []
        self.last_oi = {}
        self.oi_history = defaultdict(deque)
        self.returns_history = {}
        self.price_history = {}
        self._cache = {}
        self._rot = {}
        self._last_last = {}          # (exchange, symbol) -> last price from the latest ticker batch
        self.last_refresh = 0
        self.trading = {}
        self._live_order_ids = set()
        self.paper = None
        self._paper_marks_cache = {}
        if self.lcfg.live_trading:
            self.trading = {ex: TradingService(ad, self.cfg, self.cfg.state_path.replace(".json", f".{ex.lower()}.json")) for ex, ad in self.adapters.items()}
        elif self.lcfg.paper_trading:
            self.paper = PaperBroker(self.cfg, equity=self.lcfg.paper_equity, state_path=self.cfg.paper_state_path,
                                     journal_path=self.cfg.paper_journal_path, resume=self.lcfg.paper_resume, clock=self.clock)

    def _make_adapters(self):
        """Create adapters for the comma-separated CCXT exchange list."""
        ids = [x.strip().lower() for x in os.getenv("PHOENIX_EXCHANGES", "binance,okx").split(",") if x.strip()]
        adapters = {}
        for exchange_id in dict.fromkeys(ids):
            prefix = exchange_id.upper()
            adapters[prefix] = CCXTAdapter(
                exchange_id, self.lcfg.exchange_timeout_ms,
                os.getenv(f"PHOENIX_{prefix}_API_KEY"),
                os.getenv(f"PHOENIX_{prefix}_API_SECRET"),
                os.getenv(f"PHOENIX_{prefix}_PASSPHRASE") if exchange_id == "okx" else None,
                sandbox=os.getenv(f"PHOENIX_{prefix}_SANDBOX", "0") == "1",
            )
        if not adapters:
            raise RuntimeError("PHOENIX_EXCHANGES must list at least one CCXT exchange id")
        return adapters

    def _validate_live_credentials(self):
        if not self.lcfg.live_trading:
            return
        if os.getenv("PHOENIX_CONFIRM_LIVE", "").strip().upper() != "YES":
            raise RuntimeError("Live trading requested but PHOENIX_CONFIRM_LIVE=YES is not set (real orders stay disabled by default)")
        if len(self.adapters) > 1:
            raise RuntimeError("Multi-exchange LIVE is intentionally locked: global cross-venue equity/margin coordination must be enabled first. Multi-exchange READ_ONLY/PAPER is supported.")
        missing = []
        for ex in self.adapters:
            if not os.getenv(f"PHOENIX_{ex}_API_KEY") or not os.getenv(f"PHOENIX_{ex}_API_SECRET"):
                missing.append(f"{ex}_API_KEY/SECRET")
            if ex == "OKX" and not os.getenv("PHOENIX_OKX_PASSPHRASE"):
                missing.append("OKX_PASSPHRASE")
        if missing:
            raise RuntimeError("Live trading requested but credentials are missing: " + ", ".join(missing))

    # ---- indicators -------------------------------------------------------------------
    @staticmethod
    def _trend(bars):
        rows = [x for x in bars if len(x) >= 6 and float(x[4]) > 0]
        if len(rows) < 21:
            return None
        c = [float(x[4]) for x in rows]
        fast, slow = sum(c[-8:]) / 8, sum(c[-20:]) / 20
        tr = [max(float(rows[i][2]) - float(rows[i][3]), abs(float(rows[i][2]) - float(rows[i - 1][4])), abs(float(rows[i][3]) - float(rows[i - 1][4]))) for i in range(1, len(rows))]
        atr = sum(tr[-14:]) / 14 if len(tr) >= 14 else 0
        atr_pct = atr / c[-1] if c[-1] else 0
        raw = (fast / slow - 1) / (max(atr_pct, 1e-6) * 2.0)
        return max(-1, min(1, raw))

    @staticmethod
    def _atr_pct(bars, period=14):
        rows = [x for x in bars if len(x) >= 6 and float(x[4]) > 0]
        if len(rows) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(rows)):
            high, low, prev = float(rows[i][2]), float(rows[i][3]), float(rows[i-1][4])
            trs.append(max(high-low, abs(high-prev), abs(low-prev)))
        atr = sum(trs[-period:]) / period
        close = float(rows[-1][4])
        return atr / close if close > 0 else 0.0

    @staticmethod
    def _book_imbalance(book):
        b, a = book.get("bids") or [], book.get("asks") or []
        if not b or not a:
            return None
        def pq(row):
            return (float(row[0]), float(row[1])) if len(row) >= 2 else None
        bids = [x for x in (pq(r) for r in b[:20]) if x]
        asks = [x for x in (pq(r) for r in a[:20]) if x]
        if not bids or not asks:
            return None
        bv, av = sum(p * q for p, q in bids), sum(p * q for p, q in asks)
        return max(-1, min(1, (bv - av) / (bv + av))) if bv + av else None

    @staticmethod
    def _quote_volume_info(t, market=None):
        """Return verified USD quote volume and provenance.

        OKX derivative ``vol24h`` is a contract count, not base-asset units.
        Convert contracts using the instrument's ctVal/ctMult before applying price.
        If contract metadata is missing, fail closed rather than admitting a market
        on a potentially 100x-inflated volume.
        """
        info = t.get("info") or {}
        market_info = getattr(market, "info", None) or {}
        last = float(t.get("last") or 0)
        exchange = str(info.get("instType") or market_info.get("instType") or "").upper()
        venue = str(getattr(market, "exchange", "")).upper()
        contract_type = str(getattr(market, "contract_type", "")).lower()
        is_okx_derivative = (venue == "OKX" and contract_type in {"swap", "future", "perpetual"}) or exchange in {"SWAP", "FUTURES"} or bool(market_info.get("ctVal"))
        if is_okx_derivative:
            try:
                contracts = float(info.get("vol24h") or 0)
                ct_val = float(market_info.get("ctVal") or info.get("ctVal") or 0)
                ct_mult = float(market_info.get("ctMult") or info.get("ctMult") or 1)
                if contracts > 0 and ct_val > 0 and ct_mult > 0:
                    value_ccy = str(market_info.get("ctValCcy") or info.get("ctValCcy") or "").upper()
                    quote = str(getattr(market, "quote", "USDT") or "USDT").upper()
                    amount = contracts * ct_val * ct_mult
                    ct_type = str(market_info.get("ctType") or info.get("ctType") or "").lower()
                    if value_ccy in {quote, "USD", "USDT"} or ct_type == "inverse":
                        return amount, "okx.vol24h*ctVal*ctMult_quote"
                    if last > 0:
                        return amount * last, "okx.vol24h*ctVal*ctMult_base*last"
            except (TypeError, ValueError):
                pass
            # A trustworthy explicit quote turnover can be used if provided.
            for source, key in ((info, "quoteVolume"), (info, "volCcyQuote"), (info, "turnover24h")):
                try:
                    value = float(source.get(key) or 0)
                    if value > 0:
                        return value, f"{key}_explicit_quote"
                except (TypeError, ValueError):
                    pass
            return 0.0, "okx_contract_metadata_missing"

        try:
            q = float(t.get("quoteVolume") or 0)
            if q > 0:
                return q, "quoteVolume"
        except (TypeError, ValueError):
            pass
        for key in ("quoteVolume", "volCcyQuote", "turnover24h"):
            try:
                q = float(info.get(key) or 0)
                if q > 0:
                    return q, f"info.{key}"
            except (TypeError, ValueError):
                pass
        if last > 0:
            for key in ("baseVolume", "volume", "volCcy24h"):
                try:
                    v = float(t.get(key) or 0)
                    if v > 0:
                        return v * last, f"{key}*last"
                except (TypeError, ValueError):
                    pass
        return 0.0, "none"

    @staticmethod
    def _quote_volume(t, market=None):
        return LiveSignalRunner._quote_volume_info(t, market)[0]

    @staticmethod
    def _liquidation_pressure(records, contract_size=1):
        if not records:
            return None
        signed = total = 0.0
        for r in records:
            info = r.get("info") or {}
            side = str(r.get("side") or info.get("side") or "").lower()
            amount = float(r.get("amount") or r.get("contracts") or 0)
            price = float(r.get("price") or 0)
            usd = abs(amount * contract_size * price)
            if not usd:
                continue
            signed += -usd if side in {"long", "sell"} else usd if side in {"short", "buy"} else 0
            total += usd
        return max(-1, min(1, signed / total)) if total else None

    # ---- universe ---------------------------------------------------------------------
    def refresh_universe(self):
        old = self.markets; merged = {}; success = 0
        for ex, ad in self.adapters.items():
            try:
                ms = ad.load_markets(); success += 1
                found = 0
                for m in ms:
                    if m.active and m.quote == "USDT" and m.settle == "USDT" and m.contract_type in {"swap", "future", "perpetual"}:
                        if m.contract_type == "future" and not self.lcfg.include_dated_futures:
                            continue
                        merged[(m.exchange, m.symbol)] = m; found += 1
                self.tm.exchange_discovered[ex] = found
            except Exception as e:
                log.warning("%s market discovery failed: %s", ex, e)
                self.tm.exchange_status.setdefault(ex, {})["discovery_error"] = str(e)[:200]
        if success:
            self.markets = list(merged.values())
        elif old:
            log.warning("All market discovery calls failed; preserving last good universe (%d)", len(old))
        self.last_refresh = self.clock()
        log.info("Universe refreshed: %d eligible markets", len(self.markets))

    # ---- ranking ----------------------------------------------------------------------
    def _note_ban(self, ex, ad, exc=None):
        until = getattr(ad, "banned_until", 0.0)
        self.tm.exchange_status[ex] = {"banned": True, "banned_until": until,
                                       "remaining_sec": round(max(0.0, until - time.time()), 1),
                                       "message": getattr(ad, "ban_message", "") or (str(exc)[:200] if exc else "")}

    def _fetch_ticks(self, ex, ad, ms):
        """swap and dated-future symbols MUST be fetched in separate batches (ccxt binance rule)."""
        groups = defaultdict(list)
        for m in ms:
            groups["future" if m.contract_type == "future" else "swap"].append(m.symbol)
        ticks = {}
        for kind, syms in groups.items():
            try:
                ticks.update(ad.tickers(syms) or {})
            except Exception as exc:
                if is_ban(exc):
                    self._note_ban(ex, ad, exc)
                    raise
                log.warning("%s %s ticker batch failed: %s", ex, kind, exc)
                self.tm.exchange_status.setdefault(ex, {})[f"{kind}_ticker_error"] = str(exc)[:200]
        return ticks

    def _fill_missing_bid_ask(self, ex, ad, ticks):
        """Binance 24hr ticker has bid=None/ask=None. Complete ONLY liquid candidates from bookTicker (one call)."""
        need = []
        for s, t in ticks.items():
            if t.get("bid") and t.get("ask"):
                continue
            if float(t.get("last") or 0) > 0 and self._quote_volume(t) >= self.cfg.min_quote_volume_usd:
                need.append(s)
        if not need or not hasattr(ad, "bids_asks"):
            return 0
        try:
            got = ad.bids_asks(need) or {}
        except Exception as exc:
            if is_ban(exc):
                self._note_ban(ex, ad, exc)
                raise
            log.warning("%s bids/asks fallback failed: %s", ex, exc)
            self.tm.exchange_status.setdefault(ex, {})["bookticker_error"] = str(exc)[:200]
            return 0
        filled = 0
        for s, x in got.items():
            if s in ticks and x and x.get("bid") and x.get("ask"):
                ticks[s] = {**ticks[s], "bid": x.get("bid"), "ask": x.get("ask")}
                filled += 1
        return filled

    def _rank_tickers(self):
        ranked = {ex: [] for ex in self.adapters}
        for ex, ad in self.adapters.items():
            rr = self.tm.rank_rejections[ex]
            rr.clear()
            ms = [m for m in self.markets if m.exchange == ex]
            if not ms:
                continue
            if hasattr(ad, "banned") and ad.banned():
                self._note_ban(ex, ad)
                self.tm.rank_rejections[ex]["exchange_banned"] = len(ms)
                continue
            try:
                ticks = self._fetch_ticks(ex, ad, ms)
                self._fill_missing_bid_ask(ex, ad, ticks)
            except Exception as e:
                if is_ban(e):
                    rr["exchange_banned"] = len(ms)
                    continue
                log.warning("%s ticker batch failed: %s", ex, e)
                continue
            samples = []
            for m in ms:
                t = ticks.get(m.symbol)
                if not t:
                    rr["no_ticker"] += 1; continue
                bid, ask, last = float(t.get("bid") or 0), float(t.get("ask") or 0), float(t.get("last") or 0)
                if last <= 0:
                    rr["invalid_last"] += 1; continue
                self._last_last[(ex, m.symbol)] = last
                qv, src = self._quote_volume_info(t, m)
                if qv < self.cfg.min_quote_volume_usd:
                    rr["low_volume"] += 1; continue
                if bid > 0 and ask > 0:
                    spread = (ask - bid) / last * 10000
                    if spread > self.cfg.max_spread_bps:
                        rr["wide_spread"] += 1; continue
                else:
                    rr["spread_unknown_admitted"] += 1     # real spread is enforced later from the order book
                ranked[ex].append((qv, m, t))
                samples.append((qv, m.symbol, src))
            ranked[ex].sort(key=lambda x: x[0], reverse=True)
            self.tm.exchange_ranked[ex] = len(ranked[ex])
            if ex not in self.tm.volume_samples:
                top = sorted(samples, reverse=True)[:3]
                self.tm.volume_samples[ex] = [{"symbol": s, "quote_volume_usd": round(v), "source": src} for v, s, src in top]
        return ranked

    def _detail_batch(self, ranked):
        out = []
        n = self.lcfg.detail_symbols_per_exchange
        for ex, items in ranked.items():
            if n <= 0 or len(items) <= n:
                out.extend(items)
                continue
            head, tail = items[:n], items[n:]
            slots = min(max(0, self.lcfg.rotation_slots), len(tail))
            cur = self._rot.get(ex, 0) % len(tail) if tail else 0
            rot = [tail[(cur + i) % len(tail)] for i in range(slots)]
            self._rot[ex] = (cur + slots) % len(tail) if tail else 0
            out.extend(head + rot)
        return out

    def _returns_for_portfolio(self, symbol=None):
        out = {}
        for key, series in self.returns_history.items():
            if len(series) < 3:
                continue
            out[key] = series
            if ":" in key:
                out[key.split(":", 1)[1]] = series
        return out

    def _cached(self, key, ttl, fn):
        now = self.clock()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        val = fn()
        if val is not None:
            self._cache[key] = (now, val)
        return val

    def _market_meta(self, ad, symbol):
        fn = getattr(ad, "market_meta", None)
        if not callable(fn):
            return None
        try:
            return fn(symbol)
        except Exception:
            return None

    # ---- snapshot ---------------------------------------------------------------------
    def snapshot_with_reason(self, m, t=None):
        ad = self.adapters[m.exchange]
        try:
            t = t or ad.ticker(m.symbol)
            book = ad.order_book(m.symbol, self.lcfg.orderbook_limit)
            bids, asks = book.get("bids") or [], book.get("asks") or []
            bid = float(bids[0][0] if bids else (t.get("bid") or 0)); ask = float(asks[0][0] if asks else (t.get("ask") or 0))
            price = float(t.get("last") or ((bid + ask) / 2 if bid and ask else 0))
            if min(bid, ask, price) <= 0:
                return None, "invalid_price"
            spread = (ask - bid) / price * 10000
            qv = self._quote_volume(t, m)
            b = ad.ohlcv(m.symbol, "15m", 100)
            h1 = self._cached(("1h", m.exchange, m.symbol), self.lcfg.htf_cache_sec, lambda: ad.ohlcv(m.symbol, "1h", 60))
            h4 = self._cached(("4h", m.exchange, m.symbol), self.lcfg.htf_cache_sec, lambda: ad.ohlcv(m.symbol, "4h", 60))
            trend, h1t, h4t, imb = self._trend(b), self._trend(h1), self._trend(h4), self._book_imbalance(book)
            if trend is None: return None, "trend_unavailable"
            if h1t is None: return None, "htf1_unavailable"
            if h4t is None: return None, "htf4_unavailable"
            if imb is None: return None, "book_unavailable"
            oi = ad.oi(m.symbol)
            fund = self._cached(("funding", m.exchange, m.symbol), self.lcfg.funding_cache_sec, lambda: ad.funding(m.symbol))
            if oi is None: return None, "oi_unavailable"
            if fund is None: return None, "funding_unavailable"
            key = (m.exchange, m.symbol); now = time.time()
            hist = self.oi_history[key]
            hist.append((now, float(oi)))
            while hist and now - hist[0][0] > max(self.cfg.oi_lookback_sec * 2, 900):
                hist.popleft()
            baseline = None
            for ots, oval in hist:
                if now - ots >= self.cfg.oi_lookback_sec:
                    baseline = oval
                    break
            if baseline is None:
                baseline = self.last_oi.get(key)
            self.last_oi[key] = float(oi)
            if baseline and baseline > 0:
                oi_change = max(-1, min(1, ((float(oi) / baseline) - 1.0) * self.cfg.oi_change_scale))
            else:
                oi_change = 0.0
            liq_rows = ad.liquidations(m.symbol, self.lcfg.liquidation_limit)
            liq = self._liquidation_pressure(liq_rows, m.contract_size)
            ts = book.get("timestamp")
            if ts is None: return None, "book_timestamp_missing"
            try: age = max(0.0, now - float(ts) / 1000.0)
            except (TypeError, ValueError): return None, "book_timestamp_invalid"
            if age > self.lcfg.max_market_age_sec: return None, "market_data_stale"
            closes = [float(x[4]) for x in b if len(x) >= 5 and float(x[4]) > 0]
            if len(closes) >= 4:       # 15m close-to-close returns, used by the correlation gate
                self.returns_history[f"{m.exchange}:{m.symbol}"] = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))][-self.cfg.correlation_window:]
            self._last_last[(m.exchange, m.symbol)] = price
            s = Snapshot(m, now, price, bid, ask, spread, qv, fund, oi, oi_change, imb, liq or 0,
                         trend, h1t * .7 + h4t * .3, age > self.cfg.stale_book_sec, True, True,
                         liq is not None, 1 if liq is not None else .85, self._atr_pct(b))
            if not m.active: return None, "inactive_market"
            return s, "ok"
        except Exception as exc:
            if is_ban(exc):
                self._note_ban(m.exchange, ad, exc)
                return None, "exchange_banned"
            return None, f"exception:{type(exc).__name__}"

    def snapshot(self, m, t=None):
        s, _ = self.snapshot_with_reason(m, t)
        return s

    # ---- paper marks ------------------------------------------------------------------
    def _paper_marks(self):
        marks = {}
        if not self.paper:
            return marks
        by_exchange = defaultdict(list)
        for p in self.paper.open_positions():
            by_exchange[p.exchange].append(p.symbol)
        for ex, symbols in by_exchange.items():
            ad = self.adapters.get(ex)
            if ad is None:
                continue
            unique = list(dict.fromkeys(symbols))
            batch_ok = True
            try:
                ticks = ad.tickers(unique) or {}
            except Exception as exc:
                log.warning("paper mark batch failed %s: %s; falling back per symbol", ex, exc)
                ticks = {}
                batch_ok = False
            for symbol in unique:
                tick = ticks.get(symbol) or {}
                px = float(tick.get("last") or 0)
                if px <= 0 or not batch_ok:
                    try:
                        tick = ad.ticker(symbol) or {}
                        px = float(tick.get("last") or px or 0)
                    except Exception:
                        px = 0
                ts = tick.get("timestamp")
                if ts:
                    try:
                        ts = float(ts) / (1000.0 if float(ts) > 1e11 else 1.0)
                        if time.time() - ts > self.lcfg.max_market_age_sec:
                            px = 0.0
                    except (TypeError, ValueError):
                        px = 0.0
                if px > 0:
                    marks[(ex, symbol)] = px
                    self._last_last[(ex, symbol)] = px
        return marks

    def _monitor_paper_positions(self, force=False):
        if not self.paper:
            return
        now = time.time()
        interval = max(3, min(15, self.lcfg.reconcile_sec))
        if not force and now - getattr(self, "_last_paper_monitor", 0) < interval:
            return
        marks = self._paper_marks()
        if marks:
            self._paper_marks_cache.update(marks)
        for tr in self.paper.update(marks, now=now):
            log.info("PAPER CLOSED %s %s %s exit=%.8g net=%.2f", tr["exchange"], tr["symbol"], tr["reason"], tr["exit"], tr["net_pnl"])
        self._last_paper_monitor = now

    # ---- main loop ----------------------------------------------------------------------
    def _mode_label(self):
        return self.lcfg.mode

    def _checkpoint(self, start, cycles, errors, seen, signals, final=False):
        report = self._build_report(start, cycles, errors, seen, signals, final)
        try:
            Telemetry.write(self.lcfg.report_path, report)
        except Exception as e:
            log.warning("could not write live test report: %s", e)
        return report

    def _handle_signal(self, sig, qv, seen, score_details):
        key = f"{sig.exchange}:{sig.symbol}:{sig.side}"
        self.tm.funnel["passed_min_score"] += 1
        if score_details and score_details.get("aligned"):
            self.tm.funnel["passed_min_score_and_aligned"] += 1
        self.tm.signals_by_exchange[sig.exchange] += 1
        self.tm.signals_by_side[sig.side] += 1
        first = key not in seen
        if first:
            print(f"SIGNAL {time.strftime('%H:%M:%S')} {sig.exchange} {sig.symbol} {sig.side} score={sig.score:.3f} entry={sig.entry:.8g} stop={sig.stop:.8g} target={sig.target:.8g} volume24h={qv:.0f}", flush=True)
        if self.paper is not None:
            if self.paper.has_open(sig.exchange, sig.symbol):
                self.tm.funnel["already_open_skipped"] += 1      # not a rejection: position is simply still open
                return
            returns = self._returns_for_portfolio(sig.symbol)
            meta = self._market_meta(self.adapters[sig.exchange], sig.symbol)
            res = self.paper.submit(sig, returns=returns, meta=meta, marks=self._paper_marks_cache)
            self._record_gate("paper", res, key)
            if res["status"] == "ACCEPTED":
                seen.add(key)
                self.tm.paper_accepted_unique.add(key)
                self.tm.funnel["paper_accepted"] += 1
                log.info("PAPER ACCEPTED %s sizing=%s", key, res.get("sizing"))
            else:
                log.info("PAPER REJECTED %s stage=%s reason=%s %s", key, res["stage"], res["reason"], res.get("detail", ""))
        elif self.lcfg.live_trading:
            returns = self._returns_for_portfolio(sig.symbol)
            rec = self.trading[sig.exchange].submit(sig, returns=returns)
            log.warning("LIVE ORDER %s %s %s", sig.exchange, sig.symbol, rec)
            if rec.get("status") == "SUBMITTED":
                seen.add(key); self.tm.funnel["live_submitted"] += 1
            else:
                self._record_gate("live", rec, key)
        else:
            seen.add(key)

    def _record_gate(self, bucket, res, key):
        if res.get("status") in {"ACCEPTED", "SUBMITTED"}:
            return
        stage, reason = res.get("stage", "?"), res.get("reason", "?")
        if reason.startswith("order_validation_or_exchange_error"):
            reason = "order_validation_or_exchange_error"
        self.tm.record_paper_rejection(stage, reason, key) if bucket == "paper" else self.tm.record_live_rejection(stage, reason, key)
        if stage == "SIZING":
            self.tm.order_skips[reason] += 1

    def run(self):
        start = time.time(); seen = set(); cycles = 0; errors = 0; signals = 0
        self._paper_marks_cache = {}
        score_fh = open(self.lcfg.score_log_path, "a", encoding="utf-8") if self.lcfg.score_log_path else None
        self.refresh_universe()
        deadline = start + self.lcfg.duration_sec
        self._last_paper_monitor = 0.0
        try:
            while time.time() < deadline and (self.lcfg.max_cycles <= 0 or cycles < self.lcfg.max_cycles):
                cycles += 1
                cycle_start = time.time()
                if self.clock() - self.last_refresh >= self.cfg.universe_refresh_sec:
                    self.refresh_universe()
                if self.lcfg.live_trading:
                    for svc in self.trading.values():
                        try: svc.reconcile_all()
                        except Exception as e: log.error("exchange reconciliation failed: %s", e)
                ranked = self._rank_tickers()
                if self.paper is not None:
                    self._paper_marks_cache = {}
                    self._monitor_paper_positions(force=True)
                candidates = self._detail_batch(ranked); candidates.sort(key=lambda x: x[0], reverse=True)
                self.tm.funnel["candidates"] += len(candidates)
                log.info("Cycle %d: universe=%d detailed=%d (volume ranked) mode=%s", cycles, len(self.markets), len(candidates), self._mode_label())
                banned = set()
                processed = 0
                for qv, m, t in candidates:
                    now = time.time()
                    if now >= deadline or (self.lcfg.max_cycle_sec > 0 and now - cycle_start > self.lcfg.max_cycle_sec):
                        self.tm.truncated_cycles += 1
                        log.warning("Cycle %d truncated after %d/%d candidates", cycles, processed, len(candidates))
                        break
                    if m.exchange in banned:
                        self.tm.snapshot_dropped["exchange_banned"] += 1
                        continue
                    try:
                        s, snap_reason = self.snapshot_with_reason(m, t)
                        processed += 1
                        if not s:
                            self.tm.snapshot_dropped[snap_reason] += 1
                            if snap_reason == "exchange_banned":
                                banned.add(m.exchange)
                            continue
                        self.tm.exchange_scanned[m.exchange] += 1
                        self.tm.funnel["snapshots"] += 1
                        sig, reason, details = self.strategy.evaluate_details(s)
                        if details:
                            score = float(details["score"])
                            self.tm.record_score(score)
                            self.tm.funnel["scored"] += 1
                            if score_fh:
                                score_fh.write(json.dumps({"ts": round(time.time(), 3), "ex": m.exchange, "sym": m.symbol, "score": round(score, 6),
                                                           "spread_bps": round(s.spread_bps, 3), "qv": round(qv), "aligned": details.get("aligned"),
                                                           "pass_min": abs(score) >= self.cfg.min_score, "sig": sig.side if sig else None}) + "\n")
                        if not sig:
                            self.tm.strategy_rejections[reason] += 1
                            continue
                        signals += 1
                        self._handle_signal(sig, qv, seen, details)
                    except Exception as e:
                        errors += 1; self.tm.snapshot_dropped[f"exception:{type(e).__name__}"] += 1
                        log.warning("snapshot failed %s %s: %s", m.exchange, m.symbol, e)
                    if self.paper is not None:
                        self._monitor_paper_positions()
                    if self.lcfg.checkpoint_every and processed % self.lcfg.checkpoint_every == 0:
                        self._checkpoint(start, cycles, errors, seen, signals)
                self.tm.cycle_durations.append(time.time() - cycle_start)
                self._checkpoint(start, cycles, errors, seen, signals)
                remaining = deadline - time.time()
                if remaining > 0:
                    time.sleep(max(0, min(self.lcfg.poll_sec, remaining)))
        except KeyboardInterrupt:
            self.tm.notes.append("interrupted_by_user")
            log.warning("interrupted; writing final report")
        finally:
            if score_fh:
                score_fh.close()
        if self.paper is not None:
            self._monitor_paper_positions(force=True)
        report = self._checkpoint(start, cycles, errors, seen, signals, final=True)
        print(f"DONE cycles={cycles} universe={len(self.markets)} detailed_snapshots={report['detailed_snapshots']} signals={signals} unique_signals={len(seen)} errors={errors} duration={int(time.time()-start)}s", flush=True)
        return report

    def _build_report(self, start, cycles, errors, seen, signals, final):
        paper_summary = self.paper.summary(self._paper_marks_cache if hasattr(self, "_paper_marks_cache") else None) if self.paper else None
        corr = dict(self.paper.portfolio.stats) if self.paper else (
            dict(next(iter(self.trading.values())).portfolio.stats) if self.trading else {})
        return self.tm.build_report(
            mode=self._mode_label(), universe_discovered=len(self.markets), cycles=cycles, elapsed=int(time.time() - start),
            errors=errors, unique_signals=len(seen), signals_seen=signals, detail_per_exchange=self.lcfg.detail_symbols_per_exchange,
            exchanges=list(self.adapters.keys()), final=final, paper_summary=paper_summary, correlation_stats=corr,
            config_echo={"min_score": self.cfg.min_score, "max_spread_bps": self.cfg.max_spread_bps,
                         "min_quote_volume_usd": self.cfg.min_quote_volume_usd, "require_alignment": self.cfg.require_alignment,
                         "correlation_limit": self.cfg.correlation_limit, "correlation_min_samples": self.cfg.correlation_min_samples,
                         "rotation_slots": self.lcfg.rotation_slots, "max_cycle_sec": self.lcfg.max_cycle_sec,
                         "poll_sec": self.lcfg.poll_sec, "include_dated_futures": self.lcfg.include_dated_futures,
                         "market_environment": {"BINANCE": "TESTNET" if os.getenv("PHOENIX_BINANCE_SANDBOX", "0") == "1" else "MAINNET_PUBLIC_DATA",
                                                 "OKX": "DEMO" if os.getenv("PHOENIX_OKX_SANDBOX", "0") == "1" else "MAINNET_PUBLIC_DATA"},
                         "max_open_positions": self.cfg.max_open_positions,
                         "max_positions_per_theme": None,
                         "theme_position_count_unlimited": True,
                         "max_reserved_margin_pct": self.cfg.max_reserved_margin_pct})


def main(argv=None):
    ap = argparse.ArgumentParser(description="ACARBOT V22 live scanner (default READ_ONLY)")
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--poll", type=int, default=None)
    ap.add_argument("--detail-per-cycle", type=int, default=None, help="symbols per exchange per cycle (0 = all eligible)")
    ap.add_argument("--rotation-slots", type=int, default=None)
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--max-cycle-sec", type=int, default=None, help="truncate a cycle's detail loop after N seconds (0 = off)")
    ap.add_argument("--no-dated-futures", action="store_true")
    ap.add_argument("--require-mainnet-data", action="store_true", help="refuse to start if any configured exchange is in sandbox/demo mode")
    ap.add_argument("--live", action="store_true", help="submit authenticated exchange orders (needs PHOENIX_CONFIRM_LIVE=YES)")
    ap.add_argument("--paper", action="store_true", help="paper mode: SIZING->RISK->CORRELATION->PAPER, never touches an exchange")
    ap.add_argument("--paper-resume", action="store_true", help="continue from the previous paper_state.json")
    ap.add_argument("--clear-halt", action="store_true", help="clear a persisted kill-switch halt (live state files) and exit")
    ap.add_argument("--equity", type=float, default=None)
    ap.add_argument("--score-log", default=None, help="append one JSON line per scored snapshot")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--report", default=None, help="JSON report path")
    a = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, a.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    base = LiveConfig.from_env()
    if a.require_mainnet_data:
        exchange_ids = [x.strip().upper() for x in os.getenv("PHOENIX_EXCHANGES", "binance,okx").split(",") if x.strip()]
        sandbox_on = [ex for ex in exchange_ids if os.getenv(f"PHOENIX_{ex}_SANDBOX", "0").strip() == "1"]
        if sandbox_on:
            raise SystemExit("Refusing PAPER/READ_ONLY run: sandbox/demo enabled for " + ", ".join(sandbox_on) + ". Set corresponding PHOENIX_<EXCHANGE>_SANDBOX=0.")
    pick = lambda v, d: d if v is None else v
    live_cfg = LiveConfig(
        duration_sec=pick(a.duration, base.duration_sec), poll_sec=pick(a.poll, base.poll_sec),
        detail_symbols_per_exchange=pick(a.detail_per_cycle, base.detail_symbols_per_exchange),
        rotation_slots=pick(a.rotation_slots, base.rotation_slots), max_cycles=pick(a.max_cycles, base.max_cycles),
        max_cycle_sec=pick(a.max_cycle_sec, base.max_cycle_sec),
        include_dated_futures=base.include_dated_futures and not a.no_dated_futures,
        exchange_timeout_ms=base.exchange_timeout_ms, orderbook_limit=base.orderbook_limit, liquidation_limit=base.liquidation_limit,
        max_market_age_sec=base.max_market_age_sec, htf_cache_sec=base.htf_cache_sec, funding_cache_sec=base.funding_cache_sec,
        live_trading=a.live, paper_trading=a.paper or base.paper_trading,
        paper_equity=pick(a.equity, base.paper_equity), paper_resume=a.paper_resume, reconcile_sec=base.reconcile_sec,
        report_path=a.report or base.report_path, score_log_path=a.score_log or base.score_log_path,
        checkpoint_every=base.checkpoint_every,
    )
    if live_cfg.live_trading and live_cfg.paper_trading:       # env defaults must never silently upgrade to LIVE
        if a.live and not a.paper:
            live_cfg.paper_trading = False
        elif a.paper and not a.live:
            live_cfg.live_trading = False
    if a.clear_halt:                       # no exchange access needed: only edits the persisted state files
        from .state import StateStore
        for ex in ("BINANCE", "OKX"):
            path = cfg.state_path.replace(".json", f".{ex.lower()}.json")
            if not os.path.exists(path):
                continue
            store = StateStore(path); st = store.load(); risk = st.setdefault("risk", {})
            had = bool(risk.get("halted_reason"))
            for k in ("halted_reason", "halted_at", "kill_complete"):
                risk.pop(k, None)
            store.save(st); print(f"{ex}: halt {'cleared' if had else 'was not set'} ({path})")
        return
    runner = LiveSignalRunner(cfg=cfg, live_cfg=live_cfg)
    exchanges = list(getattr(runner, "adapters", {}).keys())
    envs = {ex: ("TESTNET/DEMO" if os.getenv(f"PHOENIX_{ex}_SANDBOX", "0") == "1" else "MAINNET_PUBLIC_DATA") for ex in exchanges}
    print(f"[ACARBOT {VERSION}] mode={live_cfg.mode} exchanges={exchanges} market_data_env={envs} "
          f"min_score={cfg.min_score} detail/exchange={live_cfg.detail_symbols_per_exchange} max_cycle_sec={live_cfg.max_cycle_sec}", flush=True)
    runner.run()


if __name__ == "__main__":
    main()
