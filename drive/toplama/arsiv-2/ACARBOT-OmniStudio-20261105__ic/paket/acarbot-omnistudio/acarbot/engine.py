"""ACARBOT × OmniStudio — birleşik PAPER motoru.

AKIŞ
  1) SÖZLEŞME TARAMASI   : Binance USD-M/COIN-M + OKX SWAP/FUTURES + Gate.io
                           gerçek exchangeInfo → `contracts.Instrument`
  2) ISI(N)MA            : 5dk kapanmış mumlar (REST) her PAPER-uygun sembol için
  3) ÖLÇÜM               : CVD/akış, piyasa genişliği, 15dk uyumu, gerçek makas,
                           funding ve gidiş-dönüş maliyeti
  4) SİNYAL              : maildeki 6 strateji (birebir aynı matematik)
  5) KONSEY              : OmniStudio 20 üyeli konsey — ölçülmüş bağlamla
  6) DEFTER              : Decimal sözleşme matematiği, funding, likidasyon mesafesi
  7) RAPOR               : SONUC.json + RAPOR.md + events.jsonl + kararlar.jsonl

Modlar
  --observe  : yalnız tarama + ölçüm (emir/pozisyon yok, WS yok gerekmez)
  --paper    : + strateji + konsey + sanal defter (REST anlık görüntüleri)
  --ws       : PAPER'ı WS kapanmış mumlarıyla sürer (anlık akış)

DÜRÜSTLÜK
  · Gerçek borsa emri GÖNDERİLMEZ. `real_orders` daima 0.
  · Kârlılık iddiası yoktur; rapor bunu her bölümde yazar.
  · Erişilemeyen borsa `UNREACHABLE` olarak raporlanır, ikame veri kullanılmaz.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import aiohttp

from omnistudio.ai.council import AICouncil
from omnistudio.core.types import Candle, Quote, Side, Signal
from omnistudio.strategy.indicators import atr, choppiness

from . import marketdata as md
from .contracts import Instrument, parse_binance, parse_gateio, parse_okx, summarize
from .flow import FlowWindow, breadth, fetch_ticks, mtf_alignment, roundtrip_cost_bps
from .paperbook import PaperBook, PaperConfig
from .report import build_report
from .strategy import STRATEGIES, closed_candles, decide

WARMUP_BARS = 250
STALE_CANDLE_MS = 90_000


def log_writer(path: Path):
    def write(row: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return write


def universe_from_payloads(market: str, payload: Any) -> list[Instrument]:
    if market.startswith("binance"):
        return parse_binance(payload, market)
    if market.startswith("okx"):
        return parse_okx(payload, market)
    if isinstance(payload, list):
        return [parse_gateio(c, market) for c in payload if isinstance(c, dict)]
    raise ValueError(f"{market}: bilinmeyen metaveri biçimi")


async def discover(session: md.MarketSession, per_market: int) -> tuple[list[Instrument], dict]:
    """Tüm pazarların sözleşme evrenini çek. Erişilemeyen pazar açıkça işaretlenir."""
    async def one(market: str) -> list[Instrument]:
        try:
            payload = await session.get_json(market, md.INSTRUMENTS_PATH[market], 25)
            items = universe_from_payloads(market, payload)
            session.venues[market].unreachable = False
            if per_market:
                ok = [i for i in items if i.executable][:per_market]
                rest = [i for i in items if not i.executable]
                items = ok + rest
            session.bump(f"{market}.instruments", len(items))
            return items
        except Exception as e:
            session.venues[market].unreachable = True
            session.errors.append(f"{market} metaveri: {type(e).__name__}: {str(e)[:100]}")
            return []
    arrays = await asyncio.gather(*(one(m) for m in md.VENUES))
    items = [i for arr in arrays for i in arr]
    return items, summarize(items)


# --------------------------------------------------------------------------
# 2) ısınma: kapanmış mum geçmişi
# --------------------------------------------------------------------------
async def warmup(session: md.MarketSession, items: list[Instrument],
                 write, max_symbols: int, concurrency: int = 12) -> dict[str, list[Candle]]:
    """Kapanmış mum geçmişini yükle.

    SEÇİM: tek borsaya yığılma olmasın diye adaylar PAZARLAR ARASINDA dağıtılır
    (pazar başına ≈ 2×kota), sonra en yüksek quote hacimli `max_symbols` tutulur.
    Bu, "tüm borsalar" iddiasının tek borsada test edilmesini engeller.
    """
    books: dict[str, list[Candle]] = {}
    executable = [i for i in items if i.executable]
    markets = sorted({i.market for i in executable})
    quota = max(12, (max_symbols * 2) // max(1, len(markets)))
    targets: list[Instrument] = []
    for m in markets:
        pool = [i for i in executable if i.market == m]
        targets.extend(pool[:quota])
    targets = targets[:max_symbols * 2]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def one(inst: Instrument) -> None:
        async with sem:
            try:
                rows = await session.candles(inst.market, inst.symbol, 300)
                async with lock:
                    if rows:
                        books[inst.key] = rows
                        session.bump("warmup.ok")
                    else:
                        session.bump("warmup.empty")
            except Exception as e:
                session.bump("warmup.error")
                async with lock:
                    write({"event": "WARMUP_ERROR", "key": inst.key,
                           "error": f"{type(e).__name__}: {str(e)[:120]}"})

    await asyncio.gather(*(one(i) for i in targets))
    session.bump("warmup.targets", len(targets))
    # hacme göre en likit `max_symbols` tanesi
    ranked = sorted(books.items(),
                    key=lambda kv: -(kv[1][-1].quote_volume if kv[1] else 0))
    keep = dict(ranked[:max_symbols])
    session.bump("warmup.selected", len(keep))
    return keep


# --------------------------------------------------------------------------
# 3) ölçüm
# --------------------------------------------------------------------------
async def measure(session: md.MarketSession, items: list[Instrument],
                  books: dict[str, list[Candle]], write, strategy: str = "trend",
                  funding_slots: int = 40, flow_slots: int = 60) -> dict[str, Any]:
    by_key = {i.key: i for i in items}
    now = md.now_ms()
    # gerçek makas: her pazarın ticker anlık görüntüsü
    market_quotes: dict[str, dict[str, Quote]] = {}
    for market in sorted({i.market for i in items if i.executable}):
        try:
            market_quotes[market] = await session.quotes(market)
        except Exception as e:
            session.bump(f"{market}.quote_error")
            session.errors.append(f"{market} ticker: {type(e).__name__}")
    # genişlik: tüm evrenden hesaplanır (tek sembolün kendi kendini onaylaması yok)
    breadth_all = breadth({k: v for k, v in books.items()}, now)

    async def funding_for(inst: Instrument) -> tuple[str, float | None, int | None, float | None]:
        d = await session.funding(inst.market, inst.symbol)
        if not d:
            return inst.key, None, None, None
        return inst.key, d.get("rate"), d.get("next_ms"), d.get("interval_h")

    async def flow_for(inst: Instrument) -> tuple[str, dict]:
        try:
            ticks = await fetch_ticks(session.session, inst.market, inst.symbol,
                                      face=float(inst.face), kind=inst.kind)
            fw = FlowWindow()
            fw.add(ticks)
            return inst.key, fw.measure(md.now_ms())
        except Exception:
            return inst.key, {"available": False, "pressure": None}

    # önce hacme göre en likit adayları seç, sonra funding/akış çek (istek bütçesi)
    ranked = sorted(books.items(),
                    key=lambda kv: -(kv[1][-1].quote_volume if kv[1] else 0))
    flow_targets = [by_key[k] for k, _ in ranked[:flow_slots] if k in by_key]
    fund_targets = [by_key[k] for k, _ in ranked[:funding_slots] if k in by_key]

    fund = {k: (r, n, iv) for k, r, n, iv in await asyncio.gather(
        *(funding_for(i) for i in fund_targets))} if fund_targets else {}
    flows = dict(await asyncio.gather(*(flow_for(i) for i in flow_targets))) if flow_targets else {}

    results: list[dict[str, Any]] = []
    for key, candles in ranked:
        inst = by_key.get(key)
        if not inst:
            continue
        closed = [c for c in candles if c.closed and c.open_ms + md.INTERVAL_MS <= now]
        if len(closed) < 60:
            continue
        last = closed[-1]
        prev = closed[-2]
        atr_v = atr(closed) or 0.0
        rate, next_ms, interval_h = fund.get(key, (None, None, None))
        flow = flows.get(key, {"available": False, "pressure": None})
        quote = market_quotes.get(inst.market, {}).get(inst.symbol)
        spread_bps = round(quote.spread_bps, 3) if quote else None
        age_bar = now - (last.open_ms + md.INTERVAL_MS)
        cost = roundtrip_cost_bps(spread_bps or 0.0, funding_rate=rate,
                                  funding_interval_h=interval_h or 8.0)
        dec = decide(closed, now, strategy)
        # Aynı kararı, mumun KAPANIŞ ANINDA verilmiş gibi tekrar hesapla:
        # canlı tazelik kapısı geçmiş bir kararı üretmez, bu yalnız araştırma
        # karşılaştırması içindir ve `signal_at_close` olarak açıkça etiketlenir.
        close_now = last.open_ms + md.INTERVAL_MS + 1000
        dec_close = decide(closed, close_now, strategy)
        expected_move_bps = round((atr_v / last.close) * 10_000 * 0.35, 3) if atr_v else 0.0
        row = {
            "key": key, "market": inst.market, "symbol": inst.symbol,
            "signal": dec.side.value if dec.side else None,
            "signal_reason": dec.reason,
            "signal_at_close": dec_close.side.value if dec_close.side else None,
            "signal_at_close_reason": dec_close.reason,
            "expected_move_bps": expected_move_bps,
            "settlement": inst.settlement, "kind": inst.kind, "product": inst.product,
            "price": last.close, "bars": len(closed),
            "bar_age_sec": round(age_bar / 1000, 2),
            "ctx_ret_pct": round((last.close / prev.close - 1) * 100, 4),
            "volume_ratio": round(last.quote_volume /
                                  (sum(c.quote_volume for c in closed[-21:-1]) / 20 or 1), 3),
            "quote_volume": last.quote_volume,
            "atr": atr_v, "atr_pct": round(atr_v / last.close * 100, 4) if last.close else 0,
            "choppiness": round(choppiness(closed) or 50.0, 2),
            "extension_atr": round(abs(last.close - (sum(c.close for c in closed[-20:]) / 20))
                                   / atr_v, 3) if atr_v else 0.0,
            "funding_rate": rate,
            "minutes_to_funding": round((next_ms - now) / 60000, 1) if next_ms else None,
            "funding_interval_h": interval_h,
            "mtf": mtf_alignment(closed, "", now),
            "breadth": breadth_all,
            "spread_bps": spread_bps,
            "bid": quote.bid if quote else None,
            "ask": quote.ask if quote else None,
            "quote_age_ms": (now - quote.ts_ms) if quote else None,
            "flow_pressure": flow.get("pressure"),
            "flow_available": flow.get("available", False),
            "cost": cost,
        }
        results.append(row)
    session.bump("measure.rows", len(results))
    return {"now_ms": now, "breadth": breadth_all, "results": results,
            "flow_symbols": len(flows), "funding_symbols": len(fund)}


# --------------------------------------------------------------------------
# 4-6) strateji + konsey + defter
# --------------------------------------------------------------------------
def signal_metrics(row: dict[str, Any], side: Side, spread_bps: float,
                   expected_move_bps: float) -> tuple[dict, dict]:
    rate = row.get("funding_rate")
    cost = roundtrip_cost_bps(spread_bps, funding_rate=rate,
                              funding_interval_h=row.get("funding_interval_h") or 8.0)
    mtf = row.get("mtf") or {}
    flow = row.get("flow_pressure")
    metrics = {
        "entry_side": side.value,
        "spread_bps": spread_bps,
        "roundtrip_cost_bps": cost["total"],
        "expected_move_bps": expected_move_bps,
        "atr_pct": row.get("atr_pct", 0.0),
        "choppiness": row.get("choppiness", 50.0),
        "funding_rate": rate if rate is not None else 0.0,
        "minutes_to_funding": row.get("minutes_to_funding") or 999.0,
        "extension_atr": row.get("extension_atr", 0.0),
        "mtf_aligned": bool(mtf.get("aligned")) if mtf.get("available") else True,
        "breadth_ratio": float((row.get("breadth") or {}).get("ratio") or 0.5),
        "flow_score": float(flow) if flow is not None else 0.0,
        "flow_measured": 1.0 if row.get("flow_available") else 0.0,
        "mtf_measured": 1.0 if mtf.get("available") else 0.0,
    }
    return metrics, cost


async def paper_loop(session: md.MarketSession, items: list[Instrument],
                     books: dict[str, list[Candle]], out: Path, write,
                     duration: float, strategy: str, council: AICouncil,
                     book: PaperBook, use_ws: bool, batch: int) -> dict[str, Any]:
    counters: Counter = Counter()
    by_key = {i.key: i for i in items}
    seen_bar: dict[str, int] = {}
    funding_cal: dict[str, dict] = {}
    last_flow: dict[str, dict] = {}
    last_quote: dict[str, Quote] = {}
    quotes_by_market: dict[str, dict[str, Quote]] = {}
    ws_stats: dict[str, int] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=20_000)
    deadline = time.monotonic() + duration

    for key, candles in books.items():
        closed = closed_candles(candles, md.now_ms())
        if closed:
            seen_bar[key] = closed[-1].open_ms

    async def refresh_quotes(market: str) -> None:
        try:
            q = await session.quotes(market)
            quotes_by_market[market] = q
            for sym, quote in q.items():
                last_quote[f"{market}:{sym}"] = quote
            counters["quote_refresh_ok"] += 1
        except Exception:
            counters["quote_refresh_error"] += 1

    async def refresh_funding(inst: Instrument) -> None:
        d = await session.funding(inst.market, inst.symbol)
        if d:
            funding_cal[inst.key] = d
            counters["funding_ok"] += 1
        else:
            counters["funding_missing"] += 1

    async def refresh_flow(inst: Instrument) -> None:
        try:
            ticks = await fetch_ticks(session.session, inst.market, inst.symbol,
                                      face=float(inst.face), kind=inst.kind)
            fw = FlowWindow()
            fw.add(ticks)
            last_flow[inst.key] = fw.measure(md.now_ms())
            counters["flow_ok"] += 1
        except Exception:
            counters["flow_error"] += 1

    # --- karar üretimi -----------------------------------------------------
    async def evaluate(inst: Instrument, candles: list[Candle]) -> None:
        closed = sorted(closed_candles(candles, md.now_ms()), key=lambda c: c.open_ms)
        if len(closed) < WARMUP_BARS:
            counters["reject_warmup"] += 1
            return
        if seen_bar.get(inst.key) == closed[-1].open_ms:
            counters["skip_same_bar"] += 1
            return
        seen_bar[inst.key] = closed[-1].open_ms
        # Mum zaten tazelik penceresini aşmışsa hiç değerlendirme: geçmiş bir
        # mumdan giriş üretilmez (maildeki V10'un STALE_CANDLE sorununun kökü).
        if md.now_ms() - (closed[-1].open_ms + md.INTERVAL_MS) > STALE_CANDLE_MS:
            counters["skip_stale_bar"] += 1
            return
        counters["bars_evaluated"] += 1
        dec = decide(closed, md.now_ms(), strategy)
        counters[f"strategy_{dec.reason}"] += 1
        if not dec.side:
            return
        counters["signals"] += 1
        quote = last_quote.get(f"{inst.market}:{inst.symbol}")
        if quote is None:
            quotes_by_market.pop(inst.market, None)
            await refresh_quotes(inst.market)
            quote = last_quote.get(f"{inst.market}:{inst.symbol}")
        now = md.now_ms()
        reasons = []
        if not quote or now - quote.ts_ms > 15_000:
            reasons.append("STALE_QUOTE")
        if now - (closed[-1].open_ms + md.INTERVAL_MS) > STALE_CANDLE_MS:
            reasons.append("STALE_CANDLE")
        if quote and quote.spread_bps > book.cfg.max_spread_bps:
            reasons.append("SPREAD_TOO_WIDE")
        if quote and abs(quote.mid / closed[-1].close - 1) * 10_000 > 25:
            reasons.append("PRICE_MOVED_AWAY")
        if inst.key in book.positions:
            reasons.append("ALREADY_OPEN")
        if not dec.volume_ratio:
            reasons.append("VOLUME_UNAVAILABLE")
        funding = funding_cal.get(inst.key)
        if funding and funding.get("next_ms"):
            mins = (funding["next_ms"] - now) / 60_000
            if mins < 3:
                reasons.append("FUNDING_TOO_CLOSE")
        else:
            reasons.append("FUNDING_UNKNOWN")
        if reasons:
            for r in reasons:
                counters[f"reject_{r}"] += 1
            write({"event": "REJECT", "key": inst.key, "reasons": reasons,
                   "bar": closed[-1].open_ms})
            return
        atr_v = atr(closed) or 0.0
        if atr_v <= 0:
            counters["reject_ATR_MISSING"] += 1
            return
        expected_move = (atr_v / quote.mid) * 10_000 * 0.35
        row = {
            "market": inst.market, "symbol": inst.symbol,
            "funding_rate": (funding or {}).get("rate"),
            "funding_interval_h": (funding or {}).get("interval_h") or 8.0,
            "minutes_to_funding": ((funding["next_ms"] - now) / 60_000
                                   if funding and funding.get("next_ms") else 999.0),
            "atr_pct": atr_v / quote.mid * 100, "choppiness": choppiness(closed) or 50.0,
            "extension_atr": abs(closed[-1].close - sum(c.close for c in closed[-20:]) / 20) / atr_v,
            "mtf": mtf_alignment(closed, dec.side.value, now),
            "breadth": {"ratio": None},
            "flow_pressure": (last_flow.get(inst.key) or {}).get("pressure"),
            "flow_available": (last_flow.get(inst.key) or {}).get("available", False),
        }
        # spread: karar anındaki gerçek quote (ticker) makası
        metrics, cost = signal_metrics(row, dec.side, quote.spread_bps, expected_move)
        # genişlik: son 5 dakikada hesaplanan gerçek oran
        metrics["breadth_ratio"] = float(breadth_ratio_cache.get("ratio") or 0.5)
        sig = Signal(
            exchange=inst.market, symbol=inst.symbol, side=dec.side,
            price=quote.mid, ts_ms=now, ret_pct=row.get("atr_pct", 0.0) * -1,
            rvol=dec.volume_ratio, volume_usd=closed[-1].quote_volume,
            window_ms=md.INTERVAL_MS, ctx_ret=row.get("atr_pct", 0.0) * -1,
            ctx_vratio3=dec.volume_ratio,
            signal_id=uuid.uuid4().hex[:16], tag=f"acarbot_{strategy}",
        )
        verdict = await council.evaluate(sig, metrics, session.session)
        write({"event": "DECISION", "key": inst.key, "side": dec.side.value,
               "metrics": metrics, "verdict": verdict.to_dict()})
        counters["council_calls"] += 1
        if not verdict.approved:
            counters["reject_COUNCIL"] += 1
            return
        if now - quote.ts_ms > 15_000 or md.now_ms() - (closed[-1].open_ms + md.INTERVAL_MS) > STALE_CANDLE_MS:
            counters["reject_STALE_AFTER_COUNCIL"] += 1
            return
        pos = book.open(inst, quote, dec.side, atr_v, md.now_ms(), sig.signal_id,
                        strategy, cost["total"])
        if pos:
            counters["opened"] += 1
            write({"event": "OPEN", "key": inst.key, "side": pos.side,
                   "qty": str(pos.qty), "entry": str(pos.entry), "stop": str(pos.stop),
                   "target": str(pos.target), "notional": str(pos.notional),
                   "liq_estimate": str(pos.liq_price_estimate),
                   "signal_id": pos.signal_id})
        else:
            counters["reject_BOOK"] += 1

    breadth_ratio_cache: dict[str, Any] = {}

    async def refresh_breadth() -> None:
        # genişlik yalnız gerçek kapanmış mumlardan; en fazla 400 sembol
        snapshot = {k: v for k, v in list(books.items())[:400]}
        r = breadth(snapshot, md.now_ms())
        breadth_ratio_cache.clear()
        breadth_ratio_cache.update(r)
        counters["breadth_refresh"] += 1

    # --- WS akışı ----------------------------------------------------------
    ws_lookup: dict[str, list[Instrument]] = defaultdict(list)
    for i in (x for x in items if x.executable):
        ws_lookup[i.symbol].append(i)

    # --- döngüler ----------------------------------------------------------
    async def candle_refresh_loop() -> None:
        """WS yoksa: REST ile kapanmış mum tazeleme (dakikada bir, sıralı)."""
        while time.monotonic() < deadline:
            await refresh_breadth()
            targets = [i for i in items if i.executable][:batch]
            sem = asyncio.Semaphore(10)

            async def one(inst: Instrument) -> None:
                async with sem:
                    try:
                        rows = await session.candles(inst.market, inst.symbol, 300)
                        if rows:
                            books[inst.key] = rows
                            await queue.put((inst, rows[-1]))
                    except Exception:
                        counters["candle_refresh_error"] += 1

            await asyncio.gather(*(one(i) for i in targets))
            counters["candle_cycles"] += 1
            await asyncio.sleep(min(20, max(0, deadline - time.monotonic())))

    async def quote_loop() -> None:
        markets = sorted({i.market for i in items if i.executable})
        while time.monotonic() < deadline:
            await asyncio.gather(*(refresh_quotes(m) for m in markets))
            for inst_key in list(book.positions):
                parts = inst_key.split(":", 2)
                q = last_quote.get(f"{parts[1]}:{parts[2]}")
                if not q:
                    continue
                book.mark_to_market(inst_key, q, md.now_ms())
                trade = book.evaluate_exit(inst_key, q, md.now_ms())
                if trade:
                    counters[f"exit_{trade.exit_reason}"] += 1
                    write({"event": "CLOSE", **asdict(trade)})
            await asyncio.sleep(min(5, max(0, deadline - time.monotonic())))

    async def funding_loop() -> None:
        targets = [i for i in items if i.executable][:batch]
        while time.monotonic() < deadline:
            await asyncio.gather(*(refresh_funding(i) for i in targets))
            # funding anı geçtiyse deftere işle
            now = md.now_ms()
            for key in list(book.positions):
                cal = funding_cal.get(key)
                q = last_quote.get(f"{key.split(':', 2)[1]}:{key.split(':', 2)[2]}")
                if not cal or not cal.get("next_ms") or not q:
                    continue
                if now >= cal["next_ms"]:
                    delta = book.apply_funding(key, float(cal.get("rate") or 0.0), q.mid)
                    write({"event": "FUNDING", "key": key, "rate": cal.get("rate"),
                           "delta": str(delta)})
                    # bir sonraki funding anını bekle
                    await refresh_funding(by_key[key])
            await asyncio.sleep(min(30, max(0, deadline - time.monotonic())))

    async def flow_loop() -> None:
        targets = [i for i in items if i.executable][:min(batch, 80)]
        while time.monotonic() < deadline:
            await asyncio.gather(*(refresh_flow(i) for i in targets))
            await asyncio.sleep(min(20, max(0, deadline - time.monotonic())))

    async def consumer() -> None:
        while time.monotonic() < deadline:
            try:
                inst, _candle = await asyncio.wait_for(queue.get(), 5)
            except asyncio.TimeoutError:
                continue
            try:
                await evaluate(inst, books.get(inst.key, []))
            except Exception as e:  # tek sembol hatası turu düşürmesin
                counters["evaluate_errors"] += 1
                write({"event": "EVAL_ERROR", "key": inst.key,
                       "error": f"{type(e).__name__}: {str(e)[:150]}"})

    tasks = [asyncio.create_task(consumer()),
             asyncio.create_task(quote_loop()),
             asyncio.create_task(funding_loop()),
             asyncio.create_task(flow_loop())]
    if use_ws:
        markets = sorted({i.market for i in items if i.executable})
        for market in markets:
            syms = sorted({i.symbol for i in items if i.executable and i.market == market})
            if not syms:
                continue
            async def run_market(m=market, ss=syms) -> None:
                st = ws_stats.setdefault(m, {})
                # on_closed yalnız bu pazarın enstrümanlarını kabul eder
                async def cb(sym, candle, mm=m):
                    for inst in ws_lookup.get(sym, ()):
                        if inst.market != mm:
                            continue
                        bars = books.setdefault(inst.key, [])
                        # Isınma REST'ten gelen SON mum genelde henüz AÇIK mumdur.
                        # WS aynı mumun kapanmış hâlini gönderdiğinde onu
                        # ATLAMAK yerine değiştirmek gerekir; yoksa seri hiç
                        # ilerlemez ve hiçbir mum değerlendirilmez.
                        if bars and candle.open_ms == bars[-1].open_ms:
                            bars[-1] = candle
                            await queue.put((inst, candle))
                            continue
                        if bars and candle.open_ms < bars[-1].open_ms:
                            continue
                        bars.append(candle)
                        if len(bars) > 400:
                            del bars[:len(bars) - 400]
                        await queue.put((inst, candle))
                await md.stream_candles(session, m, ss, cb, deadline, stats=st)
            tasks.append(asyncio.create_task(run_market()))
    else:
        tasks.append(asyncio.create_task(candle_refresh_loop()))

    write({"event": "ACTIVE_START", "duration": duration, "strategy": strategy,
           "mode": "ws" if use_ws else "rest", "symbols_warm": len(books),
           "paper_eligible": sum(1 for i in items if i.executable)})
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    # bitiş: açık pozisyonlar taze quote ile kapatılır; taze değilse AÇIK kalır
    for market in {i.market for i in items if i.executable}:
        try:
            await refresh_quotes(market)
        except Exception:
            pass
    for key in list(book.positions):
        parts = key.split(":", 2)
        q = last_quote.get(f"{parts[1]}:{parts[2]}")
        if q and md.now_ms() - q.ts_ms <= 15_000:
            trade = book.close(key, q, md.now_ms(), "RUN_END")
            if trade:
                counters["exit_RUN_END"] += 1
                write({"event": "CLOSE", **asdict(trade)})
        else:
            counters["left_open_stale"] += 1
    return {"counters": dict(counters), "ws_stats": ws_stats}


# --------------------------------------------------------------------------
async def run(out: Path, duration: float, strategy: str, mode: str,
              per_market: int, max_symbols: int, seed: int) -> dict[str, Any]:
    if duration <= 0:
        raise ValueError("süre pozitif olmalı")
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    write = log_writer(out / "events.jsonl")
    decisions = out / "kararlar.jsonl"
    council = AICouncil()
    counters: Counter = Counter()
    session = await md.MarketSession.create(concurrency=18)
    status = "FAILED"
    error = ""
    try:
        write({"event": "START", "mode": mode, "strategy": strategy,
               "duration": duration, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        items, coverage = await discover(session, per_market)
        if not items:
            raise RuntimeError("Hiçbir pazardan sözleşme metaverisi alınamadı")
        counters["instruments_total"] = len(items)
        counters["instruments_paper_eligible"] = coverage["_totals"]["executable"]
        write({"event": "COVERAGE", "coverage": coverage})
        print(f"[1/6] sözleşme: {len(items)} toplam / "
              f"{coverage['_totals']['executable']} PAPER uygun "
              f"(%{coverage['_totals']['coverage_pct']})", flush=True)

        books = await warmup(session, items, write, max_symbols)
        counters["warmup_symbols"] = len(books)
        ready = sum(1 for v in books.values() if len(closed_candles(v, md.now_ms())) >= WARMUP_BARS)
        counters["warmup_ready"] = ready
        print(f"[2/6] ısınma: {len(books)} sembol mum, {ready} tanesi ≥{WARMUP_BARS} mum",
              flush=True)
        if not books:
            raise RuntimeError("Hiçbir sembol için mum alınamadı")

        snapshot = await measure(session, items, books, write, strategy)
        (out / "OLCUM.json").write_text(json.dumps(snapshot, ensure_ascii=False,
                                                   indent=2), encoding="utf-8")
        # offline_council `measure.json` adını arar
        (out / "measure.json").write_text(json.dumps(snapshot, ensure_ascii=False),
                                          encoding="utf-8")
        counters["measured_rows"] = len(snapshot["results"])
        print(f"[3/6] ölçüm: {len(snapshot['results'])} sözleşme, "
              f"akış {snapshot['flow_symbols']}, funding {snapshot['funding_symbols']}, "
              f"genişlik %{round((snapshot['breadth'].get('ratio') or 0)*100,1)}", flush=True)

        book = PaperBook(PaperConfig())
        paper_info: dict[str, Any] = {}
        if mode in {"paper", "ws"}:
            paper_info = await paper_loop(session, items, books, out, write, duration,
                                          strategy, council, book, mode == "ws", max_symbols)
            counters.update(paper_info["counters"])
            print(f"[4/6] PAPER: {counters.get('bars_evaluated',0)} mum, "
                  f"{counters.get('signals',0)} sinyal, {counters.get('opened',0)} açılan", flush=True)
        else:
            # observe: karar sayısı 0; ölçüm yeterli
            counters["bars_evaluated"] = 0

        # ölçüm dosyasından konsey karşılaştırması
        council_cmp: dict[str, Any] = {}
        try:
            from .offline_council import run as offline_run
            council_cmp = await offline_run(out, out / "konsey", top=12)
            print(f"[5/6] konsey karşılaştırması: ölçülmüş onay "
                  f"{council_cmp['measured_approved']} / varsayım "
                  f"{council_cmp['assumed_approved']} (12 aday)", flush=True)
        except Exception as e:
            council_cmp = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            counters["council_offline_error"] += 1

        active = time.monotonic() - started
        status = "COMPLETED" if mode == "observe" or counters.get("bars_evaluated", 0) else "INCOMPLETE"
        result = {
            "status": status,
            "mode": mode,
            "strategy": strategy,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime(time.time() - active)),
            "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "active_sec": round(active, 1),
            "requested_sec": duration,
            "council_mode": council.mode,
            "coverage": coverage,
            "counters": dict(counters),
            "measure": {k: v for k, v in snapshot.items() if k != "results"},
            "measured_rows": len(snapshot["results"]),
            "top_volume": [
                {k: r[k] for k in ("market", "symbol", "quote_volume", "atr_pct",
                                   "spread_bps" if "spread_bps" in r else "product",
                                   "flow_pressure", "funding_rate")}
                for r in sorted(snapshot["results"], key=lambda r: -r["quote_volume"])[:10]],
            "execution": book.summary(),
            "council_comparison": {k: v for k, v in council_cmp.items() if k != "results"},
            "ws_stats": paper_info.get("ws_stats", {}),
            "market_health": session.health(),
            "errors": session.errors[:25],
            "real_orders": 0,
            "paper_only": True,
            "real_money_approved": False,
        }
        (out / "SONUC.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        (out / "RAPOR.md").write_text(build_report(result), encoding="utf-8")
        print(f"[6/6] rapor yazıldı: {out/'RAPOR.md'}", flush=True)
        return result
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        write({"event": "ERROR", "error": error})
        result = {"status": "FAILED", "mode": mode, "error": error,
                  "counters": dict(counters), "real_orders": 0}
        (out / "SONUC.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        return result
    finally:
        await session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="ACARBOT × OmniStudio PAPER motoru")
    ap.add_argument("--mode", choices=("observe", "paper", "ws"), default="observe")
    ap.add_argument("--duration", type=float, default=600)
    ap.add_argument("--strategy", choices=STRATEGIES, default="trend")
    ap.add_argument("--symbols", type=int, default=120,
                    help="PAPER/ısınma için en fazla sembol (hacme göre ilk N)")
    ap.add_argument("--per-market", type=int, default=0,
                    help="pazar başına PAPER-uygun sözleşme sınırı (0 = tümü)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    r = asyncio.run(run(Path(a.out), a.duration, a.strategy, a.mode,
                        a.per_market, a.symbols, 0))
    raise SystemExit(0 if r["status"] in {"COMPLETED", "INCOMPLETE"} else 1)


if __name__ == "__main__":
    main()
