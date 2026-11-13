"""Çoklu Borsa Yöneticisi (Binance USDⓈ-M + OKX USDT-M Swap) + Paper Simülatör + Failover.

Multi-Exchange Failover (Yedekleme):
  - Birincil borsada ardı ardına `timeout_esigi` kadar ağ/timeout hatası alınırsa
    `soguma_saniye` boyunca trafik ve yeni pozisyonlar sağlıklı yedek borsaya yönlendirilir.
  - Açık pozisyonu kapatma/mutabakat istekleri ise asla yanlış borsaya kaydırılmaz.
"""
from __future__ import annotations

import asyncio
import math
import os
import time
import uuid

from .futures_catalog import build_futures_catalog
from .maker_queue_sim import RealisticMakerQueueSimulator
from .security import safe_exception_msg

_TIMEOUT_KEYWORDS = (
    "timeout",
    "timed out",
    "networkerror",
    "requesttimeout",
    "ddosprotection",
    "exchangenotavailable",
    "service unavailable",
    "connection reset",
    "cannot connect",
    "502",
    "503",
    "504",
)


def is_timeout_or_network_error(exc: BaseException | str) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return True
    cls_name = type(exc).__name__.lower() if isinstance(exc, BaseException) else ""
    text = f"{cls_name} {exc}".lower()
    return any(kw in text for kw in _TIMEOUT_KEYWORDS)


class PaperBroker:
    """Gerçekçi komisyon, funding, kayma (slippage) ve reduce-only korumalı sanal borsa."""

    def __init__(
        self,
        balance_usdt: float = 100_000.0,
        fee_taker_pct: float = 0.05,
        fee_maker_pct: float = 0.02,
        max_slippage_pct: float = 0.30,
    ):
        self.start_balance = float(balance_usdt)
        self.balance = float(balance_usdt)
        self.fee_taker_pct = float(fee_taker_pct)
        self.fee_maker_pct = float(fee_maker_pct)
        self.max_slippage_pct = float(max_slippage_pct)
        self.trades: list[dict] = []
        self.protections: dict[str, dict] = {}
        # İşaretli baz miktar: LONG > 0, SHORT < 0. Executor'dan bağımsız
        # ikinci savunma hattı olarak reduce-only dolgularını sınırlar.
        self.position_qty: dict[str, float] = {}
        self.total_fees_usdt = 0.0
        self.total_funding_usdt = 0.0
        self.funding_history: list[dict] = []

    def sync_position(self, symbol: str, side: str, qty: float):
        """Restore edilen pozisyonu paper emir defterine geri yükler."""
        qty = abs(float(qty))
        if qty <= 1e-12:
            self.position_qty.pop(symbol, None)
            return
        direction = 1.0 if str(side).upper() == "LONG" else -1.0
        self.position_qty[symbol] = direction * qty

    def _apply_position_fill(
        self, symbol: str, side: str, qty: float, reduce_only: bool = False
    ) -> tuple[float, float]:
        """Dolgu miktarını açık pozisyonla sınırlar; ters pozisyon açmaz."""
        requested = float(qty)
        if requested <= 0:
            raise ValueError("Dolgu miktarı sıfırdan büyük olmalı")
        side = str(side).lower()
        if side not in {"buy", "sell"}:
            raise ValueError(f"Geçersiz emir yönü: {side}")
        current = float(self.position_qty.get(symbol, 0.0))
        filled = requested
        if reduce_only:
            if abs(current) <= 1e-12:
                raise ValueError(f"Reduce-only kapama reddedildi: {symbol} açık pozisyon yok")
            if (current > 0 and side != "sell") or (current < 0 and side != "buy"):
                raise ValueError(
                    f"Reduce-only yönü pozisyonu kapatmıyor: {symbol} {side}"
                )
            filled = min(requested, abs(current))
        delta = filled if side == "buy" else -filled
        remaining = current + delta
        if abs(remaining) <= 1e-12:
            self.position_qty.pop(symbol, None)
            remaining = 0.0
        else:
            self.position_qty[symbol] = remaining
        return filled, remaining

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
        reduce_only: bool = False,
    ) -> dict:
        requested_qty = float(qty)
        qty, position_after = self._apply_position_fill(
            symbol, side, requested_qty, reduce_only=reduce_only
        )
        fee = qty * price * fee_pct / 100
        self.balance -= fee
        self.total_fees_usdt += fee
        fill = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "requested_qty": requested_qty,
            "position_qty": position_after,
            "reduce_only": bool(reduce_only),
            "price": price,
            # Kasa ve işlem bazlı net rapor aynı tam değeri kullanır; iki
            # ondalığa erken yuvarlama yüzlerce fill'de mutabakat farkı üretir.
            "fee": float(fee),
            "slippage_pct": round(slippage_pct, 4),
            "ts": time.time(),
            "mode": "paper",
            "exchange": exchange,
            "emir_tipi": kind,
        }
        self.trades.append(fill)
        return fill

    def realize_pnl(self, pnl_usdt: float):
        """Pozisyon kapandığında gerçekleşen dolar kâr/zararını kasaya işler."""
        # Muhasebe değeri yuvarlanmaz; yalnız raporlama sırasında biçimlenir.
        # Aksi hâlde funding ondalıkları kapama anında kasadan silinebilir.
        self.balance += float(pnl_usdt)

    def apply_funding(self, symbol: str, cash_delta: float, rate: float, elapsed_sec: float):
        """Funding ödemesini/alacağını sanal kasaya ve denetim kaydına işler."""
        delta = float(cash_delta)
        if delta == 0:
            return
        self.balance += delta
        self.total_funding_usdt += delta
        self.funding_history.append(
            {
                "ts": time.time(),
                "symbol": symbol,
                "cash_delta": delta,
                "rate": float(rate),
                "elapsed_sec": float(elapsed_sec),
            }
        )

    def market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        exchange: str = "binance",
        slippage_pct: float = 0.0,
        price_source: str = "hint",
        reduce_only: bool = False,
    ) -> dict:
        fill = self._fill(
            symbol,
            side,
            qty,
            price,
            self.fee_taker_pct,
            "market",
            slippage_pct=slippage_pct,
            exchange=exchange,
            reduce_only=reduce_only,
        )
        fill["price_source"] = price_source
        return fill

    def maker_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        exchange: str = "binance",
    ) -> dict:
        tick = price * 0.0001
        fill_px = (price - tick) if side == "buy" else (price + tick)
        return self._fill(
            symbol, side, qty, fill_px, self.fee_maker_pct, "maker", exchange=exchange
        )

    def chase_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        expected_price: float,
        current_price: float,
        max_slippage_pct: float = 0.30,
        exchange: str = "binance",
    ) -> dict:
        cap = (
            expected_price * (1.0 + max_slippage_pct / 100.0)
            if side == "buy"
            else expected_price * (1.0 - max_slippage_pct / 100.0)
        )
        fill_px = min(current_price, cap) if side == "buy" else max(current_price, cap)
        slip = abs(fill_px - expected_price) / max(expected_price, 1e-12) * 100.0
        return self._fill(
            symbol,
            side,
            qty,
            fill_px,
            self.fee_maker_pct,
            "chase_limit",
            slippage_pct=slip,
            exchange=exchange,
        )


class ExchangeManager:
    def __init__(self, cfg: dict):
        g = cfg.get("genel", {})
        self.mode = str(g.get("mod", "paper")).lower()
        self.symbols: list[str] = list(g.get("semboller", []))
        self.leverage = int(
            g.get("kaldıraç", cfg.get("boyutlandirma", {}).get("kaldirac", 20)) or 20
        )
        api = cfg.get("api", {})
        em = cfg.get("emirler", {})
        rk = cfg.get("risk", {})
        sg = cfg.get("sigorta", {})
        fo = cfg.get("failover", {})
        paper_cfg = cfg.get("paper", {})
        self.margin_mode = str(rk.get("marj_modu", "cross")).strip().lower()
        self.paper_realistic = bool(paper_cfg.get("gercekci_yurutme", False))
        self.smart_maker_execution = bool(
            em.get("akilli_maker_yurutme", paper_cfg.get("akilli_maker_yurutme", False))
        )
        self.max_maker_spread_pct = float(
            em.get("max_maker_makas_yuzde", 0.08)
        )
        self.paper_funding_enabled = bool(paper_cfg.get("funding_aktif", False))
        self.dynamic_atr_slippage = bool(paper_cfg.get("dinamik_atr_kayma", False))
        self.symbol_volatility_meta: dict[str, dict[str, float]] = {}
        self.max_slippage_pct = float(
            em.get("max_kayma_yuzde", rk.get("max_kayma_yuzde", 0.30))
        )
        self.failover_enabled = bool(fo.get("aktif", True))
        self.max_exchange_timeouts = int(
            fo.get("timeout_esigi", sg.get("borsa_timeout_esik", 3))
        )
        self.failover_cooldown_sec = float(
            fo.get("soguma_saniye", sg.get("failover_suresi_sn", 300.0))
        )

        self.paper = PaperBroker(
            balance_usdt=float(paper_cfg.get("bakiye", 100000.0)),
            fee_taker_pct=em.get("komisyon_taker_yuzde", 0.05),
            fee_maker_pct=em.get("komisyon_maker_yuzde", 0.02),
            max_slippage_pct=self.max_slippage_pct,
        )
        self._ex: dict = {}
        self._leverage_set: set[str] = set()
        self.rest_data_stats: dict[str, dict] = {}

        from . import ccxt_compat as ccxt

        self.default_type = "swap" if self.leverage > 1 else "spot"
        default_type = self.default_type

        if "binance" in g.get("borsalar", []):
            b = ccxt.binance(
                {
                    "apiKey": api.get("binance_key", ""),
                    "secret": api.get("binance_secret", ""),
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": default_type,
                        # Futures botunda spot/COIN-M kataloglarını yüklemek
                        # gereksizdir; spot exchangeInfo'daki bölge hatası
                        # USDT-M katalogunu da düşürmesin.
                        "fetchMarkets": {"types": ["linear"]},
                    },
                }
            )
            if self.mode == "testnet":
                b.set_sandbox_mode(True)
            elif os.environ.get("BINANCE_PUBLIC_WWW") == "1":
                # Bazı GitHub/bulut IP'lerinde fapi.binance.com HTTP 451
                # döndürürken Binance'in resmî www alan adındaki aynı public
                # USD-M rotaları 200 olabiliyor. Yalnız imzasız public veri
                # uçlarını değiştir; private/emir uçları ve WS aynı kalsın.
                for key in ("fapiPublic", "fapiPublicV2", "fapiPublicV3", "fapiData"):
                    current = b.urls.get("api", {}).get(key)
                    if isinstance(current, str) and current.startswith(
                        "https://fapi.binance.com"
                    ):
                        b.urls["api"][key] = current.replace(
                            "https://fapi.binance.com",
                            "https://www.binance.com",
                            1,
                        )
            self._ex["binance"] = b

        if "okx" in g.get("borsalar", []):
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
                o.set_sandbox_mode(True)
            self._ex["okx"] = o

        if not self._ex:
            raise ValueError("En az bir borsa etkin olmalı (binance veya okx)")

        self._default_primary: str = next(iter(self._ex))
        self._active_primary: str = self._default_primary
        self._ex_timeouts: dict[str, int] = {name: 0 for name in self._ex}
        self._ex_total_timeouts: dict[str, int] = {name: 0 for name in self._ex}
        self._ex_degraded_until: dict[str, float] = {name: 0.0 for name in self._ex}
        self.failover_count: int = 0
        self.failover_history: list[dict] = []
        # Boş harita eski, yapılandırılmış sembol davranışını korur. Futures
        # katalogu doldurulduğunda emir yalnız sembolü listeleyen borsaya gider.
        self.symbol_exchanges: dict[str, list[str]] = {}
        self.leverage_restricted_symbols: set[str] = set()
        # (exchange, symbol) -> (bid, ask, mono_ts) gerçek zamanlı WS/BBO önbelleği
        self.live_bbo: dict[tuple[str, str], tuple[float, float, float]] = {}
        self.maker_queue_sim: RealisticMakerQueueSimulator | None = (
            RealisticMakerQueueSimulator()
            if bool(cfg.get("paper", {}).get("gercekci_maker_kuyruk", False))
            else None
        )
        self.rest_data_stats = {
            name: {
                "ohlcv_success": 0,
                "ohlcv_errors": 0,
                "ticker_success": 0,
                "ticker_errors": 0,
                "paper_fills": 0,
            }
            for name in self._ex
        }

    def _mark_rest(self, exchange: str, kind: str, success: bool):
        row = self.rest_data_stats.setdefault(exchange, {})
        key = f"{kind}_{'success' if success else 'errors'}"
        row[key] = int(row.get(key, 0)) + 1

    def rest_stats_snapshot(self) -> dict:
        rows = {name: dict(row) for name, row in self.rest_data_stats.items()}
        for fill in self.paper.trades:
            name = str(fill.get("exchange") or "")
            if name:
                row = rows.setdefault(name, {})
                row["paper_fills"] = int(row.get("paper_fills", 0)) + 1
        return rows

    def choose_symbol_exchange(self, symbol: str, preferred: str | None = None) -> str:
        """Sembolü gerçekten listeleyen sağlıklı borsayı seçer."""
        allowed = getattr(self, "symbol_exchanges", {}).get(symbol) or list(self._ex)
        candidates = [preferred] if preferred else []
        candidates += allowed
        candidates += [self.primary, *self._ex]
        now = time.time()
        for name in candidates:
            if (
                name in allowed
                and name in self._ex
                and self.is_exchange_healthy(name, now)
            ):
                return name
        # Tüm destekleyen borsalar degraded ise kapama/kurtarma istekleri için
        # desteklenen ilk borsayı döndür; asla desteklemeyen borsaya geçme.
        for name in allowed:
            if name in self._ex:
                return name
        raise RuntimeError(f"{symbol} için desteklenen borsa yok: {allowed}")

    async def discover_futures(
        self,
        preferred_symbols: list[str] | None = None,
        min_leverage: int = 10,
        max_symbols: int = 0,
        *,
        exclude_non_crypto: bool = True,
    ) -> dict:
        """Tüm aktif USDT perpetual piyasalarını yükler ve WS/emir yönünü sabitler."""
        if self.default_type != "swap":
            raise RuntimeError("Futures keşfi yalnız kaldıraçlı swap modunda kullanılabilir")

        async def load(name: str):
            markets = await self._ex[name].load_markets()
            return name, markets

        results = await asyncio.gather(
            *(load(name) for name in self._ex), return_exceptions=True
        )
        exchange_markets: dict[str, dict] = {}
        errors: dict[str, str] = {}
        for name, result in zip(self._ex, results):
            if isinstance(result, Exception):
                errors[name] = safe_exception_msg(result)
                print(f"⚠️ {name} Futures katalogu yüklenemedi: {errors[name]}", flush=True)
            else:
                _, markets = result
                exchange_markets[name] = markets

        # Analiz evreni borsadaki TÜM aktif USDT perpetual kontratlarıdır.
        # 10x desteklemeyenler dışlanmaz; yalnız emir açma evreninden ayrılır.
        symbols, support = build_futures_catalog(
            exchange_markets,
            preferred_symbols=preferred_symbols,
            min_leverage=1,
            max_symbols=max_symbols,
            exclude_non_crypto=exclude_non_crypto,
        )
        if not symbols:
            raise RuntimeError(f"Kullanılabilir USDT perpetual bulunamadı; hatalar: {errors}")
        trade_eligible, _ = build_futures_catalog(
            exchange_markets,
            preferred_symbols=preferred_symbols,
            min_leverage=min_leverage,
            max_symbols=0,
            exclude_non_crypto=exclude_non_crypto,
        )
        eligible_set = set(trade_eligible)
        trade_symbols = [s for s in symbols if s in eligible_set]
        restricted = [s for s in symbols if s not in eligible_set]
        self.symbols = symbols
        self.symbol_exchanges = support
        self.leverage_restricted_symbols = set(restricted)
        public_rest_urls = {}
        for name, exchange in self._ex.items():
            urls = getattr(exchange, "urls", {})
            fapi_public = urls.get("api", {}).get("fapiPublic") if urls else None
            if fapi_public:
                public_rest_urls[name] = fapi_public
        return {
            "symbols": symbols,
            "trade_symbols": trade_symbols,
            "restricted_leverage_symbols": restricted,
            "support": support,
            "errors": errors,
            "public_rest_urls": public_rest_urls,
            "per_exchange": {
                name: sum(name in exchanges for exchanges in support.values())
                for name in exchange_markets
            },
        }

    def _ccxt_symbol(self, symbol: str) -> str:
        """USDT perpetual için CCXT'nin birleşik sembolünü üretir."""
        if self.default_type == "swap" and ":" not in symbol and symbol.endswith("/USDT"):
            return f"{symbol}:USDT"
        return symbol

    async def get_contract_sizes(self) -> dict[tuple[str, str], float]:
        """WebSocket miktar normalizasyonu için gerçek kontrat boyutlarını okur."""
        if self.default_type != "swap":
            return {}
        out: dict[tuple[str, str], float] = {}

        async def load_one(name: str):
            try:
                markets = await self._ex[name].load_markets()
                for symbol in self.symbols:
                    market = markets.get(self._ccxt_symbol(symbol)) or {}
                    size = float(market.get("contractSize") or 0.0)
                    if size > 0:
                        out[(name, symbol)] = size
            except Exception as exc:
                print(
                    f"⚠️ {name} kontrat metaverisi okunamadı; "
                    f"kontratlı işlem akışı güvenli biçimde atlanacak: {safe_exception_msg(exc)}",
                    flush=True,
                )

        await asyncio.gather(*(load_one(name) for name in self._ex))
        return out

    @staticmethod
    def _client_order_params(exchange: str, client_order_id: str) -> dict:
        key = "clOrdId" if exchange == "okx" else "newClientOrderId"
        return {key: client_order_id}

    @staticmethod
    def _new_client_order_id() -> str:
        return f"kbot{uuid.uuid4().hex[:24]}"

    @property
    def primary(self) -> str:
        now = time.time()
        default_p = getattr(self, "_default_primary", "") or next(iter(self._ex))
        active_p = getattr(self, "_active_primary", "") or default_p
        if active_p != default_p and self.is_exchange_healthy(default_p, now):
            self._active_primary = default_p
            active_p = default_p
        return active_p

    def is_exchange_healthy(self, name: str, now: float | None = None) -> bool:
        now_ts = float(now if now is not None else time.time())
        degraded_map = getattr(self, "_ex_degraded_until", {})
        return now_ts >= float(degraded_map.get(name, 0.0))

    def record_exchange_success(self, exchange: str) -> None:
        if hasattr(self, "_ex_timeouts"):
            self._ex_timeouts[exchange] = 0

    def record_exchange_timeout(self, exchange: str, err: BaseException | str = "") -> None:
        if not hasattr(self, "_ex_timeouts"):
            self._ex_timeouts = {}
        if not hasattr(self, "_ex_total_timeouts"):
            self._ex_total_timeouts = {}
        self._ex_timeouts[exchange] = self._ex_timeouts.get(exchange, 0) + 1
        self._ex_total_timeouts[exchange] = self._ex_total_timeouts.get(exchange, 0) + 1

        if getattr(self, "failover_enabled", True) and (
            self._ex_timeouts[exchange] >= getattr(self, "max_exchange_timeouts", 3)
        ):
            now = time.time()
            self._ex_degraded_until[exchange] = now + getattr(self, "failover_cooldown_sec", 300.0)
            for cand in self._ex:
                if cand != exchange and self.is_exchange_healthy(cand, now):
                    if self._active_primary != cand:
                        self._active_primary = cand
                        self.failover_count = getattr(self, "failover_count", 0) + 1
                        self.failover_history.append(
                            {
                                "ts": now,
                                "from": exchange,
                                "to": cand,
                                "error": safe_exception_msg(err),
                            }
                        )
                        print(
                            f"🔄 FAILOVER: {exchange} üst üste timeout verdi -> aktif borsa {cand} oldu",
                            flush=True,
                        )
                    break

    def choose_healthy_exchange(self, preferred: str | None = None) -> str:
        now = time.time()
        if preferred and preferred in self._ex and self.is_exchange_healthy(preferred, now):
            return preferred
        if self.is_exchange_healthy(self.primary, now):
            return self.primary
        for name in self._ex:
            if self.is_exchange_healthy(name, now):
                return name
        if preferred and preferred in self._ex:
            return preferred
        return self.primary

    def get_failover_order(
        self, preferred: str | None = None, symbol: str | None = None
    ) -> list[str]:
        """Sağlıklı→degraded deneme sırası; sembol desteği varsa onunla sınırlı."""
        now = time.time()
        allowed = list(self._ex)
        sym_ex = getattr(self, "symbol_exchanges", {})
        if symbol is not None and sym_ex.get(symbol):
            allowed = [n for n in sym_ex[symbol] if n in self._ex]
        if not allowed:
            return []
        healthy_allowed = [n for n in allowed if self.is_exchange_healthy(n, now)]
        if preferred in healthy_allowed:
            first = preferred
        elif self.primary in healthy_allowed:
            first = self.primary
        else:
            first = healthy_allowed[0] if healthy_allowed else allowed[0]
        healthy = [n for n in allowed if n != first and self.is_exchange_healthy(n, now)]
        ordered = [first, *healthy]
        ordered += [n for n in allowed if n not in ordered and self.is_exchange_healthy(n, now)]
        ordered += [n for n in allowed if n not in ordered]
        return ordered

    def exchange_health_snapshot(self) -> dict:
        now = time.time()
        exchanges_info = {}
        for name in self._ex:
            until = float(self._ex_degraded_until.get(name, 0.0))
            exchanges_info[name] = {
                "healthy": now >= until,
                "consecutive_timeouts": int(self._ex_timeouts.get(name, 0)),
                "total_timeouts": int(self._ex_total_timeouts.get(name, 0)),
                "cooldown_remaining_sec": round(max(0.0, until - now), 1),
            }
        return {
            "active_primary": self.primary,
            "default_primary": self._default_primary,
            "failover_active": self.primary != self._default_primary,
            "failover_count": self.failover_count,
            "exchanges": exchanges_info,
        }

    async def ensure_leverage(
        self, symbol: str, leverage: int | None = None, exchange: str | None = None
    ) -> None:
        lev = int(leverage or self.leverage)
        if self.mode == "paper" or lev <= 1:
            return
        ex_name = self.choose_symbol_exchange(symbol, exchange)
        key = f"{ex_name}:{symbol}:{lev}"
        if key in self._leverage_set:
            return
        ex = self._ex.get(ex_name)
        if not ex:
            return
        if hasattr(ex, "set_margin_mode"):
            try:
                await ex.set_margin_mode(
                    getattr(self, "margin_mode", "cross"),
                    self._ccxt_symbol(symbol),
                )
            except Exception as mm_err:
                msg_low = str(mm_err).lower()
                if not any(
                    ok_tok in msg_low
                    for ok_tok in ("no need to change", "already", "not modified", "-4046")
                ):
                    print(
                        f"⚠️ {symbol} marj modu ({getattr(self, 'margin_mode', 'cross')}) "
                        f"uyarısı: {safe_exception_msg(mm_err)}",
                        flush=True,
                    )
        # Kaldıraç ayarlanamadan emir göndermek beklenen riskten kat kat yüksek
        # marj/likidasyon sonucu doğurabilir; hatayı gizlemek yerine üst kata ilet.
        await ex.set_leverage(lev, self._ccxt_symbol(symbol))
        self._leverage_set.add(key)

    # -- piyasa verisi (Failover destekli) -------------------------------------
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 300,
        exchange: str | None = None,
    ) -> list:
        last_err = None
        for ex_name in self.get_failover_order(exchange, symbol=symbol):
            ex = self._ex[ex_name]
            try:
                rows = await ex.fetch_ohlcv(self._ccxt_symbol(symbol), timeframe, limit=limit)
                self.record_exchange_success(ex_name)
                self._mark_rest(ex_name, "ohlcv", True)
                return rows
            except Exception as e:
                self._mark_rest(ex_name, "ohlcv", False)
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                continue
        raise last_err or RuntimeError(f"{symbol} OHLCV alınamadı")

    def update_live_bbo(
        self, exchange: str, symbol: str, bid: float, ask: float, ts: float | None = None
    ) -> None:
        """Canlı WebSocket / BBO akışından gelen taze en iyi alış-satış tahtasını önbelleğe yazar."""
        try:
            b, a = float(bid), float(ask)
            if math.isfinite(b) and math.isfinite(a) and b > 0 and a > 0 and a >= b:
                ex_k = str(exchange).strip().lower()
                self.live_bbo[(ex_k, symbol)] = (b, a, time.monotonic())
                self.record_exchange_success(ex_k)
                if getattr(self, "maker_queue_sim", None) is not None:
                    self.maker_queue_sim.on_bbo(ex_k, symbol, b, a, now_ts=ts)
        except (TypeError, ValueError, OverflowError):
            return

    def feed_live_trade_to_maker_queue(
        self,
        exchange: str,
        symbol: str,
        price: float,
        qty: float,
        is_buyer_maker: bool,
        ts: float | None = None,
    ) -> None:
        """Canlı işlem akışını pasif post-only kuyruk simülatörüne iletir."""
        sim = getattr(self, "maker_queue_sim", None)
        if sim is not None:
            sim.on_trade(exchange, symbol, price, qty, is_buyer_maker=bool(is_buyer_maker), now_ts=ts)

    def maker_queue_stats(self) -> dict:
        sim = getattr(self, "maker_queue_sim", None)
        return sim.summary() if sim is not None else {"enabled": False}

    def get_fresh_bbo(
        self, exchange: str, symbol: str, *, max_age_sec: float = 15.0
    ) -> tuple[float, float] | None:
        item = getattr(self, "live_bbo", {}).get((str(exchange).strip().lower(), symbol))
        if not item:
            return None
        bid, ask, mono_ts = item
        if (time.monotonic() - mono_ts) <= max_age_sec and bid > 0 and ask > 0:
            return bid, ask
        return None

    def select_best_exchange(
        self,
        symbol: str,
        side: str,
        open_positions: dict | None = None,
        *,
        max_cross_spread_pct: float = 1.2,
    ) -> tuple[str, dict]:
        """Binance ve OKX canlı BBO tahtalarını karşılaştırarak en avantajlı borsayı seçer."""
        supported = self.symbol_exchanges.get(symbol) or list(self._ex)
        candidates: dict[str, dict] = {}
        open_pos = open_positions or {}
        venue_counts: dict[str, int] = {}
        for p in open_pos.values():
            vex = str(getattr(p, "exchange", "") or "").lower()
            if vex:
                venue_counts[vex] = venue_counts.get(vex, 0) + 1

        for name in supported:
            ex_k = str(name).strip().lower()
            if ex_k not in self._ex or not self.is_exchange_healthy(ex_k):
                continue
            bbo = self.get_fresh_bbo(ex_k, symbol, max_age_sec=20.0)
            if not bbo:
                continue
            bid, ask = bbo
            mid = (bid + ask) / 2.0
            if mid <= 0:
                continue
            spread_pct = (ask - bid) / mid * 100.0
            load_penalty = float(venue_counts.get(ex_k, 0)) * 0.004
            candidates[ex_k] = {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": spread_pct,
                "effective_cost_pct": spread_pct + load_penalty,
                "open_load": venue_counts.get(ex_k, 0),
            }

        if len(candidates) > 1:
            mids = [c["mid"] for c in candidates.values()]
            lo_m, hi_m = min(mids), max(mids)
            if lo_m > 0 and ((hi_m - lo_m) / lo_m * 100.0) > max_cross_spread_pct:
                # Sembol çakışması varsa birincil borsayı koru
                pref = self.primary if self.primary in candidates else next(iter(candidates))
                candidates = {pref: candidates[pref]}

        if candidates:
            chosen = min(candidates, key=lambda k: candidates[k]["effective_cost_pct"])
            return chosen, candidates

        fallback = self.choose_healthy_exchange()
        return fallback, candidates

    async def fetch_price(
        self, symbol: str, exchange: str | None = None
    ) -> float:
        for ex_name in self.get_failover_order(exchange, symbol=symbol):
            bbo = self.get_fresh_bbo(ex_name, symbol, max_age_sec=15.0)
            if bbo:
                return (bbo[0] + bbo[1]) / 2.0
        last_err = None
        for ex_name in self.get_failover_order(exchange, symbol=symbol):
            ex = self._ex[ex_name]
            try:
                t = await ex.fetch_ticker(self._ccxt_symbol(symbol))
                self.record_exchange_success(ex_name)
                self._mark_rest(ex_name, "ticker", True)
                return float(t["last"])
            except Exception as e:
                self._mark_rest(ex_name, "ticker", False)
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                continue
        raise last_err or RuntimeError(f"{symbol} fiyat alınamadı")

    async def fetch_bid_ask(
        self, symbol: str, exchange: str | None = None
    ) -> tuple[float, float]:
        for ex_name in self.get_failover_order(exchange, symbol=symbol):
            bbo = self.get_fresh_bbo(ex_name, symbol, max_age_sec=15.0)
            if bbo:
                self._mark_rest(ex_name, "ticker", True)
                return bbo
        last_err = None
        for ex_name in self.get_failover_order(exchange, symbol=symbol):
            ex = self._ex[ex_name]
            try:
                t = await ex.fetch_ticker(self._ccxt_symbol(symbol))
                self.record_exchange_success(ex_name)
                self._mark_rest(ex_name, "ticker", True)
                bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
                if not bid or not ask:
                    last_px = float(t.get("last") or 0)
                    bid = bid or last_px
                    ask = ask or last_px
                if bid > 0 and ask > 0:
                    self.update_live_bbo(ex_name, symbol, bid, ask)
                    return bid, ask
            except Exception as e:
                self._mark_rest(ex_name, "ticker", False)
                last_err = e
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(ex_name, e)
                continue
        raise last_err or RuntimeError(f"{symbol} bid/ask alınamadı")

    async def fetch_all_quotes(self, symbol: str) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {}
        supported = self.symbol_exchanges.get(symbol) or list(self._ex)
        for name in supported:
            if name not in self._ex:
                continue
            try:
                t = await self._ex[name].fetch_ticker(self._ccxt_symbol(symbol))
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

    async def best_price(
        self,
        symbol: str,
        side: str,
        *,
        preferred_exchange: str | None = None,
        max_cross_spread_pct: float = 1.5,
    ) -> tuple[str, float]:
        """Sağlıklı borsalarda canlı BBO/fiyata bak, sembol çakışmasını ele, avantajlı olanı seç."""
        if preferred_exchange:
            pref_k = str(preferred_exchange).strip().lower()
            bbo_pref = self.get_fresh_bbo(pref_k, symbol, max_age_sec=15.0)
            if bbo_pref and self.is_exchange_healthy(pref_k):
                return pref_k, (bbo_pref[0] + bbo_pref[1]) / 2.0

        quotes: dict[str, float] = {}
        for name in self.get_failover_order(symbol=symbol):
            if not self.is_exchange_healthy(name) and quotes:
                continue
            bbo = self.get_fresh_bbo(name, symbol, max_age_sec=15.0)
            if bbo:
                quotes[name] = (bbo[0] + bbo[1]) / 2.0
                continue
            try:
                t = await self._ex[name].fetch_ticker(self._ccxt_symbol(symbol))
                px = float(t["last"])
                if px <= 0:
                    continue
                self.record_exchange_success(name)
                quotes[name] = px
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                continue
        if not quotes:
            raise RuntimeError(f"{symbol} için hiçbir borsadan fiyat alınamadı")

        # İki borsada aynı sembol adıyla farklı varlık işlem görüyorsa (ör. Binance BB=BounceBit
        # $0.0074 iken OKX BB=BlackBerry hissesi $8.93), birincil borsa fiyatından >%1.5 sapan
        # ikincil borsayı anında dışla ve sembol desteğinden çıkar.
        ref_ex = self.primary if self.primary in quotes else next(iter(quotes))
        ref_px = quotes[ref_ex]
        if len(quotes) > 1 and ref_px > 0 and max_cross_spread_pct > 0:
            valid_quotes: dict[str, float] = {ref_ex: ref_px}
            for ex_n, px_n in quotes.items():
                if ex_n == ref_ex:
                    continue
                base_min = max(min(ref_px, px_n), 1e-12)
                diff_pct = abs(px_n - ref_px) / base_min * 100.0
                if diff_pct <= max_cross_spread_pct:
                    valid_quotes[ex_n] = px_n
                else:
                    sym_ex = getattr(self, "symbol_exchanges", {})
                    supp = sym_ex.get(symbol)
                    if isinstance(supp, list) and ex_n in supp and len(supp) > 1:
                        supp.remove(ex_n)
            quotes = valid_quotes

        if str(side).strip().lower() in {"buy", "long"}:
            name = min(quotes, key=quotes.get)
        else:
            name = max(quotes, key=quotes.get)
        return name, quotes[name]

    async def fetch_funding(self, symbol: str, exchange: str | None = None) -> float | None:
        swap = self._ccxt_symbol(symbol)
        for name in self.get_failover_order(exchange, symbol=symbol):
            ex = self._ex[name]
            try:
                fr = await ex.fetch_funding_rate(swap)
                self.record_exchange_success(name)
                rate = fr.get("fundingRate")
                if rate is not None:
                    return float(rate)
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                continue
        return None

    async def fetch_open_interest(
        self, symbol: str, exchange: str | None = None
    ) -> float | None:
        swap = self._ccxt_symbol(symbol)
        for name in self.get_failover_order(exchange, symbol=symbol):
            ex = self._ex[name]
            try:
                oi = await ex.fetch_open_interest(swap)
                self.record_exchange_success(name)
                val = (
                    oi.get("openInterestValue")
                    or oi.get("openInterestAmount")
                    or (oi.get("info") or {}).get("openInterest")
                )
                if val is not None:
                    return float(val)
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                continue
        return None

    async def fetch_balance_usdt(self) -> float:
        if self.mode == "paper":
            return float(self.paper.balance)
        for name in self.get_failover_order():
            try:
                bal = await self._ex[name].fetch_balance()
                self.record_exchange_success(name)
                usdt = bal.get("USDT") or {}
                tot = usdt.get("total")
                if tot is None:
                    tot = (bal.get("total") or {}).get("USDT")
                if tot is not None:
                    return float(tot)
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                continue
        return 0.0

    async def fetch_open_positions(self, exchange: str | None = None) -> list[dict] | None:
        """Tüm borsalardaki açık vadeli pozisyonları döndürür.

        Mutabakatın eksik veriyle yerel pozisyon silmemesi için borsalardan biri
        okunamazsa ``None`` döner. ``exchange`` verilirse yalnızca o borsa okunur;
        kapama/mutabakat isteği sessizce başka borsaya yönlendirilmez.
        """
        if self.mode == "paper":
            return []
        names = [exchange] if exchange else list(self._ex)
        if any(name not in self._ex for name in names):
            return None
        out: list[dict] = []
        for name in names:
            try:
                raw = await self._ex[name].fetch_positions()
                self.record_exchange_success(name)
            except Exception as e:
                if is_timeout_or_network_error(e):
                    self.record_exchange_timeout(name, e)
                return None
            for position in raw:
                qty = abs(float(position.get("contracts") or 0)) * float(
                    position.get("contractSize") or 1
                )
                if qty <= 0:
                    continue
                out.append(
                    {
                        "symbol": position.get("symbol", ""),
                        "side": "LONG"
                        if str(position.get("side", "")).lower() == "long"
                        else "SHORT",
                        "qty": qty,
                        "exchange": name,
                    }
                )
        return out

    # -- emirler + Failover + Kayma (Slippage) Filtresi + Chase Order ----------
    async def market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        exchange: str | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict:
        """Tek borsada market emri gönderir.

        Canlı emir sonucu timeout nedeniyle belirsizse başka borsada yeniden
        denenmez; bu, aynı emrin iki kez açılmasını önler. ``client_order_id``
        borsa tarafında izlenebilirlik/idempotency için her emre eklenir.
        """
        if qty <= 0:
            raise ValueError("Emir miktarı sıfırdan büyük olmalı")
        target_ex = self.choose_symbol_exchange(symbol, exchange)
        if self.mode == "paper":
            if self.paper_realistic:
                bid, ask = await self.fetch_bid_ask(symbol, target_ex)
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (price_hint or 0.0)
                px = ask if side == "buy" else bid
                if self.dynamic_atr_slippage and px > 0:
                    vmeta = self.symbol_volatility_meta.get(symbol) or {}
                    atr_p = max(0.0, float(vmeta.get("atr_pct", 0.35)))
                    min_qv = max(10_000.0, float(vmeta.get("minute_qv_usdt", 250_000.0)))
                    notional = px * qty
                    dyn_extra_pct = atr_p * 0.03 + min(0.10, (notional / min_qv) * 0.25)
                    px = px * (1.0 + dyn_extra_pct / 100.0) if side == "buy" else px * (1.0 - dyn_extra_pct / 100.0)
                reference = price_hint or mid
                slippage_pct = abs(px - reference) / max(reference, 1e-12) * 100.0
                if target_ex in self.rest_data_stats:
                    self.rest_data_stats[target_ex]["paper_fills"] += 1
                return self.paper.market_order(
                    symbol,
                    side,
                    qty,
                    px,
                    exchange=target_ex,
                    slippage_pct=slippage_pct,
                    price_source="rest_bid_ask_atr_slippage" if self.dynamic_atr_slippage else "rest_bid_ask",
                    reduce_only=reduce_only,
                )
            px = price_hint or await self.fetch_price(symbol, target_ex)
            if target_ex in self.rest_data_stats:
                self.rest_data_stats[target_ex]["paper_fills"] += 1
            return self.paper.market_order(
                symbol, side, qty, px, exchange=target_ex, reduce_only=reduce_only
            )

        ex = self._ex[target_ex]
        order_id = client_order_id or self._new_client_order_id()
        params = self._client_order_params(target_ex, order_id)
        if reduce_only:
            params["reduceOnly"] = True
        try:
            order = await ex.create_market_order(
                self._ccxt_symbol(symbol), side, qty, params=params
            )
            self.record_exchange_success(target_ex)
        except Exception as e:
            if is_timeout_or_network_error(e):
                self.record_exchange_timeout(target_ex, e)
                raise RuntimeError(
                    f"Emir sonucu belirsiz; çift emir önlemek için tekrar denenmedi "
                    f"({target_ex}, clientOrderId={order_id}): {e}"
                ) from e
            raise

        filled = order.get("filled")
        average = order.get("average")
        cost = order.get("cost")
        if order.get("id") and (filled is None or (average is None and cost is None)):
            try:
                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
                order = {**order, **(fetched or {})}
                filled = order.get("filled")
                average = order.get("average")
                cost = order.get("cost")
            except Exception as exc:
                raise RuntimeError(
                    f"Emir dolgu miktarı/fiyatı doğrulanamadı (order={order.get('id')}): {exc}"
                ) from exc
        if filled is None:
            raise RuntimeError(
                f"Borsa gerçekleşen miktarı döndürmedi (order={order.get('id')}); istenen miktar dolgu sayılmadı"
            )
        filled = float(filled)
        if average is None and cost is not None and filled > 0:
            average = float(cost) / filled
        if average is None:
            raise RuntimeError(
                f"Borsa gerçekleşme fiyatını döndürmedi (order={order.get('id')})"
            )
        return {
            "symbol": symbol,
            "side": side,
            "qty": filled,
            "price": float(average),
            "fee": float((order.get("fee") or {}).get("cost") or 0.0),
            "id": order.get("id"),
            "client_order_id": order_id,
            "status": order.get("status"),
            "mode": self.mode,
            "exchange": target_ex,
            "emir_tipi": "market",
            "reduce_only": reduce_only,
        }

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
        ex_name = self.choose_symbol_exchange(symbol, exchange)
        if self.mode == "paper":
            if ex_name in self.rest_data_stats:
                self.rest_data_stats[ex_name]["paper_fills"] += 1
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
        filled_tot = 0.0
        cost_tot = 0.0
        last_oid = None

        for _ in range(max(1, steps)):
            rem = qty - filled_tot
            if rem <= qty * 0.001:
                break
            bid, ask = await self.fetch_bid_ask(symbol, ex_name)
            touch = ask if side == "buy" else bid
            limit_px = min(touch, cap_px) if side == "buy" else max(touch, cap_px)
            try:
                limit_px = float(ex.price_to_precision(self._ccxt_symbol(symbol), limit_px))
            except Exception:
                pass
            client_id = self._new_client_order_id()
            # Chase limit fiyatı takip eder ve gerektiğinde karşı tarafı geçer;
            # postOnly kullanmak dokunulan fiyatta emri gereksiz yere reddeder.
            params = self._client_order_params(ex_name, client_id)
            order = await ex.create_limit_order(
                self._ccxt_symbol(symbol), side, rem, limit_px, params=params
            )
            last_oid = order.get("id")
            await asyncio.sleep(0.8)
            try:
                status = await ex.fetch_order(last_oid, self._ccxt_symbol(symbol))
            except Exception as e:
                # Sonuç bilinmeden yeni emir/market fallback yapılmaz.
                raise RuntimeError(
                    f"Chase emrinin sonucu okunamadı (order={last_oid}): {e}"
                ) from e

            if status.get("status") == "open":
                await ex.cancel_order(last_oid, self._ccxt_symbol(symbol))
                # İptal sırasında gerçekleşen miktarı da yakala.
                status = await ex.fetch_order(last_oid, self._ccxt_symbol(symbol))

            step_filled = float(status.get("filled") or 0.0)
            if step_filled > 0:
                avg_step = float(status.get("average") or limit_px)
                filled_tot += step_filled
                cost_tot += step_filled * avg_step
            if (
                status.get("status")
                not in {"closed", "canceled", "cancelled", "rejected", "expired"}
                and step_filled < rem
            ):
                raise RuntimeError(
                    f"Chase emri hâlâ açık (order={last_oid}); yeni emir gönderilmedi"
                )

        if filled_tot <= 0:
            raise RuntimeError("Chase limit emir dolmadı; pozisyon açılmadı")
        return {
            "symbol": symbol,
            "side": side,
            "qty": filled_tot,
            "price": cost_tot / filled_tot,
            "id": last_oid,
            "status": "closed" if filled_tot >= qty * 0.999 else "partial",
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
        prefer_maker: bool = True,
        timeout: float = 4.0,
        exchange: str | None = None,
        expected_price: float | None = None,
        leverage: int | None = None,
        order_type: str | None = None,
    ) -> dict:
        """Pozisyon GİRİŞ emri (Failover + Maksimum Kayma Filtresi + Chase Order + Maker)."""
        if order_type is not None:
            prefer_maker = str(order_type).lower() != "market"
        ex_name = self.choose_symbol_exchange(symbol, exchange)
        await self.ensure_leverage(symbol, leverage or self.leverage, ex_name)

        if expected_price and expected_price > 0 and price_hint > 0:
            slip_pct = abs(price_hint - expected_price) / expected_price * 100.0
            if slip_pct > self.max_slippage_pct:
                return await self._chase_limit_order(
                    symbol, side, qty, expected_price, price_hint, ex_name
                )

        if not prefer_maker:
            return await self.market_order(symbol, side, qty, price_hint, ex_name)

        if self.mode == "paper":
            if not self.paper_realistic:
                px = price_hint or await self.fetch_price(symbol, ex_name)
                if ex_name in self.rest_data_stats:
                    self.rest_data_stats[ex_name]["paper_fills"] += 1
                return self.paper.maker_order(symbol, side, qty, px, exchange=ex_name)
            if self.smart_maker_execution:
                try:
                    bid, ask = await self.fetch_bid_ask(symbol, ex_name)
                except Exception:
                    bid, ask = (0.0, 0.0)
                if 0 < bid <= ask:
                    mid = (bid + ask) / 2.0
                    spread_pct = (ask - bid) / max(mid, 1e-12) * 100.0
                    if spread_pct <= self.max_maker_spread_pct:
                        passive_px = bid if side == "buy" else ask
                        q_sim = getattr(self, "maker_queue_sim", None)
                        if q_sim is not None:
                            vol_meta = getattr(self, "symbol_volatility_meta", {}).get(symbol) or {}
                            minute_qv = float(vol_meta.get("minute_qv_usdt") or 200_000.0)
                            resting = q_sim.register_order(
                                exchange=ex_name,
                                symbol=symbol,
                                side=side,
                                qty=qty,
                                bid=bid,
                                ask=ask,
                                timeout_sec=max(0.05, float(timeout)),
                                minute_qv_usdt=minute_qv,
                            )

                            async def _poll_resting_bbo() -> None:
                                """WebSocket ilk-40 dışında kalan dinamik terfi pariteleri için
                                bekleyen pasif Maker emrine gerçek zamanlı BBO + işlem şeridi akışı sağlar."""
                                import aiohttp as _aiohttp
                                seen_tids: set[str] = set()
                                created_ms = int(resting.created_ts * 1000)
                                base_coin = symbol.split("/")[0].upper()
                                async with _aiohttp.ClientSession() as _sess:
                                    while resting.status == "open":
                                        await asyncio.sleep(0.50)
                                        if resting.status != "open":
                                            break
                                        try:
                                            if ex_name == "binance":
                                                raw_sym = f"{base_coin}USDT"
                                                async with _sess.get(
                                                    f"https://www.binance.com/fapi/v1/ticker/bookTicker?symbol={raw_sym}",
                                                    timeout=2.5,
                                                ) as r_bbo:
                                                    if r_bbo.status == 200:
                                                        jb = await r_bbo.json()
                                                        lb = float(jb.get("bidPrice") or 0.0)
                                                        la = float(jb.get("askPrice") or 0.0)
                                                        if lb > 0 and la >= lb:
                                                            self.update_live_bbo("binance", symbol, lb, la)
                                                async with _sess.get(
                                                    f"https://www.binance.com/fapi/v1/aggTrades?symbol={raw_sym}&limit=25",
                                                    timeout=2.5,
                                                ) as r_tr:
                                                    if r_tr.status == 200:
                                                        for tr in await r_tr.json():
                                                            tid = str(tr.get("a"))
                                                            tms = int(tr.get("T") or 0)
                                                            if tms >= created_ms and tid not in seen_tids:
                                                                seen_tids.add(tid)
                                                                q_sim.on_trade(
                                                                    "binance",
                                                                    symbol,
                                                                    float(tr.get("p") or 0.0),
                                                                    float(tr.get("q") or 0.0),
                                                                    is_buyer_maker=bool(tr.get("m", False)),
                                                                )
                                            elif ex_name == "okx":
                                                inst_id = f"{base_coin}-USDT-SWAP"
                                                async with _sess.get(
                                                    f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}",
                                                    timeout=2.5,
                                                ) as r_bbo:
                                                    if r_bbo.status == 200:
                                                        rows = (await r_bbo.json()).get("data") or []
                                                        if rows:
                                                            lb = float(rows[0].get("bidPx") or 0.0)
                                                            la = float(rows[0].get("askPx") or 0.0)
                                                            if lb > 0 and la >= lb:
                                                                self.update_live_bbo("okx", symbol, lb, la)
                                                async with _sess.get(
                                                    f"https://www.okx.com/api/v5/market/trades?instId={inst_id}&limit=25",
                                                    timeout=2.5,
                                                ) as r_tr:
                                                    if r_tr.status == 200:
                                                        for tr in reversed((await r_tr.json()).get("data") or []):
                                                            tid = str(tr.get("tradeId"))
                                                            tms = int(tr.get("ts") or 0)
                                                            if tms >= created_ms and tid not in seen_tids:
                                                                seen_tids.add(tid)
                                                                q_sim.on_trade(
                                                                    "okx",
                                                                    symbol,
                                                                    float(tr.get("px") or 0.0),
                                                                    float(tr.get("sz") or 0.0),
                                                                    is_buyer_maker=(str(tr.get("side", "")).lower() == "sell"),
                                                                )
                                        except Exception:
                                            pass

                            bbo_task = (
                                asyncio.create_task(_poll_resting_bbo())
                                if float(timeout) >= 0.7 and symbol in getattr(self, "_live_bbo", {}).get(ex_name, {})
                                else None
                            )
                            try:
                                resolved = await q_sim.await_fill_or_expire(
                                    resting,
                                    current_mid_fn=lambda: (
                                        sum(self.get_fresh_bbo(ex_name, symbol, max_age_sec=20.0) or (mid, mid)) / 2.0
                                    ),
                                )
                            finally:
                                if bbo_task is not None and not bbo_task.done():
                                    bbo_task.cancel()
                            if resolved.filled_qty <= 0 or resolved.limit_price <= 0:
                                return {
                                    "symbol": symbol,
                                    "side": side,
                                    "qty": 0.0,
                                    "price": 0.0,
                                    "fee": 0.0,
                                    "status": resolved.status,
                                    "mode": "paper",
                                    "exchange": ex_name,
                                    "emir_tipi": f"maker_{resolved.status}",
                                    "queue_ahead_qty": round(resolved.queue_ahead_qty, 6),
                                }
                            if ex_name in self.rest_data_stats:
                                self.rest_data_stats[ex_name]["paper_fills"] += 1
                            return self.paper._fill(
                                symbol,
                                side,
                                resolved.filled_qty,
                                resolved.limit_price,
                                self.paper.fee_maker_pct,
                                f"maker_{resolved.fill_reason or 'queue_fill'}",
                                slippage_pct=0.0,
                                exchange=ex_name,
                            )
                        if ex_name in self.rest_data_stats:
                            self.rest_data_stats[ex_name]["paper_fills"] += 1
                        return self.paper._fill(
                            symbol,
                            side,
                            qty,
                            passive_px,
                            self.paper.fee_maker_pct,
                            "maker_post_only",
                            slippage_pct=0.0,
                            exchange=ex_name,
                        )
                    elif getattr(self, "maker_queue_sim", None) is not None:
                        # Geniş makas varken sessizce market emrine düşmek yerine post-only reddi döndür
                        return {
                            "symbol": symbol,
                            "side": side,
                            "qty": 0.0,
                            "price": 0.0,
                            "fee": 0.0,
                            "status": "wide_spread_skipped",
                            "mode": "paper",
                            "exchange": ex_name,
                            "emir_tipi": "maker_wide_spread_skipped",
                        }
            return await self.market_order(symbol, side, qty, price_hint, ex_name)

        ex = self._ex[ex_name]
        bid, ask = await self.fetch_bid_ask(symbol, ex_name)
        base = price_hint or (ask if side == "buy" else bid)
        ref_exp = expected_price or base
        slip_pct = abs(base - ref_exp) / max(ref_exp, 1e-12) * 100.0
        if slip_pct > self.max_slippage_pct:
            return await self._chase_limit_order(symbol, side, qty, ref_exp, base, ex_name)

        tick = max(base * 0.0001, 1e-8)
        raw_px = (ask - tick) if side == "buy" else (bid + tick)
        try:
            limit_px = float(ex.price_to_precision(self._ccxt_symbol(symbol), raw_px))
        except Exception:
            limit_px = raw_px
        client_id = self._new_client_order_id()
        params = {
            "postOnly": True,
            **self._client_order_params(ex_name, client_id),
        }
        try:
            order = await ex.create_limit_order(
                self._ccxt_symbol(symbol), side, qty, limit_px, params=params
            )
            self.record_exchange_success(ex_name)
        except Exception as e:
            if is_timeout_or_network_error(e):
                self.record_exchange_timeout(ex_name, e)
            # Emir gönderilmiş olabilir. Otomatik market fallback burada çift
            # pozisyon açabileceği için sonuç netleşmeden başka emir yok.
            raise RuntimeError(
                f"Maker emir kurulamadı veya sonucu belirsiz (clientOrderId={client_id}): {e}"
            ) from e

        oid = order.get("id")
        filled = float(order.get("filled") or 0.0)
        avg_px = float(order.get("average") or limit_px)
        status = order
        deadline = time.time() + timeout
        while time.time() < deadline and filled < qty * 0.999:
            await asyncio.sleep(0.4)
            status = await ex.fetch_order(oid, self._ccxt_symbol(symbol))
            filled = float(status.get("filled") or 0.0)
            if status.get("average"):
                avg_px = float(status["average"])
            if status.get("status") in {"closed", "canceled", "cancelled", "rejected", "expired"}:
                break

        if filled < qty * 0.999 and status.get("status") == "open":
            # İptal başarısızsa kalan için market/chase emri GÖNDERİLMEZ.
            await ex.cancel_order(oid, self._ccxt_symbol(symbol))
            status = await ex.fetch_order(oid, self._ccxt_symbol(symbol))
            filled = float(status.get("filled") or 0.0)
            if status.get("average"):
                avg_px = float(status["average"])

        if filled >= qty * 0.999:
            return {
                "symbol": symbol,
                "side": side,
                "qty": filled,
                "price": avg_px,
                "id": oid,
                "client_order_id": client_id,
                "mode": self.mode,
                "exchange": ex_name,
                "emir_tipi": "maker",
            }

        if status.get("status") not in {"closed", "canceled", "cancelled", "rejected", "expired"}:
            raise RuntimeError(
                f"Maker emri hâlâ açık (order={oid}); kalan miktar için yeni emir gönderilmedi"
            )

        remainder = max(0.0, qty - filled)
        if remainder <= 0:
            raise RuntimeError("Maker emir dolmadı")

        cur_bid, cur_ask = await self.fetch_bid_ask(symbol, ex_name)
        cur_px = cur_ask if side == "buy" else cur_bid
        rem_slip = abs(cur_px - ref_exp) / max(ref_exp, 1e-12) * 100.0
        if rem_slip > self.max_slippage_pct:
            other = await self._chase_limit_order(
                symbol, side, remainder, ref_exp, cur_px, ex_name
            )
            kind_lbl = "maker+chase-limit"
        else:
            other = await self.market_order(symbol, side, remainder, cur_px, ex_name)
            kind_lbl = "maker+kalan-market"

        other_qty = float(other.get("qty") or 0.0)
        other_px = float(other.get("price") or cur_px)
        total_filled = filled + other_qty
        if total_filled <= 0:
            raise RuntimeError("Giriş emri dolmadı")
        avg_px = (filled * avg_px + other_qty * other_px) / total_filled
        return {
            "symbol": symbol,
            "side": side,
            "qty": total_filled,
            "price": avg_px,
            "id": oid,
            "client_order_id": client_id,
            "mode": self.mode,
            "exchange": ex_name,
            "emir_tipi": kind_lbl,
            "maker_dolum": round(filled / qty * 100, 1),
        }

    async def execute_exit(
        self,
        symbol: str,
        side: str,
        qty: float,
        price_hint: float = 0.0,
        reason: str = "",
        exchange: str | None = None,
        reduce_only: bool = True,
    ) -> dict:
        """v9.0 Komisyon-Optimize Çıkış Yöneticisi:
        • Acil koruma çıkışları (STOP LOSS, ZAMAN ÇÜRÜMESİ, SİGORTA, TEST SONU): %0.05 Taker Market
        • Kâr alma / Kâr kilidi çıkışları (KÂR KİLİDİ, KAR AL, TP): Dar makasta %0.02 Reduce-Only Maker!
        """
        ex_name = self.choose_symbol_exchange(symbol, exchange)
        r_up = str(reason or "").upper()
        is_profit_take = any(
            kw in r_up
            for kw in ("KÂR KİLİDİ", "KAR KILIDI", "KAR AL", "TP", "HEDEF", "ÇAPRAZ KURTARMA")
        ) and not any(kw in r_up for kw in ("ZARAR", "SİGORTA", "TEST SONU", "TASFİYE", "ÇÜRÜME"))

        if self.smart_maker_execution and is_profit_take and self.mode == "paper":
            if self.paper_realistic:
                try:
                    bid, ask = await self.fetch_bid_ask(symbol, ex_name)
                except Exception:
                    bid, ask = (0.0, 0.0)
                if 0 < bid <= ask:
                    mid = (bid + ask) / 2.0
                    spread_pct = (ask - bid) / max(mid, 1e-12) * 100.0
                    if spread_pct <= self.max_maker_spread_pct:
                        passive_px = bid if side == "buy" else ask
                        if ex_name in self.rest_data_stats:
                            self.rest_data_stats[ex_name]["paper_fills"] += 1
                        res = self.paper._fill(
                            symbol,
                            side,
                            qty,
                            passive_px,
                            self.paper.fee_maker_pct,
                            "maker_reduce_only",
                            slippage_pct=0.0,
                            exchange=ex_name,
                            reduce_only=reduce_only,
                        )
                        res["reduce_only"] = reduce_only
                        return res

        return await self.market_order(
            symbol, side, qty, price_hint=price_hint, exchange=ex_name, reduce_only=reduce_only
        )

    # -- borsa koruması (native stop / OCO) --------------------------------------
    async def place_protection(
        self,
        symbol: str,
        pos_side: str,
        qty: float,
        stop_price: float,
        tp_price: float | None = None,
        exchange: str | None = None,
    ) -> dict:
        ex_name = self.choose_symbol_exchange(symbol, exchange)
        if self.mode == "paper":
            prot = {
                "native": True,
                "tur": "paper-oco" if tp_price else "paper-stop",
                "stop": stop_price,
                "tp": tp_price,
                "exchange": ex_name,
                "ids": [f"paper-{int(time.time() * 1000)}"],
            }
            self.paper.protections[symbol] = prot
            return prot

        ex = self._ex[ex_name]
        trig_side = "sell" if str(pos_side).upper() == "LONG" else "buy"

        def _px(v: float) -> float:
            try:
                return float(ex.price_to_precision(self._ccxt_symbol(symbol), v))
            except Exception:
                return v

        def _amt(v: float):
            try:
                return ex.amount_to_precision(self._ccxt_symbol(symbol), v)
            except Exception:
                return v

        sl_px = _px(stop_price)
        if ":" in symbol or self.leverage > 1:
            try:
                sl_o = await ex.create_order(
                    self._ccxt_symbol(symbol),
                    "STOP_MARKET",
                    trig_side,
                    _amt(qty),
                    None,
                    {"stopPrice": sl_px, "reduceOnly": True},
                )
                ids = [sl_o.get("id")]
                if tp_price:
                    tp_o = await ex.create_order(
                        self._ccxt_symbol(symbol),
                        "TAKE_PROFIT_MARKET",
                        trig_side,
                        _amt(qty),
                        None,
                        {"stopPrice": _px(tp_price), "reduceOnly": True},
                    )
                    ids.append(tp_o.get("id"))
                return {
                    "native": True,
                    "tur": "futures-stop+tp" if tp_price else "futures-stop",
                    "stop": sl_px,
                    "tp": tp_price,
                    "exchange": ex_name,
                    "ids": ids,
                }
            except Exception:
                pass

        attempts = [
            ("stop_loss_limit", sl_px, {"stopPrice": sl_px, "reduceOnly": True}),
            ("limit", sl_px, {"triggerPrice": sl_px, "reduceOnly": True}),
        ]
        for typ, px, params in attempts:
            try:
                o = await ex.create_order(
                    self._ccxt_symbol(symbol), typ, trig_side, _amt(qty), px, params
                )
                return {
                    "native": True,
                    "tur": typ,
                    "stop": sl_px,
                    "tp": tp_price,
                    "exchange": ex_name,
                    "ids": [o.get("id")],
                }
            except Exception:
                continue

        return {
            "native": False,
            "tur": "yazilim-stop",
            "stop": sl_px,
            "tp": tp_price,
            "exchange": ex_name,
            "ids": [],
        }

    async def cancel_protection(self, symbol: str, prot: dict | None) -> bool:
        if self.mode == "paper":
            self.paper.protections.pop(symbol, None)
            return True
        if not prot or not prot.get("native"):
            return True
        ex_name = prot.get("exchange") or self.choose_symbol_exchange(symbol)
        ex = self._ex.get(ex_name)
        if not ex:
            return False
        for oid in prot.get("ids", []) or []:
            if oid:
                try:
                    await ex.cancel_order(oid, self._ccxt_symbol(symbol))
                except Exception:
                    pass
        return True

    async def replace_protection(
        self,
        symbol: str,
        pos_side: str,
        qty: float,
        stop_price: float,
        old_prot: dict | None = None,
        exchange: str | float | None = None,
        tp_price: float | None = None,
    ) -> dict:
        if isinstance(exchange, (int, float)):
            tp_price = float(exchange)
            ex_arg = None
        else:
            ex_arg = exchange
        await self.cancel_protection(symbol, old_prot)
        ex_name = ex_arg or (old_prot or {}).get("exchange")
        return await self.place_protection(
            symbol, pos_side, qty, stop_price, tp_price=tp_price, exchange=ex_name
        )

    async def close(self) -> None:
        for ex in self._ex.values():
            try:
                await ex.close()
            except Exception:
                pass
