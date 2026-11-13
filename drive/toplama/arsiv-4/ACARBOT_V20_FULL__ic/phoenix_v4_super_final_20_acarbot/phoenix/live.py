"""Live market-data and optional execution pipeline for Binance/OKX Futures.
Default is read-only. Use --live only after sandbox/paper validation.
"""
from __future__ import annotations
import argparse, json, logging, os, time, random
from collections import defaultdict, deque
from dataclasses import dataclass
try:
    import ccxt
except ImportError:
    ccxt = None
from .config import Config
from .models import Market, Snapshot, Position
from .risk import RiskManager
from .portfolio import PortfolioRisk
from .strategy import Strategy
from .trading import TradingService
from .utils_retry import RetryPolicy, with_retry

log = logging.getLogger("phoenix.live")


@dataclass
class LiveConfig:
    duration_sec: int = 300
    poll_sec: int = 15
    detail_symbols_per_exchange: int = 0
    exchange_timeout_ms: int = 10000
    orderbook_limit: int = 20
    liquidation_limit: int = 50
    max_market_age_sec: float = 20.0
    live_trading: bool = False
    paper_trading: bool = False
    paper_equity: float = 1000.0
    reconcile_sec: int = 15
    report_path: str = "live_test_report.json"

    @classmethod
    def from_env(cls):
        def i(name, default):
            raw=os.getenv(name); return default if raw in (None, "") else int(raw)
        def f(name, default):
            raw=os.getenv(name); return default if raw in (None, "") else float(raw)
        def b(name, default=False):
            raw=os.getenv(name); return default if raw in (None, "") else raw.strip().lower() in {"1","true","yes","on"}
        return cls(
            duration_sec=i("PHOENIX_LIVE_DURATION_SEC",300), poll_sec=i("PHOENIX_LIVE_POLL_SEC",15),
            detail_symbols_per_exchange=i("PHOENIX_LIVE_DETAIL_PER_CYCLE",0), exchange_timeout_ms=i("PHOENIX_EXCHANGE_TIMEOUT_MS",10000),
            orderbook_limit=i("PHOENIX_ORDERBOOK_LIMIT",20), liquidation_limit=i("PHOENIX_LIQUIDATION_LIMIT",50),
            max_market_age_sec=f("PHOENIX_MAX_MARKET_AGE_SEC",20), live_trading=b("PHOENIX_LIVE_TRADING",False),
            paper_trading=b("PHOENIX_PAPER_TRADING",False), paper_equity=f("PHOENIX_PAPER_EQUITY",1000),
            reconcile_sec=i("PHOENIX_RECONCILE_SEC",15), report_path=os.getenv("PHOENIX_LIVE_REPORT_PATH","live_test_report.json")
        )



class PaperExecution:
    """In-memory paper execution that runs the same risk/correlation gates as live."""
    def __init__(self, cfg, equity=1000.0):
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self.portfolio = PortfolioRisk(cfg.correlation_limit, cfg.correlation_window)
        self.equity = float(equity)
        self.peak_equity = self.equity
        self.positions = []
        self.accepted = 0
        self.rejected = defaultdict(int)
        self.fills = []

    def submit(self, signal, returns=None):
        # Do not silently allow multiple simultaneous positions in one instrument.
        if any(p.status == "OPEN" and p.symbol == signal.symbol for p in self.positions):
            reason = f"existing_position:{signal.symbol}"
            self.rejected[reason] += 1
            return {"status": "REJECTED", "reason": reason}

        if returns:
            blocked, symbol, corr = self.portfolio.correlated(signal.symbol, returns, self.positions)
            if blocked:
                reason = f"correlation_limit:{symbol}:{corr:.3f}"
                self.rejected[reason] += 1
                return {"status": "REJECTED", "reason": reason}

        decision = self.risk.can_enter(
            self.equity, self.positions, 0.0, signal.notional,
            daily_loss=0.0, weekly_loss=0.0, peak_equity=self.peak_equity,
        )
        if not decision.allowed:
            self.rejected[decision.reason] += 1
            return {"status": "REJECTED", "reason": decision.reason}

        pid = f"PAPER-{len(self.fills)+1:06d}"
        pos = Position(
            id=pid, exchange=signal.exchange, symbol=signal.symbol, side=signal.side,
            entry=signal.entry, qty=signal.qty, notional=signal.notional, margin=signal.margin,
            stop=signal.stop, target=signal.target, opened_at=signal.created_at,
            entry_fee=self.risk.estimated_entry_fee(signal.notional),
            funding_paid=0.0, status="OPEN", reserved_margin=signal.margin,
            contract_size=signal.contract_size,
        )
        self.positions.append(pos)
        self.accepted += 1
        rec = {
            "status": "PAPER_FILLED", "id": pid, "exchange": signal.exchange,
            "symbol": signal.symbol, "side": signal.side, "score": signal.score,
            "entry": signal.entry, "stop": signal.stop, "target": signal.target,
            "notional": signal.notional, "margin": signal.margin,
        }
        self.fills.append(rec)
        return rec

    def report(self):
        return {
            "paper_equity": self.equity,
            "paper_open_positions": sum(p.status == "OPEN" for p in self.positions),
            "paper_accepted": self.accepted,
            "paper_rejected": sum(self.rejected.values()),
            "paper_rejections": dict(self.rejected),
            "paper_fills": list(self.fills),
        }


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
        if str(exchange_id).lower().startswith("binance") and os.getenv("PHOENIX_BINANCE_PUBLIC_WWW", "0") == "1":
            try:
                from binance_www_route import apply_binance_www_route
                changed = apply_binance_www_route(self.client, force=True)
                if changed:
                    log.info("BINANCE public WWW route enabled: %s", changed)
            except Exception as exc:
                log.warning("BINANCE WWW route could not be applied: %s", exc)
        if sandbox:
            self.client.set_sandbox_mode(True)
        self._markets = None
        self.retry_policy = RetryPolicy(attempts=5, base_delay=0.5, max_delay=8.0)

    def _call(self, fn, *args, **kwargs):
        return with_retry(lambda: fn(*args, **kwargs), self.retry_policy)

    def unify_symbol(self, symbol):
        return str(symbol).strip().upper()

    def exchange_symbol(self, symbol):
        key = self.unify_symbol(symbol)
        if self._markets:
            for ccxt_symbol in self._markets:
                if self.unify_symbol(ccxt_symbol) == key:
                    return ccxt_symbol
        return symbol

    def load_markets(self):
        self._markets = self._call(self.client.load_markets)
        out = []
        for s, m in self._markets.items():
            if m.get("active") is False or not (m.get("swap") or m.get("future")) or m.get("quote") != "USDT" or m.get("settle") != "USDT":
                continue
            prec = m.get("precision") or {}
            limits = m.get("limits") or {}
            amt = limits.get("amount") or {}
            cost = limits.get("cost") or {}
            out.append(Market(self.exchange_id, s, m.get("base", ""), "USDT", "USDT", "swap" if m.get("swap") else "future",
                              float(m.get("contractSize") or 1), True, float(prec.get("price") or 0), float(prec.get("amount") or 0),
                              float(amt.get("min") or 0), float(cost.get("min") or 0)))
        return out

    def market(self, symbol):
        if self._markets is None:
            self.load_markets()
        return self._markets[symbol]

    def tickers(self, symbols):
        if self.client.has.get("fetchTickers"):
            return self._call(self.client.fetch_tickers, symbols)
        return {s: self._call(self.client.fetch_ticker, s) for s in symbols}

    def ticker(self, symbol): return self._call(self.client.fetch_ticker, symbol)
    def book_tickers(self, symbols=None):
        """Fetch best bid/ask in one exchange-native batch when available."""
        if self.exchange_id == "BINANCE":
            for name in ("fapiPublicGetTickerBookTicker", "fapiPublicV2GetTickerBookTicker"):
                fn = getattr(self.client, name, None)
                if fn:
                    try:
                        rows = self._call(fn, {}) or []
                        wanted = set(symbols or [])
                        id_to_symbol = {}
                        if self._markets:
                            id_to_symbol = {str(m.get("id")): s for s, m in self._markets.items()}
                        out = {}
                        for row in rows if isinstance(rows, list) else [rows]:
                            sym = id_to_symbol.get(str(row.get("symbol")))
                            if sym and (not wanted or sym in wanted):
                                out[sym] = {
                                    "bid": row.get("bidPrice") or row.get("bid"),
                                    "ask": row.get("askPrice") or row.get("ask"),
                                }
                        if out:
                            return out
                    except Exception as exc:
                        log.debug("BINANCE bookTicker batch failed: %s", exc)
        out = {}
        for symbol in symbols or []:
            try:
                book = self.order_book(symbol, 5)
                bids, asks = book.get("bids") or [], book.get("asks") or []
                if bids and asks:
                    out[symbol] = {"bid": bids[0][0], "ask": asks[0][0]}
            except Exception:
                continue
        return out

    def order_book(self, symbol, limit=20): return self._call(self.client.fetch_order_book, symbol, limit)
    def ohlcv(self, symbol, tf, limit=100): return self._call(self.client.fetch_ohlcv, symbol, tf, limit=limit)
    def funding(self, symbol):
        try:
            if self.client.has.get("fetchFundingRate"):
                r = self._call(self.client.fetch_funding_rate, self.exchange_symbol(symbol))
                v = r.get("fundingRate")
                if v is not None: return float(v)
        except Exception:
            pass
        # REST fallback for exchanges where CCXT capability metadata is incomplete.
        try:
            if self.exchange_id == "BINANCE" and hasattr(self.client, "fapiPublicGetFundingRate"):
                rows = self._call(self.client.fapiPublicGetFundingRate, {"symbol": self.client.market(self.exchange_symbol(symbol))["id"], "limit": 1})
                if rows: return float(rows[-1].get("fundingRate"))
            if self.exchange_id == "OKX" and hasattr(self.client, "publicGetApiV5PublicFundingRate"):
                inst = self.client.market(self.exchange_symbol(symbol))["id"]
                rows = self._call(self.client.publicGetApiV5PublicFundingRate, {"instId": inst})
                data=(rows.get("data") if isinstance(rows,dict) else rows) or []
                if data: return float(data[0].get("fundingRate"))
        except Exception:
            return None
        return None

    def oi(self, symbol):
        try:
            if self.client.has.get("fetchOpenInterest"):
                r = self._call(self.client.fetch_open_interest, self.exchange_symbol(symbol))
                v = r.get("openInterestAmount")
                if v is None: v = r.get("openInterestValue")
                if v is not None: return float(v)
        except Exception:
            pass
        try:
            if self.exchange_id == "BINANCE" and hasattr(self.client, "fapiPublicGetOpenInterest"):
                row=self._call(self.client.fapiPublicGetOpenInterest, {"symbol": self.client.market(self.exchange_symbol(symbol))["id"]})
                if row.get("openInterest") is not None: return float(row["openInterest"])
            if self.exchange_id == "OKX" and hasattr(self.client, "publicGetApiV5PublicOpenInterest"):
                inst=self.client.market(self.exchange_symbol(symbol))["id"]
                rows=self._call(self.client.publicGetApiV5PublicOpenInterest, {"instType":"SWAP","instId":inst})
                data=(rows.get("data") if isinstance(rows,dict) else rows) or []
                if data:
                    for k in ("oi","oiCcy","oiUsd"):
                        if data[0].get(k) is not None: return float(data[0][k])
        except Exception:
            return None
        return None
    def liquidations(self, symbol, limit=50):
        if not self.client.has.get("fetchLiquidations"):
            return []
        try:
            return self._call(self.client.fetch_liquidations, symbol, limit=limit) or []
        except Exception:
            return []
    def fetch_balance(self): return self._call(self.client.fetch_balance, {"type": "swap"})
    def fetch_positions(self): return self._call(self.client.fetch_positions)
    def fetch_open_orders(self): return self._call(self.client.fetch_open_orders)
    def fetch_my_trades(self, since=None, limit=1000):
        return self._call(self.client.fetch_my_trades, None, since, limit)

    def fetch_my_trades_paginated(self, since=None, until=None, max_records=5000, page_limit=1000):
        """Fetch realized-trade history in bounded pages; deduplicate by exchange id/timestamp.

        Exchanges differ in pagination semantics, so the cursor advances from the newest
        timestamp returned. If an exchange ignores `since`, duplicate rows are removed.
        """
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
    def create_order(self, *a, **kw): return self._call(self.client.create_order, *a, **kw)
    def cancel_order(self, oid, s): return self._call(self.client.cancel_order, oid, s)
    def fetch_order(self, oid, s): return self._call(self.client.fetch_order, oid, s)


class LiveSignalRunner:
    def __init__(self, cfg=None, live_cfg=None, adapters=None):
        self.cfg = cfg or Config.from_env()
        self.lcfg = live_cfg or LiveConfig.from_env()
        self.strategy = Strategy(self.cfg)
        self.adapters = adapters or self._make_adapters()
        self._validate_live_credentials()
        self.markets = []
        self.last_oi = {}
        self.oi_history = defaultdict(deque)
        self.price_history = {}
        self.last_refresh = 0
        self.trading = {}
        self.paper = {}
        self._live_order_ids = set()
        if self.lcfg.paper_trading:
            self.paper = {ex: PaperExecution(self.cfg, self.lcfg.paper_equity) for ex in self.adapters}
        if self.lcfg.live_trading:
            self.trading = {ex: TradingService(ad, self.cfg, self.cfg.state_path.replace(".json", f".{ex.lower()}.json")) for ex, ad in self.adapters.items()}

    def _make_adapters(self):
        return {
            "BINANCE": CCXTAdapter("binance", self.lcfg.exchange_timeout_ms, os.getenv("PHOENIX_BINANCE_API_KEY"), os.getenv("PHOENIX_BINANCE_API_SECRET"), sandbox=os.getenv("PHOENIX_BINANCE_SANDBOX", "0") == "1"),
            "OKX": CCXTAdapter("okx", self.lcfg.exchange_timeout_ms, os.getenv("PHOENIX_OKX_API_KEY"), os.getenv("PHOENIX_OKX_API_SECRET"), os.getenv("PHOENIX_OKX_PASSPHRASE"), sandbox=os.getenv("PHOENIX_OKX_SANDBOX", "0") == "1"),
        }

    def _validate_live_credentials(self):
        if not self.lcfg.live_trading:
            return
        missing = []
        if not os.getenv("PHOENIX_BINANCE_API_KEY") or not os.getenv("PHOENIX_BINANCE_API_SECRET"):
            missing.append("BINANCE_API_KEY/SECRET")
        if not os.getenv("PHOENIX_OKX_API_KEY") or not os.getenv("PHOENIX_OKX_API_SECRET") or not os.getenv("PHOENIX_OKX_PASSPHRASE"):
            missing.append("OKX_API_KEY/SECRET/PASSPHRASE")
        if missing:
            raise RuntimeError("Live trading requested but credentials are missing: " + ", ".join(missing))

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
    def _quote_volume(t, market=None):
        for key in ("quoteVolume",):
            q = t.get(key)
            try:
                if q is not None and float(q) > 0:
                    return float(q)
            except (TypeError, ValueError):
                pass
        info = t.get("info") or {}
        for key in ("quoteVolume", "volCcyQuote", "turnover24h"):
            try:
                q = info.get(key)
                if q is not None and float(q) > 0:
                    return float(q)
            except (TypeError, ValueError):
                pass
        last = float(t.get("last") or 0)
        if last <= 0:
            return 0.0
        # CCXT baseVolume is already normalized to base units; do not apply
        # contractSize a second time. Raw OKX volCcy24h is treated as base
        # currency and converted once to quote currency.
        for key in ("baseVolume", "volume"):
            try:
                v = t.get(key)
                if v is not None and float(v) > 0:
                    return float(v) * last
            except (TypeError, ValueError):
                pass
        for source in (t, info):
            try:
                v = source.get("volCcy24h")
                if v is not None and float(v) > 0:
                    return float(v) * last
            except (TypeError, ValueError):
                pass
        return 0.0

    @staticmethod
    def _book_timestamp_age(ts, now=None):
        if ts is None:
            return None
        now = time.time() if now is None else now
        try:
            value = float(ts)
        except (TypeError, ValueError):
            return None
        # Normalize sec/ms/us/ns without assuming one exchange-specific unit.
        if value > 1e17:
            value /= 1e9
        elif value > 1e14:
            value /= 1e6
        elif value > 1e11:
            value /= 1e3
        return max(0.0, now - value)

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

    def refresh_universe(self):
        old = self.markets; merged = {}; success = 0
        for ex, ad in self.adapters.items():
            try:
                ms = ad.load_markets(); success += 1
                for m in ms:
                    if m.active and m.quote == "USDT" and m.settle == "USDT" and m.contract_type in {"swap", "future", "perpetual"}:
                        merged[(m.exchange, m.symbol)] = m
            except Exception as e:
                log.warning("%s market discovery failed: %s", ex, e)
        if success:
            self.markets = list(merged.values())
        elif old:
            log.warning("All market discovery calls failed; preserving last good universe (%d)", len(old))
        self.last_refresh = time.time()
        log.info("Universe refreshed: %d eligible markets", len(self.markets))

    def _rank_tickers(self):
        ranked = {ex: [] for ex in self.adapters}
        for ex, ad in self.adapters.items():
            ms = [m for m in self.markets if m.exchange == ex]
            if not ms:
                continue
            # Binance CCXT rejects mixed swap/future fetch_tickers batches.
            # Split every exchange batch by contract type; this also keeps the
            # universe explicitly Futures-only (spot is never loaded).
            groups = defaultdict(list)
            for m in ms:
                groups[m.contract_type].append(m)
            ticks = {}
            for contract_type, group in groups.items():
                symbols = [m.symbol for m in group]
                try:
                    ticks.update(ad.tickers(symbols))
                except Exception as exc:
                    log.warning("%s %s ticker batch failed: %s", ex, contract_type, exc)
                    # Fall back per symbol so one bad contract class does not
                    # erase the other class.
                    for m in group:
                        try:
                            ticks[m.symbol] = ad.ticker(m.symbol)
                        except Exception as symbol_exc:
                            log.warning("%s ticker failed %s: %s", ex, m.symbol, symbol_exc)

            missing_book = [
                m.symbol for m in ms
                if not (
                    float((ticks.get(m.symbol) or {}).get("bid") or 0) > 0
                    and float((ticks.get(m.symbol) or {}).get("ask") or 0) > 0
                )
            ]
            book_ticks = ad.book_tickers(missing_book) if missing_book and hasattr(ad, 'book_tickers') else {}
            for m in ms:
                t = ticks.get(m.symbol) or {}
                bt = book_ticks.get(m.symbol) or {}
                bid = float(t.get("bid") or bt.get("bid") or 0)
                ask = float(t.get("ask") or bt.get("ask") or 0)
                last = float(t.get("last") or 0)
                qv = self._quote_volume(t, m)
                spread = (ask - bid) / last * 10000 if last and bid and ask else 99999
                if last > 0 and qv >= self.cfg.min_quote_volume_usd and spread <= self.cfg.max_spread_bps:
                    ranked[ex].append((qv, m, t))
            ranked[ex].sort(key=lambda x: x[0], reverse=True)
        return ranked

    def _detail_batch(self, ranked):
        out = []
        for ex, items in ranked.items():
            out.extend(items if self.lcfg.detail_symbols_per_exchange <= 0 else items[:self.lcfg.detail_symbols_per_exchange])
        return out

    def _returns_for_portfolio(self, symbol):
        out = {}
        for key, prices in self.price_history.items():
            if len(prices) < 4:
                continue
            series = [(prices[i] / prices[i-1] - 1.0) for i in range(1, len(prices))]
            out[key] = series
            if ":" in key:
                out[key.split(":", 1)[1]] = series
        return out

    def snapshot_with_reason(self, m, t=None):
        ad = self.adapters[m.exchange]
        try:
            t = t or ad.ticker(m.symbol)
            book = ad.order_book(m.symbol, self.lcfg.orderbook_limit)
            bids, asks = book.get("bids") or [], book.get("asks") or []
            bid = float(t.get("bid") or (bids[0][0] if bids else 0)); ask = float(t.get("ask") or (asks[0][0] if asks else 0)); price = float(t.get("last") or ((bid + ask) / 2 if bid and ask else 0))
            if min(bid, ask, price) <= 0:
                return None, "invalid_price"
            spread = (ask - bid) / price * 10000
            qv = self._quote_volume(t, m)
            b = ad.ohlcv(m.symbol, "15m", 100); h1 = ad.ohlcv(m.symbol, "1h", 60); h4 = ad.ohlcv(m.symbol, "4h", 60)
            trend, h1t, h4t, imb = self._trend(b), self._trend(h1), self._trend(h4), self._book_imbalance(book)
            if trend is None: return None, "trend_unavailable"
            if h1t is None: return None, "htf1_unavailable"
            if h4t is None: return None, "htf4_unavailable"
            if imb is None: return None, "book_unavailable"
            oi, fund = ad.oi(m.symbol), ad.funding(m.symbol)
            if oi is None: return None, "oi_unavailable"
            if fund is None: return None, "funding_unavailable"
            key = (m.exchange, m.symbol); now = time.time()
            hist = self.oi_history[key]
            hist.append((now, float(oi)))
            while hist and now - hist[0][0] > max(self.cfg.oi_lookback_sec * 2, 900):
                hist.popleft()
            baseline = None
            target_age = self.cfg.oi_lookback_sec
            for ots, oval in hist:
                if now - ots >= target_age:
                    baseline = oval
                    break
            if baseline is None:
                prev = self.last_oi.get(key)
                baseline = prev if prev is not None else None
            self.last_oi[key] = float(oi)
            if baseline and baseline > 0:
                oi_change = max(-1, min(1, ((float(oi) / baseline) - 1.0) * self.cfg.oi_change_scale))
            else:
                oi_change = 0.0
            liq_rows = ad.liquidations(m.symbol, self.lcfg.liquidation_limit)
            liq = self._liquidation_pressure(liq_rows, m.contract_size)
            ts = book.get("timestamp")
            if ts is None: return None, "book_timestamp_missing"
            age = self._book_timestamp_age(ts, now)
            if age is None: return None, "book_timestamp_invalid"
            if age > self.lcfg.max_market_age_sec: return None, "market_data_stale"
            key_hist = f"{m.exchange}:{m.symbol}"
            ph = self.price_history.setdefault(key_hist, [])
            ph.append(price); del ph[:-100]
            s = Snapshot(m, now, price, bid, ask, spread, qv, fund, oi, oi_change, imb, liq or 0,
                         trend, h1t * .7 + h4t * .3, age > self.cfg.stale_book_sec, True, True,
                         liq is not None, 1 if liq is not None else .85)
            if not m.active: return None, "inactive_market"
            return s, "ok"
        except Exception as exc:
            return None, f"exception:{type(exc).__name__}"

    def snapshot(self, m, t=None):
        s, _ = self.snapshot_with_reason(m, t)
        return s

    def run(self):
        start = time.time()
        signal_seen = set()
        snapshots = 0
        cycles = 0
        errors = 0
        signals = 0
        universe_scanned_total = 0
        diagnostics = {
            "snapshot_dropped": defaultdict(int),
            "strategy_rejections": defaultdict(int),
            "score_min": None, "score_max": None, "score_sum": 0.0, "score_count": 0,
            "score_histogram": {f"{i/10:.1f}-{(i+1)/10:.1f}": 0 for i in range(10)},
            "signals_by_exchange": defaultdict(int), "signals_by_side": defaultdict(int),
            "paper_execution": defaultdict(int),
        }
        self.refresh_universe()

        while time.time() - start < self.lcfg.duration_sec:
            cycles += 1
            if time.time() - self.last_refresh >= self.cfg.universe_refresh_sec:
                self.refresh_universe()

            if self.lcfg.live_trading:
                for svc in self.trading.values():
                    try:
                        svc.reconcile_all()
                    except Exception as e:
                        errors += 1
                        log.error("exchange reconciliation failed: %s", e)

            ranked = self._rank_tickers()
            candidates = self._detail_batch(ranked)
            candidates.sort(key=lambda x: x[0], reverse=True)
            universe_scanned_total += len(candidates)
            exchange_scanned = {ex: sum(1 for _, m, _ in candidates if m.exchange == ex) for ex in self.adapters}
            log.info(
                "Cycle %d: universe_discovered=%d detailed=%d exchange_scanned=%s (volume ranked)",
                cycles, len(self.markets), len(candidates), exchange_scanned
            )

            for qv, m, t in candidates:
                try:
                    s, snap_reason = self.snapshot_with_reason(m, t)
                    if not s:
                        diagnostics["snapshot_dropped"][snap_reason] += 1
                        continue

                    snapshots += 1
                    sig, reason, details = self.strategy.evaluate_details(s)
                    if details:
                        score = float(details["score"])
                        diagnostics["score_min"] = score if diagnostics["score_min"] is None else min(diagnostics["score_min"], score)
                        diagnostics["score_max"] = score if diagnostics["score_max"] is None else max(diagnostics["score_max"], score)
                        diagnostics["score_sum"] += score
                        diagnostics["score_count"] += 1
                        a = min(0.999999, abs(score))
                        bucket = min(9, int(a * 10))
                        diagnostics["score_histogram"][f"{bucket/10:.1f}-{(bucket+1)/10:.1f}"] += 1

                    if not sig:
                        diagnostics["strategy_rejections"][reason] += 1
                        continue

                    signals += 1
                    diagnostics["signals_by_exchange"][sig.exchange] += 1
                    diagnostics["signals_by_side"][sig.side] += 1
                    key = f"{sig.exchange}:{sig.symbol}:{sig.side}"
                    if key in signal_seen:
                        continue

                    signal_seen.add(key)
                    print(
                        f"SIGNAL {time.strftime('%H:%M:%S')} {sig.exchange} {sig.symbol} {sig.side} "
                        f"score={sig.score:.3f} entry={sig.entry:.8g} stop={sig.stop:.8g} "
                        f"target={sig.target:.8g} volume24h={qv:.0f}",
                        flush=True,
                    )

                    returns = self._returns_for_portfolio(f"{sig.exchange}:{sig.symbol}")
                    if self.lcfg.paper_trading:
                        rec = self.paper[sig.exchange].submit(sig, returns=returns)
                        diagnostics["paper_execution"][rec.get("status", "UNKNOWN")] += 1
                        if rec.get("status") == "REJECTED":
                            diagnostics["paper_execution"][f"REJECT:{rec.get('reason', 'unknown')}"] += 1
                        log.info("PAPER EXECUTION %s %s %s", sig.exchange, sig.symbol, rec)
                    elif self.lcfg.live_trading:
                        rec = self.trading[sig.exchange].submit(sig, returns=returns)
                        diagnostics["paper_execution"][f"LIVE_{rec.get('status', 'UNKNOWN')}"] += 1
                        log.warning("LIVE ORDER %s %s %s", sig.exchange, sig.symbol, rec)

                except Exception as e:
                    errors += 1
                    diagnostics["snapshot_dropped"][f"exception:{type(e).__name__}"] += 1
                    log.warning("snapshot failed %s %s: %s", m.exchange, m.symbol, e)

            # Persist a checkpoint every cycle so an interrupted run still leaves
            # the complete diagnostic trail.
            elapsed = int(time.time() - start)
            report = self._build_report(
                start, cycles, snapshots, signals, errors, signal_seen, diagnostics,
                final=False, elapsed=elapsed, universe_scanned_total=universe_scanned_total
            )
            try:
                with open(self.lcfg.report_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log.warning("could not write live test checkpoint: %s", e)

            remaining = self.lcfg.duration_sec - (time.time() - start)
            if remaining <= 0:
                break
            time.sleep(min(max(0, self.lcfg.poll_sec), remaining))

        report = self._build_report(
            start, cycles, snapshots, signals, errors, signal_seen, diagnostics,
            final=True, elapsed=int(time.time() - start),
            universe_scanned_total=universe_scanned_total
        )
        try:
            with open(self.lcfg.report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("could not write live test report: %s", e)

        print(
            f"DONE cycles={cycles} universe_discovered={len(self.markets)} "
            f"detailed_snapshots={snapshots} signals={signals} unique_signals={len(signal_seen)} "
            f"errors={errors} duration={int(time.time()-start)}s",
            flush=True,
        )
        return report

    def _build_report(self, start, cycles, snapshots, signals, errors, signal_seen,
                      diagnostics, final, elapsed, universe_scanned_total=0):
        score_count = diagnostics["score_count"]
        paper = {}
        for ex, engine in self.paper.items():
            paper[ex] = engine.report()
        return {
            "version": "5.0.0-acarbot-v20",
            "mode": "LIVE" if self.lcfg.live_trading else ("PAPER" if self.lcfg.paper_trading else "READ_ONLY"),
            "duration_sec": elapsed,
            "cycles": cycles,
            "universe_discovered": len(self.markets),
            "universe_scanned_total": universe_scanned_total,
            "universe": len(self.markets),
            "detailed_snapshots": snapshots,
            "signals_seen": signals,
            "unique_signals": len(signal_seen),
            "errors": errors,
            "exchanges": list(self.adapters.keys()),
            "detail_per_cycle": self.lcfg.detail_symbols_per_exchange,
            "score_min": diagnostics["score_min"],
            "score_max": diagnostics["score_max"],
            "score_mean": diagnostics["score_sum"] / score_count if score_count else None,
            "score_histogram": dict(diagnostics["score_histogram"]),
            "snapshot_dropped": dict(diagnostics["snapshot_dropped"]),
            "strategy_rejections": dict(diagnostics["strategy_rejections"]),
            "signals_by_exchange": dict(diagnostics["signals_by_exchange"]),
            "signals_by_side": dict(diagnostics["signals_by_side"]),
            "paper_execution": dict(diagnostics["paper_execution"]),
            "paper_by_exchange": paper,
            "final": final,
            "timestamp": int(time.time()*1000),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--poll", type=int, default=None)
    ap.add_argument("--detail-per-cycle", type=int, default=None)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="submit authenticated exchange orders")
    mode.add_argument("--paper", action="store_true", help="paper mode; never submits exchange orders")
    mode.add_argument("--read-only", action="store_true", help="force read-only mode")
    ap.add_argument("--equity", type=float, default=None)
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--report", default=None, help="JSON report path")
    a = ap.parse_args()
    logging.basicConfig(level=getattr(logging, a.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    base = LiveConfig.from_env()
    if a.read_only:
        live_mode, paper_mode = False, False
    elif a.paper:
        live_mode, paper_mode = False, True
    elif a.live:
        live_mode, paper_mode = True, False
    else:
        live_mode, paper_mode = base.live_trading, base.paper_trading
    live_cfg = LiveConfig(
        duration_sec=a.duration if a.duration is not None else base.duration_sec,
        poll_sec=a.poll if a.poll is not None else base.poll_sec,
        detail_symbols_per_exchange=a.detail_per_cycle if a.detail_per_cycle is not None else base.detail_symbols_per_exchange,
        exchange_timeout_ms=base.exchange_timeout_ms, orderbook_limit=base.orderbook_limit, liquidation_limit=base.liquidation_limit,
        max_market_age_sec=base.max_market_age_sec, live_trading=live_mode,
        paper_trading=paper_mode, paper_equity=a.equity if a.equity is not None else base.paper_equity,
        reconcile_sec=base.reconcile_sec, report_path=a.report or base.report_path
    )
    if os.path.exists(live_cfg.report_path):
        try:
            os.remove(live_cfg.report_path)
        except OSError:
            pass
    LiveSignalRunner(cfg=cfg, live_cfg=live_cfg).run()


if __name__ == "__main__":
    main()
