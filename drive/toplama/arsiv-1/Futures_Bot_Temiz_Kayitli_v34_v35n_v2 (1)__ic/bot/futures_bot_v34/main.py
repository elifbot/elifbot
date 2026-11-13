#!/usr/bin/env python3
"""
main.py — PAPER vadeli işlem araştırma botu — CLI ve oturum döngüsü.

MOD: yalnızca `paper` ve `replay` desteklenir.
`--mode live` veya `--mode testnet` -> hata mesajı + sys.exit(1)
(hiçbir API çağrısı yapılmadan).

Gerçek emir gönderilmez, kimlik doğrulamalı uç nokta kullanılmaz,
API anahtarı okunmaz.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

import config
from data.binance_futures_feed import BinanceFuturesFeed
from data.binance_futures_feed import FeedAccessError as BinanceAccessError
from data.binance_futures_feed import FeedError as BinanceFeedError
from data.feed_utils import check_candle_gaps, filter_closed_candles
from data.okx_swap_feed import FeedAccessError as OkxAccessError
from data.okx_swap_feed import FeedError as OkxFeedError
from data.okx_swap_feed import OkxSwapFeed
from indicators.catalog import render_catalog_text
from logger.trade_logger import TradeLogger
from portfolio.paper_futures import PaperPortfolio, verify_pnl_formulas
from reports.pnl_report import PnLReport, render_table
from scanner.spike import ANI_DUSUS, ANI_YUKSELIS, NORMAL, compute_spike, rank_spikes
from scanner.universe import (
    build_universe,
    filter_by_symbols,
    normalize_binance_tickers,
    normalize_okx_tickers,
    rejection_report,
)
from strategies import build_candidates
from strategies.base import HOLD
from strategies.composite import composite_signal

log = logging.getLogger("futures_bot")

# ASSUMPTION: işlem başına marj = başlangıç bakiyesinin %10'u (100 USDT).
MARGIN_PER_TRADE = config.STARTING_BALANCE_USDT * 0.10
# ASSUMPTION: ATR tabanlı stop/hedef çarpanları kalibre edilmemiştir.
STOP_ATR_MULT = 2.0
TAKE_PROFIT_ATR_MULT = 4.0

_BANNER = """
============================================================
 PAPER-ONLY FUTURES RESEARCH BOT — GERÇEK EMİR GÖNDERİLMEZ
 Public veri • API anahtarı yok • Yalnızca simülasyon
============================================================
"""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def guard_mode(mode: str) -> None:
    """live/testnet modlarını herhangi bir ağ çağrısından ÖNCE reddeder."""
    if mode in config.REJECTED_MODES:
        print(
            f"HATA: '{mode}' modu desteklenmiyor. Bu proje PAPER-ONLY'dir ve "
            "gerçek emir göndermez.\n"
            "Kullanılabilir modlar: paper, replay",
            file=sys.stderr,
        )
        sys.exit(1)
    if mode not in config.SUPPORTED_MODES:
        print(f"HATA: bilinmeyen mod: {mode}", file=sys.stderr)
        sys.exit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Paper-only çok göstergeli vadeli işlem araştırma botu."
    )
    p.add_argument("--mode", default="paper", help="paper | replay (live reddedilir)")
    p.add_argument("--duration-min", type=int, default=config.SESSION_DURATION_MIN)
    p.add_argument(
        "--pairs",
        default="",
        help="Virgülle ayrılmış 'borsa:sembol' listesi (boşsa config kullanılır)",
    )
    p.add_argument("--replay-csv", default="", help="replay modu için CSV yolu")
    p.add_argument("--log-path", default=config.TRADE_LOG_PATH)
    p.add_argument("--report-path", default=config.REPORT_PATH)
    p.add_argument("--show-catalog", action="store_true", help="gösterge envanterini yaz")
    p.add_argument(
        "--scan",
        action="store_true",
        help="Hacim odaklı tarama: alfabetik DEĞİL, 24s USD hacme göre sırala ve "
        "ani hacim/fiyat hareketi olan sembolleri seç",
    )
    p.add_argument("--scan-universe", type=int, default=config.SCAN_UNIVERSE_LIMIT)
    p.add_argument("--scan-fetch", type=int, default=config.SCAN_FETCH_TOP,
                   help="Mum verisi çekilecek en fazla sembol")
    p.add_argument("--scan-pick", type=int, default=config.SCAN_PICK_TOP,
                   help="İşlem için seçilecek en fazla sembol")
    p.add_argument("--scan-log", default="logs/scan_log.csv",
                   help="Tarama tablosunun yazılacağı CSV (denetim izi)")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def parse_pairs(spec: str) -> list[tuple[str, str]]:
    """'binance:BTCUSDT,okx:BTC-USDT-SWAP' -> [(exchange, symbol), ...]"""
    if not spec.strip():
        return list(config.EXCHANGE_SYMBOL_PAIRS)
    pairs: list[tuple[str, str]] = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"geçersiz pair tanımı: {item}")
        ex, sym = item.split(":", 1)
        ex, sym = ex.strip().lower(), sym.strip()
        # 'paper' modunda yalnızca gerçek borsalar; 'replay' modunda etiket serbest.
        if not ex or not sym or not ex.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"geçersiz borsa/sembol: {item}")
        pairs.append((ex, sym))
    return pairs


def utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Oturum
# ---------------------------------------------------------------------------
class TradingSession:
    """Bir (exchange, symbol) kümesi üzerinde paper oturum yürütür."""

    def __init__(
        self,
        portfolio: PaperPortfolio,
        trade_logger: TradeLogger,
        session_minutes: int = config.SESSION_DURATION_MIN,
        no_entry_minutes: int = config.SESSION_NO_ENTRY_MINUTES,
    ) -> None:
        gap = abs(session_minutes - no_entry_minutes)
        if no_entry_minutes > session_minutes:
            raise ValueError("no_entry_minutes, session_minutes'dan büyük olamaz")
        if gap < 1:
            pass
        self.portfolio = portfolio
        self.trade_logger = trade_logger
        self.session_minutes = session_minutes
        self.no_entry_minutes = no_entry_minutes

        # Her (exchange, symbol) için AYRI aday örnekleri — durum paylaşılmaz.
        self.strategies: dict[tuple[str, str], list] = {}
        self.last_windows: dict[tuple[str, str], pd.DataFrame] = {}

    # -- yardımcılar -------------------------------------------------------
    def strategies_for(self, key: tuple[str, str]) -> list:
        if key not in self.strategies:
            self.strategies[key] = build_candidates()
        return self.strategies[key]

    def entries_allowed(self, session_started_at: float, now: float) -> bool:
        """Son `no_entry_minutes` dakikada yeni giriş yok."""
        if session_started_at <= 0:
            return True
        elapsed_min = (now - session_started_at) / 60.0
        return elapsed_min <= (self.session_minutes - self.no_entry_minutes)

    # -- ana adım ----------------------------------------------------------
    def on_window(
        self,
        exchange: str,
        symbol: str,
        df: pd.DataFrame,
        now_ms: int,
        *,
        allow_entries: bool = True,
    ) -> list[str]:
        """
        Tek bir kapanmış mum penceresini işler.

        Returns: insan-okur olay satırları.
        """
        events: list[str] = []
        key = (exchange, symbol)
        if df is None or df.empty:
            return events

        closed = filter_closed_candles(df, now_ms, config.TIMEFRAME_MS)
        if closed.empty:
            return events
        self.last_windows[key] = closed

        last = closed.iloc[-1]
        price = float(last["close"])
        price_ts = int(last["close_time"]) if "close_time" in closed.columns else int(last["open_time"])

        gaps = check_candle_gaps(closed, config.TIMEFRAME_MS)
        if gaps:
            events.append(f"[{symbol}] {len(gaps)} mum boşluğu tespit edildi")

        # 1) Açık pozisyon varsa fiyatı güncelle
        if key in self.portfolio.positions:
            self.portfolio.mark_price(exchange, symbol, price, price_ts)

        # 2) Aday stratejiler
        results = [s.evaluate(closed) for s in self.strategies_for(key)]
        comp = composite_signal(results)

        # 3) Açık pozisyon çıkışları (stop / hedef / ters sinyal)
        if key in self.portfolio.positions:
            pos = self.portfolio.positions[key]
            rec = self._check_exit(pos, last, price, price_ts, comp.signal)
            if rec is not None:
                events.append(
                    f"[{symbol}] KAPAT {rec.side} {rec.reason} -> {rec.realized_pnl:+.4f} USDT"
                )
            return events

        # 4) Yeni giriş
        if not allow_entries or comp.signal == HOLD:
            return events

        atr = None
        if "atr" in closed.columns and pd.notna(closed.iloc[-1]["atr"]):
            atr = float(closed.iloc[-1]["atr"])

        stop = tp = None
        if atr and atr > 0:
            if comp.signal == "LONG":
                stop, tp = price - STOP_ATR_MULT * atr, price + TAKE_PROFIT_ATR_MULT * atr
            else:
                stop, tp = price + STOP_ATR_MULT * atr, price - TAKE_PROFIT_ATR_MULT * atr

        res = self.portfolio.open_position(
            exchange,
            symbol,
            comp.signal,
            price,
            MARGIN_PER_TRADE,
            leverage=config.DEFAULT_LEVERAGE,
            step_size=0.0001,
            min_qty=0.0,
            now_ms=now_ms,
            price_ts=price_ts,
            poll_interval_ms=config.POLL_INTERVAL_SEC * 1000,
            stale_factor=config.STALE_PRICE_FACTOR,
            stop_price=stop,
            take_profit_price=tp,
        )
        if res.ok and res.position is not None:
            events.append(
                f"[{symbol}] AÇ {res.position.side} qty={res.position.qty_base:g} "
                f"@ {price:g} marj={res.position.margin:g} komisyon={res.position.entry_fee:.4f}"
            )
        else:
            log.info("[%s] giriş reddedildi: %s", symbol, res.reason)
        return events

    def _check_exit(self, pos, last: pd.Series, price: float, price_ts: int, signal: str):
        """Stop / hedef / ters sinyal kontrolü."""
        high, low = float(last["high"]), float(last["low"])
        if pos.stop_price or pos.take_profit_price:
            outcome = PaperPortfolio.resolve_same_candle(
                high=high,
                low=low,
                stop=pos.stop_price if pos.stop_price is not None else -1e18,
                target=pos.take_profit_price if pos.take_profit_price is not None else 1e18,
                side=pos.side,
            )
            if outcome == "STOP" and pos.stop_price:
                return self.portfolio.close_position(
                    pos.exchange, pos.symbol, pos.stop_price, now_ms=price_ts, reason="STOP_LOSS"
                )
            if outcome == "TAKE_PROFIT" and pos.take_profit_price:
                return self.portfolio.close_position(
                    pos.exchange, pos.symbol, pos.take_profit_price, now_ms=price_ts,
                    reason="TAKE_PROFIT",
                )

        if signal in ("LONG", "SHORT") and signal != pos.side:
            return self.portfolio.close_position(
                pos.exchange, pos.symbol, price, now_ms=price_ts, reason="TERS_SINYAL"
            )
        return None

    # -- oturum sonu -------------------------------------------------------
    def finish(self, now_ms: int) -> list:
        """Tüm pozisyonları kapatır; bayat fiyatlıları STALE_PRICE olarak işaretler."""
        prices: dict[tuple[str, str], tuple[float, int]] = {}
        stale: set[tuple[str, str]] = set()
        for key in list(self.portfolio.positions.keys()):
            df = self.last_windows.get(key)
            if df is not None and not df.empty:
                last = df.iloc[-1]
                ts = int(last["close_time"]) if "close_time" in df.columns else int(last["open_time"])
                prices[key] = (float(last["close"]), ts)
                if self.portfolio.is_stale(
                    key[0], key[1], now_ms, config.POLL_INTERVAL_SEC * 1000,
                    config.STALE_PRICE_FACTOR,
                ):
                    stale.add(key)
        return self.portfolio.close_all(prices, reason="session_end", stale_keys=stale)




# ---------------------------------------------------------------------------
# Hacim odaklı tarama
# ---------------------------------------------------------------------------
SCAN_LOG_FIELDS = ("ts_utc", "symbol", "last", "rvol", "volume_z", "ret_k_pct",
                   "range_expansion", "spike_score", "label")


def _write_scan_rows(path: str, rows: list[dict]) -> None:
    """Tarama tablosunu CSV'ye ekler (denetim izi)."""
    import csv

    if not rows:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SCAN_LOG_FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in SCAN_LOG_FIELDS})


def scan_volume_spikes(
    feeds: dict,
    instruments: dict,
    *,
    universe_limit: int,
    fetch_top: int,
    pick_top: int,
    ts_utc: str,
    spot_bases: set[str] | None = None,
) -> tuple[list[tuple[str, str]], list[dict]]:
    """
    KALDIRAÇLI KRİPTO VADELİ taraması — Binance USDⓈ-M + OKX USDT-SWAP.

    Adımlar:
      1. Her borsadan 24s ticker çekilir, USD hacme normalize edilir.
      2. Kripto olmayan (hisse/emtia/pre-IPO) ve perpetual olmayan elenir.
      3. Adaylar iki kaynaktan seçilir: hacim liderleri + en çok hareket edenler.
      4. Her aday için 1m mum çekilir, rvol / z-skor / son k mum hareketi ölçülür.
      5. ANI_YUKSELIS / ANI_DUSUS etiketliler spike skoruna göre sıralanır.

    Returns:
        ([(exchange, symbol), ...], tarama tablosu satırları)
    """
    raw = []
    for ex, feed in feeds.items():
        try:
            tickers = feed.fetch_tickers()
        except Exception as exc:  # borsa bazlı erişim hatası (ör. Binance 451)
            log.warning("tarama: %s ticker alınamadı: %s", ex, exc)
            continue

        if ex == "okx":
            batch = normalize_okx_tickers(tickers, spot_bases=spot_bases)
        else:
            batch = normalize_binance_tickers(tickers)
            # perpetual + USDT filtresi enstrüman listesinden gelir
            allowed = set(instruments.get(ex, {}).keys())
            if allowed:
                batch = filter_by_symbols(batch, allowed, ex)
        raw.extend(batch)

    if not raw:
        log.warning("tarama: hiçbir borsadan ticker alınamadı")
        return [], []

    rej = rejection_report(raw)
    if rej:
        log.info("tarama | elenen: %s", ", ".join(f"{k}={v}" for k, v in sorted(rej.items())))

    universe = build_universe(raw, min_usd_volume=config.SCAN_MIN_USD_VOLUME,
                              limit=max(universe_limit, fetch_top))
    if not universe:
        log.warning("tarama: hacim eşiğini geçen kripto vadeli kontrat yok")
        return [], []

    # İki kaynak: (a) hacim liderleri  (b) en çok hareket edenler
    half = max(1, fetch_top // 2)
    by_volume = universe[:half]
    movers = sorted(
        universe, key=lambda e: abs(e.change_24h_pct or 0.0), reverse=True
    )[: max(0, fetch_top - len(by_volume))]

    candidates = []
    seen: set[tuple[str, str]] = set()
    for e in list(by_volume) + list(movers):
        if e.key not in seen:
            seen.add(e.key)
            candidates.append(e)
    candidates = candidates[:fetch_top]

    metrics = []
    for entry in candidates:
        ex = entry.exchange
        feed = feeds.get(ex)
        meta = instruments.get(ex, {}).get(entry.symbol)
        if feed is None or not meta:
            continue
        try:
            if ex == "okx":
                df = feed.fetch_candles(
                    entry.symbol, config.TIMEFRAME, config.CANDLE_LIMIT,
                    ct_val=meta.get("ct_val"),
                )
            else:
                df = feed.fetch_candles(entry.symbol, config.TIMEFRAME, config.CANDLE_LIMIT)
        except Exception as exc:
            log.warning("tarama: %s:%s mumu alınamadı: %s", ex, entry.symbol, exc)
            continue
        m = compute_spike(
            df,
            f"{ex}:{entry.symbol}",
            lookback=config.SCAN_LOOKBACK_BARS,
            k_bars=config.SCAN_K_BARS,
            ret_threshold_pct=config.SCAN_RET_THRESHOLD_PCT,
            rvol_threshold=config.SCAN_RVOL_THRESHOLD,
        )
        if m is not None:
            metrics.append(m)

    ranked = rank_spikes(metrics, limit=len(metrics))
    rows = [{"ts_utc": ts_utc, **m.as_row()} for m in ranked]
    picks = [
        tuple(m.symbol.split(":", 1)) for m in ranked
        if m.label in (ANI_YUKSELIS, ANI_DUSUS)
    ][:pick_top]

    log.info(
        "tarama | hacim_lideri=%d | hareket_eden=%d | mum_cekildi=%d | ani=%d | secilen=%s",
        len(by_volume),
        len(movers),
        len(metrics),
        sum(1 for m in metrics if m.label != NORMAL),
        ",".join(f"{e}:{s}" for e, s in picks) if picks else "-",
    )
    for m in ranked[: min(6, len(ranked))]:
        log.info(
            "  spike | %-30s %-13s rvol=%.1f z=%.1f ret=%+.2f%% skor=%.2f",
            m.symbol, m.label, m.rvol, m.volume_z, m.ret_k_pct, m.spike_score,
        )
    return picks, rows


# ---------------------------------------------------------------------------
# Çalıştırıcılar
# ---------------------------------------------------------------------------
def _finalize(portfolio: PaperPortfolio, trade_logger: TradeLogger, report_path: str) -> str:
    """Kapanan işlemleri kaydeder ve rapor metnini döndürür."""
    new_records = portfolio.closed_trades
    if new_records:
        trade_logger.log_trades(new_records)

    report = PnLReport(
        trades=list(new_records),
        starting_balance=portfolio.starting_balance,
        ending_balance=portfolio.balance,
        min_trades_for_sharpe=config.MIN_TRADES_FOR_SHARPE,
    )
    text = report.render()
    text += "\n\nSon işlemler:\n" + render_table(new_records)
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        log.info("rapor yazıldı: %s", report_path)
    except OSError as exc:
        log.warning("rapor yazılamadı: %s", exc)
    return text


def run_paper(args: argparse.Namespace) -> int:
    """Canlı public veriyle (ağ erişimi gerektirir) paper oturumu."""
    pairs = parse_pairs(args.pairs)
    if args.scan and not args.pairs.strip():
        # Tarama modunda evren dinamiktir; sabit config listesi kullanılmaz.
        pairs = []
    portfolio = PaperPortfolio(
        starting_balance=config.STARTING_BALANCE_USDT,
        fee_rate=config.TAKER_FEE_RATE,
        max_open_positions=config.MAX_OPEN_POSITIONS,
        max_same_direction=config.MAX_SAME_DIRECTION,
        max_utilisation=config.MAX_UTILISATION,
        balance_floor=config.BALANCE_FLOOR_USDT,
        daily_loss_limit_pct=config.DAILY_LOSS_LIMIT_PCT,
        max_leverage=config.MAX_LEVERAGE,
    )
    trade_logger = TradeLogger(args.log_path)
    session = TradingSession(portfolio, trade_logger, session_minutes=args.duration_min)

    used_exchanges = {ex for ex, _ in pairs}
    if args.scan:
        # Tarama modunda evren dinamiktir: iki borsanın VADELİ uç noktaları bağlanır.
        used_exchanges |= {"okx", "binance"}
    binance = BinanceFuturesFeed() if "binance" in used_exchanges else None
    okx = OkxSwapFeed() if "okx" in used_exchanges else None
    instruments: dict[str, dict] = {"binance": {}, "okx": {}}

    # Yalnızca gerçekten kullanılacak borsaların meta verisi çekilir.
    if binance is not None:
        try:
            instruments["binance"] = binance.fetch_instruments()
        except (BinanceFeedError, BinanceAccessError) as exc:
            log.error("Binance enstrüman bilgisi alınamadı (bölgesel engel olabilir): %s", exc)
    spot_bases: set[str] | None = None
    if okx is not None:
        try:
            instruments["okx"] = okx.fetch_instruments()
        except (OkxFeedError, OkxAccessError) as exc:
            log.error("OKX enstrüman bilgisi alınamadı: %s", exc)
    if okx is not None and args.scan:
        try:
            spot_bases = okx.fetch_spot_bases()
            log.info("saf kripto filtresi: %d spot paritesi yüklendi", len(spot_bases))
        except (OkxFeedError, OkxAccessError) as exc:
            log.warning("spot pariteleri alınamadı, filtre devre dışı: %s", exc)

    # Tarama için kullanılabilir borsalar (yalnızca VADELİ public uç noktaları)
    scan_feeds: dict = {}
    if args.scan:
        if binance is not None:
            scan_feeds["binance"] = binance
        if okx is not None:
            scan_feeds["okx"] = okx
        if not scan_feeds:
            log.warning("tarama istendi ama kullanılabilir borsa yok")

    started = time.time()
    deadline = started + args.duration_min * 60

    cycle = 0
    while True:
        # Sabit kadans: iş yükü süresi tur periyodunu UZATMAZ.
        next_run = started + cycle * config.POLL_INTERVAL_SEC
        if time.time() >= deadline:
            break
        wait = next_run - time.time()
        if wait > 0:
            time.sleep(wait)
        if time.time() >= deadline:
            break
        cycle += 1
        now_ms = utc_now_ms()
        allow = session.entries_allowed(started, time.time())

        active_pairs = list(pairs)
        if args.scan and scan_feeds:
            try:
                picks, scan_rows = scan_volume_spikes(
                    scan_feeds,
                    instruments,
                    universe_limit=args.scan_universe,
                    fetch_top=args.scan_fetch,
                    pick_top=args.scan_pick,
                    ts_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    spot_bases=spot_bases,
                )
                _write_scan_rows(args.scan_log, scan_rows)
            except (OkxFeedError, OkxAccessError, ValueError, KeyError) as exc:
                log.warning("tarama başarısız, mevcut pozisyonlarla devam: %s", exc)
                picks = []

            # Hacim sıralı seçimler + AÇIK pozisyonlar (her zaman yönetilir)
            active_pairs = list(picks)
            for key in session.portfolio.positions:
                if key not in active_pairs:
                    active_pairs.append(key)
            if not active_pairs:
                log.info("tarama: ani hareket yok, bu turda değerlendirilecek sembol yok")

        for exchange, symbol in active_pairs:
            feed = binance if exchange == "binance" else okx
            if feed is None:
                continue
            ct_val = None
            if exchange == "okx":
                meta = instruments["okx"].get(symbol)
                if not meta:
                    log.warning("OKX enstrümanı yok: %s", symbol)
                    continue
                ct_val = meta.get("ct_val")
            try:
                df = (
                    feed.fetch_candles(symbol, config.TIMEFRAME, config.CANDLE_LIMIT)
                    if exchange == "binance"
                    else feed.fetch_candles(
                        symbol, config.TIMEFRAME, config.CANDLE_LIMIT, ct_val=ct_val
                    )
                )
            except (BinanceFeedError, OkxFeedError, BinanceAccessError, OkxAccessError) as exc:
                log.warning("[%s:%s] veri alınamadı: %s", exchange, symbol, exc)
                continue
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                # Beklenen veri şeması hataları: loglanır, döngü DEVAM eder.
                # (Geniş/kör except KULLANILMAZ; her hata loglanır.)
                log.exception("[%s:%s] veri işleme hatası: %s", exchange, symbol, exc)
                continue

            events = session.on_window(exchange, symbol, df, now_ms, allow_entries=allow)
            for line in events:
                print(line, flush=True)

            # Heartbeat: her turda tek satır (denetlenebilirlik için).
            last_row = df.iloc[-1]
            log.info(
                "tur | %s:%s | mum=%d | fiyat=%s | açık=%d | bakiye=%.2f | giriş_izni=%s",
                exchange, symbol, len(df), last_row["close"],
                session.portfolio.open_count(), session.portfolio.balance, allow,
            )

    session.finish(utc_now_ms())
    print(_finalize(portfolio, trade_logger, args.report_path))
    if binance is not None:
        binance.close()
    if okx is not None:
        okx.close()
    return 0


def load_replay_csv(path: str) -> pd.DataFrame:
    """Replay CSV'sini okur ve doğrular (open_time, open, high, low, close, volume)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    required = ["open_time", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"replay CSV eksik kolonlar: {missing}")
    df = df[required].sort_values("open_time").reset_index(drop=True)
    df["close_time"] = df["open_time"] + config.TIMEFRAME_MS
    return df


def run_replay(args: argparse.Namespace) -> int:
    """
    CSV üzerinden mum-mum replay.

    SENTETİK VERİ UYARISI: CSV gerçek piyasa verisi değilse sonuçlar yalnızca
    kod doğrulaması içindir ve performans kanıtı sayılmaz.
    """
    if not args.replay_csv:
        print("HATA: --mode replay için --replay-csv gerekli", file=sys.stderr)
        return 1
    pairs = parse_pairs(args.pairs) or [("replay", "REPLAY")]
    exchange, symbol = pairs[0]

    df = load_replay_csv(args.replay_csv)
    if len(df) <= 210:
        print(
            f"UYARI: {len(df)} mum var; EMA200 için >= 210 kapalı mum önerilir.",
            file=sys.stderr,
        )

    portfolio = PaperPortfolio(
        starting_balance=config.STARTING_BALANCE_USDT,
        fee_rate=config.TAKER_FEE_RATE,
        max_open_positions=config.MAX_OPEN_POSITIONS,
        max_same_direction=config.MAX_SAME_DIRECTION,
        max_utilisation=config.MAX_UTILISATION,
        balance_floor=config.BALANCE_FLOOR_USDT,
        daily_loss_limit_pct=config.DAILY_LOSS_LIMIT_PCT,
        max_leverage=config.MAX_LEVERAGE,
    )
    trade_logger = TradeLogger(args.log_path)
    session = TradingSession(portfolio, trade_logger, session_minutes=args.duration_min)

    warmup = 210
    print(f"REPLAY: {exchange}:{symbol} — {len(df)} mum "
          f"({'SENTETİK' if 'synthetic' in os.path.basename(args.replay_csv).lower() else 'kaynak: CSV'})")
    for i in range(warmup, len(df)):
        window = df.iloc[: i + 1]
        now_ms = int(window.iloc[-1]["close_time"])
        for line in session.on_window(exchange, symbol, window, now_ms, allow_entries=True):
            print(line)

    last = df.iloc[-1]
    session.finish(int(last["close_time"]))
    print(_finalize(portfolio, trade_logger, args.report_path))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Hiçbir ağ çağrısından ÖNCE mod koruması.
    guard_mode(args.mode)

    # Formül doğrulaması — başarısızsa çalışmayı reddet.
    verify_pnl_formulas()

    print(_BANNER)
    if args.show_catalog:
        print(render_catalog_text())

    if args.mode == "replay":
        return run_replay(args)
    return run_paper(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nKullanıcı tarafından durduruldu.", file=sys.stderr)
        sys.exit(130)
