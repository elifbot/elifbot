"""CLI runner. The --paper flag is mandatory; live trading is not implemented."""

from __future__ import annotations

import argparse
import asyncio
import logging
from math import isfinite
import time
from collections.abc import Sequence

from app.executor import Executor
from core.indicators import atr
from core.risk import MIN_24H_VOLUME, VOLUME_SPIKE_MULTIPLIER
from core.symbols import base_asset, is_blacklisted
from core.strategy import Signal
from core.volume_spike import VolumeSpike, VolumeSpikeDetector
from infra.exchanges.binance import BinancePublic
from infra.exchanges.base import (
    Market,
    PublicExchange,
    PublicMarketDataError,
    Ticker,
)
from infra.exchanges.okx import OKXPublic
from infra.market_data.models import Candle
from infra.paper import PaperBroker
from safety.alerts import AlertManager
from state.store import StateStore


_TIMEFRAME_MS = {"5m": 5 * 60_000}
_SCAN_LIMIT = 100
_DEFAULT_REQUEST_DELAY_SECONDS = 0.1
_MAX_SPIKES_PER_BATCH = 30
_MAX_TICKER_AGE_MS = 15_000
_EXCHANGES = {
    "binance": BinancePublic,
    "okx": OKXPublic,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Public-data paper trading bot")
    parser.add_argument("--paper", action="store_true", required=True,
                        help="required confirmation: simulated orders only")
    parser.add_argument(
        "--exchange",
        choices=("binance", "okx", "all", "binance+okx"),
        default="binance",
    )
    parser.add_argument("--symbols", default="BTCUSDT",
                        help="comma-separated symbols, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--state", default="paper_state.sqlite3")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="volume-spike candidate batch interval in seconds")
    parser.add_argument(
        "--request-delay",
        type=float,
        default=_DEFAULT_REQUEST_DELAY_SECONDS,
        help="delay between spike OHLCV requests in seconds (default: 0.1)",
    )
    parser.add_argument("--once", action="store_true", help="run one data cycle and exit")
    return parser


def _closed_candles(exchange: object, symbol: str, timeframe: str, limit: int = 300):
    candles = exchange.fetch_candles(symbol, timeframe, limit)
    cutoff = int(time.time() * 1000) - _TIMEFRAME_MS[timeframe]
    closed = [candle for candle in candles if candle.timestamp <= cutoff]
    if not closed:
        raise PublicMarketDataError(f"No closed {timeframe} candles available for {symbol}")
    return closed


def _closed_and_current_candles(
    exchange: PublicExchange, symbol: str, timeframe: str, limit: int = 300
) -> tuple[list[Candle], Candle | None]:
    candles = exchange.fetch_candles(symbol, timeframe, limit)
    cutoff = int(time.time() * 1000) - _TIMEFRAME_MS[timeframe]
    closed = [candle for candle in candles if candle.timestamp <= cutoff]
    if not closed:
        raise PublicMarketDataError(f"No closed {timeframe} candles available for {symbol}")
    current = next(
        (candle for candle in reversed(candles) if candle.timestamp > cutoff),
        None,
    )
    return closed, current


def _selected_exchanges(value: str) -> list[str]:
    if value in {"all", "binance+okx"}:
        return ["binance", "okx"]
    return [value]


def _rejection_label(signal: Signal) -> str:
    labels = {
        "MAX_POSITIONS_REACHED": "limit_dolu",
        "INSUFFICIENT_FUNDS": "marj_yetersiz",
        "conflict": "sinyal_cakismasi",
        "POSITION_ALREADY_OPEN": "pozisyon_acik",
        "INVALID_SIGNAL": "gecersiz_sinyal",
        "dusuk_momentum": "dusuk_momentum",
        "dusuk_hacim": "dusuk_hacim",
        "TREND_WARMUP": "trend_isinma",
        "TREND_NOT_CONFIRMED": "trend_onayi_yok",
        "FADE_PATTERN_NOT_MET": "strateji_kosulu_yok",
    }
    if signal.rejection_code:
        return labels.get(signal.rejection_code, signal.rejection_code)
    if signal.side == "HOLD":
        return "sinyal_yok"
    return "yok"


def _select_markets(
    exchange: PublicExchange, symbols_option: str
) -> list[Market]:
    if symbols_option.strip().upper() == "ALL":
        # Fetch a broad ranked slice, remove every excluded base, then cap the
        # actual poll pool so blacklisted high-volume contracts do not waste slots.
        markets = exchange.fetch_top_usdt_futures(1000)
    else:
        requested = [
            item.strip().upper()
            for item in symbols_option.split(",")
            if item.strip()
        ][: _SCAN_LIMIT]
        markets_by_symbol = {
            market.symbol.upper(): market
            for market in exchange.fetch_top_usdt_futures(10_000)
        }
        markets_by_base: dict[str, Market] = {}
        for market in markets_by_symbol.values():
            markets_by_base.setdefault(market.base_asset.upper(), market)
        markets = [
            markets_by_symbol.get(symbol)
            or markets_by_base.get(base_asset(symbol))
            or Market(symbol, "", 0.0, "requested")
            for symbol in requested
        ]
        missing_tick = [
            market.symbol for market in markets if market.tick_size <= 0
        ]
        if missing_tick:
            raise PublicMarketDataError(
                "Tick size unavailable for requested markets: "
                + ", ".join(missing_tick)
            )
    eligible = [
        market for market in markets
        if not is_blacklisted(market.symbol)
        and (not market.base_asset or not is_blacklisted(market.base_asset))
    ]
    if symbols_option.strip().upper() == "ALL":
        eligible.sort(
            key=lambda market: (
                market.quote_volume_24h,
                abs(market.percentage_24h),
            ),
            reverse=True,
        )
    return eligible[:_SCAN_LIMIT]


def run(args: argparse.Namespace) -> int:
    if args.once:
        return _run_polling(args)
    return asyncio.run(_run_realtime(args))


def _run_polling(args: argparse.Namespace) -> int:
    if not args.paper:
        raise ValueError("only --paper mode is available")
    if (
        not isfinite(args.balance) or not isfinite(args.interval)
        or args.balance <= 0 or args.interval <= 0
    ):
        raise ValueError("balance and interval must be positive")
    request_delay = getattr(
        args, "request_delay", _DEFAULT_REQUEST_DELAY_SECONDS
    )
    if not isfinite(request_delay) or request_delay < 0:
        raise ValueError("request delay must be finite and non-negative")
    if not args.symbols.strip():
        raise ValueError("at least one symbol is required")
    exchange_names = _selected_exchanges(args.exchange)
    exchanges = {name: _EXCHANGES[name]() for name in exchange_names}
    alerts = AlertManager()
    with StateStore(args.state) as store:
        broker = PaperBroker(args.balance)
        executor = Executor(broker, store=store)
        market_pools: dict[str, list[Market]] = {}
        for name, exchange in exchanges.items():
            try:
                market_pools[name] = _select_markets(exchange, args.symbols)
                print(f"{name}: {len(market_pools[name])} markets in paper scan pool")
            except Exception as exc:
                alerts.notify(f"{name} futures universe unavailable: {exc}", "error")
                market_pools[name] = []
        if not any(market_pools.values()):
            alerts.notify("No exchange has an available market scan pool; fail-closed.", "critical")
            return 1
        print(
            f"Paper mode | {', '.join(exchange_names)} public Futures data | "
            f"balance={broker.portfolio.balance:.2f} USDT"
        )
        for name, exchange in exchanges.items():
            for market in market_pools[name]:
                position_key = f"{name}:{market.symbol}"
                try:
                    five_minute = _closed_candles(exchange, market.symbol, "5m")
                    reference_ticker = None
                    if position_key in broker.portfolio.positions:
                        reference_ticker = exchange.fetch_ticker(market.symbol)
                    previous_trade_count = len(broker.trades)
                    signal = executor.process(
                        position_key, five_minute,
                        tick_size=market.tick_size,
                        reference_ticker=reference_ticker,
                    )
                    if (
                        len(broker.trades) > previous_trade_count
                        and broker.trades[-1].get("type") == "OPEN"
                        and broker.trades[-1].get("symbol") == position_key
                    ):
                        trade = broker.trades[-1]
                        print(
                            "PAPER ORDER AÇILDI: "
                            f"[{market.symbol}] [{trade['side']}] "
                            f"[{float(trade['price']):.8f}]"
                        )
                    print(
                        f"{position_key}: {signal.side} [{signal.motor}] "
                        f"impulse={signal.impulse_pct:.3f}% rvol={signal.rvol:.2f}; "
                        f"rejection={_rejection_label(signal)}; "
                        f"equity={broker.mark_to_market({position_key: five_minute[-1].close}):.2f} USDT"
                    )
                except Exception as exc:
                    alerts.notify(f"{name} market-data/processing error: {exc}", "error")
                time.sleep(request_delay)
    return 0


def _realtime_markets(
    exchange: PublicExchange, symbols_option: str
) -> list[Market]:
    if symbols_option.strip().upper() != "ALL":
        markets = _select_markets(exchange, symbols_option)
    else:
        markets = exchange.fetch_top_usdt_futures(10_000)
    return [
        market for market in markets
        if not is_blacklisted(market.symbol)
        and not is_blacklisted(market.base_asset)
    ]


async def _stream_exchange_tickers(
    name: str,
    exchange: PublicExchange,
    markets: dict[str, Market],
    detector: VolumeSpikeDetector,
    executor: Executor,
    queue: asyncio.Queue[tuple[str, VolumeSpike]],
    alerts: AlertManager,
) -> None:
    symbols = tuple(markets)
    backoff = 1.0
    while True:
        try:
            async for ticker in exchange.stream_tickers(symbols):
                market = markets.get(ticker.symbol.upper())
                if market is None:
                    continue
                position_key = f"{name}:{market.symbol}"
                executor.process_tick(
                    position_key, ticker.last_price, ticker.timestamp_ms,
                    ticker_symbol=ticker.symbol,
                )
                spike = detector.update(ticker)
                if spike is None:
                    continue
                print(
                    "TÜM PİYASA TARAMASI: HACİM PATLAMASI - "
                    f"[{spike.symbol}] - Anlık Hacim: {spike.quote_volume:.2f} USDT"
                )
                if spike.direction is None:
                    print(
                        f"{position_key}: rejection=yonsuz_hacim "
                        f"(spike={spike.multiplier:.2f}x)"
                    )
                    continue
                print(
                    "HACİM PATLAMASI TESPİT EDİLDİ: "
                    f"[{spike.symbol}] Hacim: {spike.multiplier:.2f} katı, "
                    f"Yön: {spike.direction}"
                )
                await queue.put((name, spike))
            backoff = 1.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            alerts.notify(f"{name} ticker stream error: {exc}", "error")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)


async def _process_spike_batch(
    batch: list[tuple[str, VolumeSpike]],
    exchanges: dict[str, PublicExchange],
    markets: dict[str, dict[str, Market]],
    executor: Executor,
    request_delay: float,
) -> None:
    unique: dict[tuple[str, str], VolumeSpike] = {}
    for name, spike in batch:
        key = (name, spike.symbol)
        if key not in unique or spike.multiplier > unique[key].multiplier:
            unique[key] = spike
    ranked = sorted(unique.items(), key=lambda item: item[1].multiplier, reverse=True)
    candidates = [
        item for item in ranked
        if f"{item[0][0]}:{item[0][1]}" not in executor.broker.portfolio.positions
    ][:_MAX_SPIKES_PER_BATCH]
    semaphores = {name: asyncio.Semaphore(5) for name in exchanges}

    async def fetch_candles(name: str, symbol: str) -> list:
        async with semaphores[name]:
            candles = await asyncio.to_thread(
                _closed_candles, exchanges[name], symbol, "5m", 100
            )
            await asyncio.sleep(request_delay)
            return candles

    candle_results = await asyncio.gather(
        *(
            fetch_candles(name, spike.symbol)
            for (name, _), spike in candidates
        ),
        return_exceptions=True,
    )
    for ((name, symbol), spike), result in zip(candidates, candle_results):
        position_key = f"{name}:{symbol}"
        if isinstance(result, BaseException):
            logging.getLogger(__name__).error(
                "Could not fetch OHLCV for spike %s: %s", position_key, result
            )
            continue
        candles = result
        market = markets[name][symbol]
        try:
            average_range = atr(
                [item.high for item in candles],
                [item.low for item in candles],
                [item.close for item in candles],
            )[-1]
            if average_range is None:
                continue
            stop_fraction = max(0.001, 2.5 * average_range / spike.price)
            signal = Signal(
                spike.direction or "HOLD",
                spike.impulse_percent,
                spike.multiplier,
                stop_fraction,
                "volume_spike",
            )
            previous_close = candles[-1].close
            signal_candles = [
                *candles,
                Candle(
                    max(spike.timestamp_ms, candles[-1].timestamp + 1),
                    previous_close,
                    max(previous_close, spike.price),
                    min(previous_close, spike.price),
                    spike.price,
                    0.0,
                ),
            ]
            previous_trade_count = len(executor.broker.trades)
            decision = executor.process(
                position_key,
                signal_candles,
                tick_size=market.tick_size,
                signal_override=signal,
                market_price=spike.price,
            )
            if (
                len(executor.broker.trades) > previous_trade_count
                and executor.broker.trades[-1].get("type") == "OPEN"
                and executor.broker.trades[-1].get("symbol") == position_key
            ):
                trade = executor.broker.trades[-1]
                print(
                    "PAPER ORDER AÇILDI: "
                    f"[{symbol}] [{trade['side']}] "
                    f"[{float(trade['price']):.8f}]"
                )
            elif decision.side == "HOLD":
                print(
                    f"{position_key}: rejection={_rejection_label(decision)}"
                )
        except Exception as exc:
            logging.getLogger(__name__).exception(
                "Could not process volume spike for %s: %s", position_key, exc
            )


async def _monitor_open_positions(
    exchanges: dict[str, PublicExchange],
    markets: dict[str, dict[str, Market]],
    executor: Executor,
    request_delay: float,
) -> None:
    last_processed_candle: dict[str, int] = {}
    while True:
        for position_key in list(executor.broker.portfolio.positions):
            name, separator, symbol = position_key.partition(":")
            if not separator or name not in exchanges or symbol not in markets[name]:
                continue
            position = executor.broker.portfolio.positions.get(position_key)
            if position is None:
                continue
            try:
                candles, current_candle = await asyncio.to_thread(
                    _closed_and_current_candles,
                    exchanges[name], symbol, "5m", 100,
                )
                reference_ticker = executor.latest_ticker(position_key)
                if reference_ticker is None:
                    continue
                if (
                    abs(int(time.time() * 1000) - reference_ticker.timestamp_ms)
                    > _MAX_TICKER_AGE_MS
                ):
                    logging.getLogger(__name__).warning(
                        "HATALI FİYAT VERİSİ REDDEDİLDİ: [%s] "
                        "ticker is stale",
                        position_key,
                    )
                    continue
                latest = candles[-1]
                if (
                    latest.timestamp <= position.opened_at
                    or latest.timestamp <= last_processed_candle.get(position_key, -1)
                ):
                    continue
                last_processed_candle[position_key] = latest.timestamp
                before = len(executor.broker.trades)
                executor.manage_position(
                    position_key,
                    candles,
                    reference_ticker=reference_ticker,
                    verification_candle=current_candle,
                )
                if (
                    len(executor.broker.trades) > before
                    and executor.broker.trades[-1].get("type") == "CLOSE"
                ):
                    trade = executor.broker.trades[-1]
                    print(
                        f"PAPER ORDER KAPANDI: [{symbol}] "
                        f"[{trade['reason']}] "
                        f"[PnL={float(trade['pnl']):.2f} USDT]"
                    )
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "Could not refresh open position %s: %s", position_key, exc
                )
            await asyncio.sleep(request_delay)
        await asyncio.sleep(1.0)


async def _run_realtime(args: argparse.Namespace) -> int:
    if not args.paper:
        raise ValueError("only --paper mode is available")
    if (
        not isfinite(args.balance) or args.balance <= 0
        or not isfinite(args.interval) or args.interval <= 0
    ):
        raise ValueError("balance and interval must be positive")
    request_delay = getattr(args, "request_delay", _DEFAULT_REQUEST_DELAY_SECONDS)
    if not isfinite(request_delay) or request_delay < 0:
        raise ValueError("request delay must be finite and non-negative")
    if not args.symbols.strip():
        raise ValueError("at least one symbol is required")
    exchange_names = _selected_exchanges(args.exchange)
    exchanges = {name: _EXCHANGES[name]() for name in exchange_names}
    alerts = AlertManager()
    with StateStore(args.state) as store:
        broker = PaperBroker(args.balance)
        executor = Executor(broker, store=store)
        markets: dict[str, dict[str, Market]] = {}
        for name, exchange in exchanges.items():
            try:
                listed = await asyncio.to_thread(
                    _realtime_markets, exchange, args.symbols
                )
                markets[name] = {market.symbol.upper(): market for market in listed}
                print(
                    f"{name}: {len(markets[name])} futures markets monitored "
                    f"(24h volume >= {MIN_24H_VOLUME:.0f} USDT)"
                )
            except Exception as exc:
                alerts.notify(f"{name} futures universe unavailable: {exc}", "error")
                markets[name] = {}
        if not any(markets.values()):
            alerts.notify(
                "No exchange has an available real-time market universe; fail-closed.",
                "critical",
            )
            return 1

        print(
            f"Paper mode | real-time public Futures streams | "
            f"volume spike={VOLUME_SPIKE_MULTIPLIER:.1f}x | "
            f"balance={broker.portfolio.balance:.2f} USDT"
        )
        queue: asyncio.Queue[tuple[str, VolumeSpike]] = asyncio.Queue()
        tasks = [
            asyncio.create_task(
                _stream_exchange_tickers(
                    name,
                    exchange,
                    markets[name],
                    VolumeSpikeDetector(),
                    executor,
                    queue,
                    alerts,
                ),
                name=f"{name}-ticker-stream",
            )
            for name, exchange in exchanges.items()
            if markets[name]
        ]
        tasks.append(
            asyncio.create_task(
                _monitor_open_positions(
                    exchanges, markets, executor, request_delay
                ),
                name="open-position-monitor",
            )
        )
        try:
            while True:
                first = await queue.get()
                batch = [first]
                deadline = asyncio.get_running_loop().time() + args.interval
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        batch.append(await asyncio.wait_for(queue.get(), remaining))
                    except asyncio.TimeoutError:
                        break
                await _process_spike_batch(
                    batch, exchanges, markets, executor, request_delay
                )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Stopped; paper state was saved.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
