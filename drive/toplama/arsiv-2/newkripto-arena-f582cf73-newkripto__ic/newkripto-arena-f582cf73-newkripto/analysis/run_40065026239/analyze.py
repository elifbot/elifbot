"""Run 40065026239 için tekrar üretilebilir, UUID bazlı paper log analizi.

Bu betik yalnız kurtarılmış logu okur; borsa/telegram erişimi yapmaz ve eksik
mark-to-market verisini tahmin etmez. Çıktılar aynı dizine yazılır.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "paper-session.txt"
lines = LOG.read_text(encoding="utf-8").splitlines()


def num(value: str) -> float:
    return float(value.replace(",", ""))


def finite(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def reason_group(reason: str) -> str:
    if reason.startswith("KÂR KOŞUSU"):
        return "Order-flow / CVD kâr çıkışı"
    if reason == "TRAILING STOP":
        return "Trailing stop"
    if reason.startswith("STOP-LOSS"):
        return "Başlangıç koruyucu stopu"
    if "ÇAPRAZ KURTARMA" in reason:
        return "Çapraz kurtarma"
    return reason


def score_bin(score: float) -> str:
    value = abs(score)
    if value < 20:
        return "0–19.9"
    if value < 30:
        return "20–29.9"
    if value < 40:
        return "30–39.9"
    if value < 50:
        return "40–49.9"
    return "50+"


def pnl_stats(rows: list[dict]) -> dict:
    values = [finite(row.get("gross_pnl")) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "count": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(rows) - len(wins) - len(losses),
        "win_rate_pct": 100 * len(wins) / len(rows) if rows else 0.0,
        "gross_pnl_usdt": sum(values),
        "gross_profit_usdt": gross_profit,
        "gross_loss_usdt": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "avg_pnl_usdt": mean(values) if values else 0.0,
        "median_pnl_usdt": median(values) if values else 0.0,
    }


def grouped(rows: list[dict], key) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        value = key(row) if callable(key) else row.get(key)
        groups[str(value)].append(row)
    return {name: pnl_stats(group) for name, group in sorted(groups.items())}


entry_re = re.compile(
    r"^🧾 GİRİŞ VERİSİ \| (?P<position_id>[0-9a-f]+) \| "
    r"(?P<symbol>\S+) \| (?P<context>\{.*\})$"
)
open_re = re.compile(
    r"^🟢 (?P<side>LONG|SHORT) AÇILDI \| (?P<symbol>\S+) @ "
    r"(?P<entry>[\d,]+(?:\.\d+)?) \| .*?\| Emir: (?P<order_type>[^|]+) \| "
    r".*?\| Neden: skor (?P<score>[+-]?[\d.]+) \| tetik: (?P<trigger>\S+)"
)
close_data_re = re.compile(
    r"^🧾 KAPANIŞ VERİSİ \| (?P<position_id>[0-9a-f]+) \| "
    r"(?P<symbol>\S+) \| (?P<reason>.*?) \| gerçekleşen miktar="
    r"(?P<quantity>[\d.eE+-]+) \| brüt K/Z=\$(?P<gross>[+-]?[\d,]+(?:\.\d+)?)"
)
close_re = re.compile(
    r"^[✅🔴] POZİSYON KAPANDI \| (?P<side>LONG|SHORT) (?P<symbol>\S+) .*?"
    r"@ (?P<exit>[\d,]+(?:\.\d+)?) \| Fiyat PnL: %(?P<pnl_pct>[+-]?[\d.]+) .*?"
    r"ROE: %(?P<roe>[+-]?[\d.]+) \| Fiyat K/Z: \$(?P<gross>[+-]?[\d,]+(?:\.\d+)?)"
)
heartbeat_re = re.compile(
    r"^💓 (?P<minute>\d+)dk .*?açık=(?P<open>\[.*\]) \| Futures="
    r"(?P<universe>\d+) parite, fiyat akışı=(?P<priced>\d+) \| "
    r"istatistik=(?P<stats>\{.*\})$"
)
cash_re = re.compile(r"^💰 Kasa \(paper\): \$(?P<cash>[\d,]+(?:\.\d+)?)")

entries: list[dict] = []
entries_by_id: dict[str, dict] = {}
opens: list[dict] = []
closes: list[dict] = []
heartbeats: list[dict] = []
last_heartbeat: dict = {}
cash_final = None
pending_close = None

for line_no, line in enumerate(lines, 1):
    match = entry_re.match(line)
    if match:
        context = json.loads(match.group("context"))
        row = {
            "position_id": match.group("position_id"),
            "symbol": match.group("symbol"),
            "entry_line": line_no,
            "context": context,
            "side": context.get("side"),
            "signal_price": finite(context.get("entry_price")),
            "score": finite((context.get("combined") or {}).get("total")),
            "trigger": str(context.get("entry_reason", "")).split("tetik: ")[-1],
            "regime": (context.get("combined") or {}).get("regime"),
            "orderflow_verdict": (context.get("orderflow") or {}).get("verdict"),
            "mtf_trend": (context.get("mtf") or {}).get("trend"),
            "ml_direction": (context.get("ml") or {}).get("direction"),
            "ml_score": finite((context.get("ml") or {}).get("score")),
            "news_veto": bool((context.get("news") or {}).get("veto")),
        }
        entries.append(row)
        entries_by_id[row["position_id"]] = row
        continue

    match = open_re.match(line)
    if match:
        # GİRİŞ VERİSİ hemen önce gelir; sembol ve henüz eşleşmemiş kayıt
        # üzerinden fill bilgisini UUID'ye bağlarız.
        candidates = [
            row for row in entries
            if row["symbol"] == match.group("symbol") and "open_line" not in row
        ]
        row = candidates[-1] if candidates else None
        rec = {
            "symbol": match.group("symbol"),
            "side": match.group("side"),
            "entry_fill": num(match.group("entry")),
            "order_type": match.group("order_type").strip(),
            "score": float(match.group("score")),
            "trigger": match.group("trigger"),
            "open_line": line_no,
            "position_id": row["position_id"] if row else None,
        }
        opens.append(rec)
        if row is not None:
            row.update(rec)
        continue

    match = close_data_re.match(line)
    if match:
        pending_close = {
            "position_id": match.group("position_id"),
            "symbol": match.group("symbol"),
            "reason": match.group("reason"),
            "reason_group": reason_group(match.group("reason")),
            "quantity": float(match.group("quantity")),
            "gross_pnl": num(match.group("gross")),
            "close_data_line": line_no,
        }
        closes.append(pending_close)
        continue

    match = close_re.match(line)
    if match and pending_close is not None:
        pending_close.update(
            {
                "side": match.group("side"),
                "exit_fill": num(match.group("exit")),
                "price_pnl_pct": float(match.group("pnl_pct")),
                "roe_pct": float(match.group("roe")),
                "close_line": line_no,
            }
        )
        entry = entries_by_id.get(pending_close["position_id"])
        if entry is not None:
            pending_close["entry"] = {
                key: value for key, value in entry.items() if key != "context"
            }
            pending_close["entry_context"] = entry["context"]
        pending_close = None
        continue

    match = heartbeat_re.match(line)
    if match:
        stats = ast.literal_eval(match.group("stats"))
        row = {
            "minute": int(match.group("minute")),
            "open_symbols": ast.literal_eval(match.group("open")),
            "universe": int(match.group("universe")),
            "priced": int(match.group("priced")),
            "stats": stats,
            "line": line_no,
        }
        heartbeats.append(row)
        last_heartbeat = row
        continue

    match = cash_re.match(line)
    if match:
        cash_final = num(match.group("cash"))

closed_ids = [row["position_id"] for row in closes]
closed_id_set = set(closed_ids)
duplicate_close_ids = sorted(pid for pid, count in Counter(closed_ids).items() if count > 1)
primary_closes = []
seen_close_ids = set()
for row in closes:
    if row["position_id"] not in seen_close_ids:
        primary_closes.append(row)
        seen_close_ids.add(row["position_id"])

# Bu run'da UUID'ler bir kez kapanmalı. Aynı UUID'nin tekrarını bağımsız
# işlem olarak saymıyoruz; açık-kapalı mutabakatını da ayrıca raporluyoruz.
open_entries = [row for row in entries if row["position_id"] not in closed_id_set]
final_open_symbols = last_heartbeat.get("open_symbols", [])
reported_stats = last_heartbeat.get("stats", {})
start_cash = 100000.0
gross_realized = sum(finite(row.get("gross_pnl")) for row in primary_closes)
funding = finite(reported_stats.get("funding_usdt"))
fees_implied = (
    start_cash + gross_realized + funding - cash_final
    if cash_final is not None else None
)

# Yalnız model tabanlı ücret kontrolü; kesin ücret bakiyeden türetilen
# fees_implied değeridir. Açık pozisyonların giriş ücretleri de buna dahildir.
estimated_close_fees = sum(
    finite(row.get("quantity")) * finite(row.get("exit_fill")) * 0.05 / 100
    for row in primary_closes
)
estimated_entry_fees_all = len(entries) * 50.0 * 10.0 * 0.02 / 100
estimated_entry_fees_closed = len(primary_closes) * 50.0 * 10.0 * 0.02 / 100

# Kapanan işlemlerin bağlamını kompakt, modül bazında karşılaştırılabilir yap.
closed_context = []
for row in primary_closes:
    context = row.get("entry_context") or {}
    indicators = context.get("indicators") or {}
    closed_context.append(
        {
            "position_id": row["position_id"],
            "symbol": row["symbol"],
            "side": row.get("side"),
            "reason_group": row["reason_group"],
            "gross_pnl_usdt": row["gross_pnl"],
            "score": finite((context.get("combined") or {}).get("total")),
            "regime": (context.get("combined") or {}).get("regime"),
            "components": indicators.get("components") or {},
            "rsi": indicators.get("rsi"),
            "adx": indicators.get("adx"),
            "macd_hist": indicators.get("macd_hist"),
            "supertrend_direction": indicators.get("supertrend_direction"),
            "orderflow": context.get("orderflow") or {},
            "mtf": context.get("mtf") or {},
            "ml": context.get("ml") or {},
            "news": context.get("news") or {},
        }
    )

summary = {
    "run_id": 40065026239,
    "run_url": "https://github.com/omeracar56/kripto-bot/actions/runs/40065026239",
    "head_sha": "44af9491f1ab218f03abcb4ac5d017fcf5664f6a",
    "source_log": str(LOG.relative_to(ROOT.parent.parent)),
    "log_lines": len(lines),
    "planned_minutes": 60,
    "entries": len(entries),
    "standard_open_records": len(opens),
    "unique_entry_ids": len(entries_by_id),
    "close_records": len(closes),
    "primary_closes": len(primary_closes),
    "duplicate_close_records": len(closes) - len(primary_closes),
    "duplicate_close_ids": duplicate_close_ids,
    "unmatched_close_ids": sorted(closed_id_set - set(entries_by_id)),
    "open_positions_derived": len(open_entries),
    "open_positions_heartbeat": len(final_open_symbols),
    "open_symbols": final_open_symbols,
    "open_symbols_not_derived": sorted(set(final_open_symbols) - {row["symbol"] for row in open_entries}),
    "derived_symbols_not_open": sorted({row["symbol"] for row in open_entries} - set(final_open_symbols)),
    "universe": last_heartbeat.get("universe"),
    "priced_symbols": last_heartbeat.get("priced"),
    "exchange_scope": {
        "catalog": "OKX=507",
        "binance": "HTTP 451; katalog ve kontrat metaverisi yok",
        "interpretation": "OKX-only fiili evren; iki borsa başarılı testi değil",
        "heartbeat_primary_label": "BINANCE (etiket; katalog kapsamıyla karıştırılmamalı)",
    },
    "closed_stats": pnl_stats(primary_closes),
    "closed_by_side": grouped(primary_closes, "side"),
    "closed_by_reason": grouped(primary_closes, "reason_group"),
    "closed_by_score_bin": grouped(primary_closes, lambda row: score_bin(finite((row.get("entry") or {}).get("score")))),
    "entry_cohort": {
        "by_side": dict(Counter(row.get("side") for row in entries)),
        "by_regime": dict(Counter(row.get("regime") for row in entries)),
        "by_trigger": dict(Counter(row.get("trigger") for row in entries)),
        "by_score_bin": dict(Counter(score_bin(row["score"]) for row in entries)),
        "by_mtf_trend": dict(Counter(row.get("mtf_trend") for row in entries)),
        "by_ml_direction": dict(Counter(row.get("ml_direction") for row in entries)),
        "news_veto_count": sum(row["news_veto"] for row in entries),
    },
    "reported_final_stats": reported_stats,
    "cash_reconciliation": {
        "start_cash_usdt": start_cash,
        "final_cash_usdt": cash_final,
        "cash_change_usdt": cash_final - start_cash if cash_final is not None else None,
        "realized_gross_pnl_usdt": gross_realized,
        "funding_usdt": funding,
        "fees_implied_usdt": fees_implied,
        "formula": "final_cash = start_cash + gross_realized + funding - fees",
        "includes_open_position_entry_fees": True,
        "open_unrealized_pnl_available_in_log": False,
        "net_equity_pnl_available_in_log": False,
        "note": "Kasa değişimi özsermaye K/Z değildir; 74 açık pozisyonun gerçekleşmemiş K/Z'si log gövdesinde yok.",
    },
    "fee_model_check": {
        "maker_pct": 0.02,
        "taker_pct": 0.05,
        "estimated_all_entry_fees_usdt": estimated_entry_fees_all,
        "estimated_closed_entry_fees_usdt": estimated_entry_fees_closed,
        "estimated_close_fees_usdt": estimated_close_fees,
        "estimated_total_fees_usdt": estimated_entry_fees_all + estimated_close_fees,
        "implied_minus_model_usdt": fees_implied - estimated_entry_fees_all - estimated_close_fees if fees_implied is not None else None,
        "closed_net_before_funding_estimate_usdt": gross_realized - estimated_entry_fees_closed - estimated_close_fees,
        "funding_allocation_to_closed_trades_available": False,
    },
    "operational_counters": {
        key: reported_stats.get(key)
        for key in (
            "trades", "wins", "losses", "pyramids", "pair_rescues", "chase_orders",
            "tp1_partial_closes", "tp2_closes", "runner_orderflow_exits",
            "supertrend_trail_updates", "orderflow_filtered", "mtf_filtered",
        )
    },
    "holding_minutes_available": False,
    "closed_trade_contexts": closed_context,
    "open_entries": [
        {key: value for key, value in row.items() if key != "context"}
        for row in open_entries
    ],
}

# JSON'da ham context'i iki kez şişirmeden bağımsız trade ayrıntısını sakla.
serializable_closes = []
for row in primary_closes:
    serializable_closes.append({key: value for key, value in row.items() if key != "entry_context"})

(ROOT / "analysis.json").write_text(
    json.dumps({"summary": summary, "primary_trades": serializable_closes}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(ROOT / "summary_full.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
