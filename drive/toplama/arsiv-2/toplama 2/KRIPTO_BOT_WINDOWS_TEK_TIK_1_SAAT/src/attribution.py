"""Giriş bileşeni attribüsyonu ve süreli paper oturumu analizi.

Leave-one-out yalnız gerçekten açılmış pozisyonlarda, işlem sonrası hesaplanır;
canlı tarama/sinyal davranışını değiştirmez. Performans kohortları ilişkidir,
tek oturumdan nedensellik veya otomatik parametre kararı çıkarılmaz.
"""
from __future__ import annotations

import json
from collections import defaultdict


TECHNICAL_COMPONENTS = (
    "ema_trend", "ma_trend", "rsi", "macd", "bollinger", "stoch_rsi",
    "williams_r", "adx", "cci", "mfi", "obv", "vwap", "donchian",
    "funding", "supertrend", "session_vwap", "anchored_vwap",
    "volume_profile", "confirmed_breakout",
)
ORDERFLOW_COMPONENTS = (
    "taker_delta", "cvd_direction", "whale_balance", "orderbook_depth",
    "oi_liquidation", "volume_spike",
)
MODULE_COMPONENTS = (
    "technical_all", "orderflow_all", "news_score", "ml_score", "mtf_filter",
)
ALL_COMPONENTS = TECHNICAL_COMPONENTS + ORDERFLOW_COMPONENTS + MODULE_COMPONENTS


def _clip(value: float) -> float:
    return max(-100.0, min(100.0, float(value)))


def _market_context(context: dict) -> dict:
    indicators = context.get("indicators") or {}
    flow = context.get("orderflow") or {}
    return {
        **indicators,
        "cvd_slope": flow.get("cvd_slope", 0.0),
        "cvd_divergence": flow.get("cvd_divergence", "YOK"),
        "absorption": flow.get("absorption", "YOK"),
        "oi_signal": flow.get("oi_signal", "NOTR"),
        "oi_change_pct": flow.get("oi_change_pct", 0.0),
        "price_change_pct": flow.get("price_change_pct", 0.0),
    }


def build_entry_attribution(strategy, context: dict, side: str) -> dict:
    """Aynı filtrelerle her aktif katkıyı çıkarıp giriş kararını yeniden hesapla."""
    indicators = context.get("indicators") or {}
    orderflow = context.get("orderflow") or {}
    inputs = context.get("decision_inputs") or {}
    ind_score = float(indicators.get("score", 0.0) or 0.0)
    flow_score = float(orderflow.get("score", 0.0) or 0.0)
    news_score = float(inputs.get("news_score", 0.0) or 0.0)
    ml_score = inputs.get("ml_score")
    mtf = context.get("mtf")
    market_context = _market_context(context)

    def evaluate(ind=None, flow=None, news=None, ml="unchanged", mtf_value="unchanged"):
        combined = strategy.combine(
            ind_score if ind is None else ind,
            flow_score if flow is None else flow,
            news_score if news is None else news,
            ml_score if ml == "unchanged" else ml,
            market_context=market_context,
        )
        decision = strategy.entry_decision(
            combined,
            bool(inputs.get("veto")),
            has_position=False,
            veto_long=bool(inputs.get("veto_long")),
            veto_short=bool(inputs.get("veto_short")),
            mtf_trend=mtf if mtf_value == "unchanged" else mtf_value,
        )
        return decision, combined

    def row(contribution, decision, combined):
        return {
            "contribution": round(float(contribution), 6),
            "decisive": decision.get("action") != side,
            "without_action": decision.get("action"),
            "without_signal": combined.get("signal"),
            "without_total": combined.get("total"),
        }

    result: dict[str, dict] = {"technical": {}, "orderflow": {}, "modules": {}}
    active = indicators.get("active_components") or {}
    active_unclipped = indicators.get("active_score_unclipped")
    if active and active_unclipped is not None:
        for name, contribution in active.items():
            reduced = _clip(float(active_unclipped) - float(contribution))
            decision, combined = evaluate(ind=reduced)
            result["technical"][name] = row(contribution, decision, combined)

    flow_components = orderflow.get("score_components") or {}
    flow_unclipped = orderflow.get("score_unclipped")
    if flow_components and flow_unclipped is not None:
        for name, contribution in flow_components.items():
            reduced = round(_clip(float(flow_unclipped) - float(contribution)), 1)
            decision, combined = evaluate(flow=reduced)
            result["orderflow"][name] = row(contribution, decision, combined)

    module_tests = {
        "technical_all": {"ind": 0.0, "contribution": ind_score},
        "orderflow_all": {"flow": 0.0, "contribution": flow_score},
        "news_score": {"news": 0.0, "contribution": news_score},
        "ml_score": {
            "ml": 0.0 if ml_score is not None else None,
            "contribution": float(ml_score or 0.0),
        },
        "mtf_filter": {"mtf_value": None, "contribution": 0.0},
    }
    for name, kwargs in module_tests.items():
        contribution = kwargs.pop("contribution")
        decision, combined = evaluate(**kwargs)
        result["modules"][name] = row(contribution, decision, combined)
    return result


def _context(trade: dict) -> dict:
    raw = trade.get("entry_context") or {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _net(trade: dict) -> float:
    if trade.get("net_pnl_usdt") is not None:
        return float(trade.get("net_pnl_usdt") or 0.0)
    return (
        float(trade.get("pnl_usdt", 0.0) or 0.0)
        - float(trade.get("entry_fee_usdt", 0.0) or 0.0)
        - float(trade.get("exit_fee_usdt", 0.0) or 0.0)
        + float(trade.get("funding_usdt", 0.0) or 0.0)
    )


def _stats(rows: list[dict]) -> dict:
    nets = [_net(row) for row in rows]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    positive = sum(wins)
    negative = -sum(losses)
    return {
        "count": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(rows) - len(wins) - len(losses),
        "win_rate_pct": 100.0 * len(wins) / len(rows) if rows else 0.0,
        "gross_pnl_usdt": sum(float(row.get("pnl_usdt", 0.0) or 0.0) for row in rows),
        "entry_fee_usdt": sum(float(row.get("entry_fee_usdt", 0.0) or 0.0) for row in rows),
        "exit_fee_usdt": sum(float(row.get("exit_fee_usdt", 0.0) or 0.0) for row in rows),
        "funding_usdt": sum(float(row.get("funding_usdt", 0.0) or 0.0) for row in rows),
        "net_pnl_usdt": sum(nets),
        "profit_factor": positive / negative if negative > 0 else None,
    }


def _group(rows: list[dict], key) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(key(row))].append(row)
    return {name: _stats(group) for name, group in sorted(groups.items())}


def exit_module_name(reason) -> str:
    """Dinamik kapanış nedenlerini aynı rapor modülü altında gruplandırır."""
    text = str(reason or "BELİRSİZ")
    if text.startswith("KÂR KOŞUSU:"):
        return "KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ"
    return text


def build_session_analysis(trades: list[dict]) -> dict:
    aligned: dict[str, list[dict]] = {name: [] for name in ALL_COMPONENTS}
    decisive: dict[str, list[dict]] = {name: [] for name in ALL_COMPONENTS}
    attribution_coverage = 0
    for trade in trades:
        context = _context(trade)
        side = str(trade.get("side") or context.get("side") or "")
        direction = 1.0 if side == "LONG" else -1.0
        indicators = context.get("indicators") or {}
        flow = context.get("orderflow") or {}
        inputs = context.get("decision_inputs") or {}
        for name, value in (indicators.get("active_components") or {}).items():
            if name in aligned and float(value) * direction > 0:
                aligned[name].append(trade)
        for name, value in (flow.get("score_components") or {}).items():
            if name in aligned and float(value) * direction > 0:
                aligned[name].append(trade)
        if float(indicators.get("score", 0.0) or 0.0) * direction > 0:
            aligned["technical_all"].append(trade)
        if float(flow.get("score", 0.0) or 0.0) * direction > 0:
            aligned["orderflow_all"].append(trade)
        if float(inputs.get("news_score", 0.0) or 0.0) * direction > 0:
            aligned["news_score"].append(trade)
        if float(inputs.get("ml_score", 0.0) or 0.0) * direction > 0:
            aligned["ml_score"].append(trade)
        mtf = str((context.get("mtf") or {}).get("trend", "")).upper()
        if (side == "LONG" and mtf in {"BULLISH", "UP"}) or (
            side == "SHORT" and mtf in {"BEARISH", "DOWN"}
        ):
            aligned["mtf_filter"].append(trade)

        attribution = context.get("attribution") or {}
        if attribution:
            attribution_coverage += 1
        for group in attribution.values():
            if not isinstance(group, dict):
                continue
            for name, row in group.items():
                if name in decisive and row.get("decisive"):
                    decisive[name].append(trade)

    return {
        "method": {
            "aligned": "Açılan yönle aynı işaretli aktif skor katkısı bulunan işlemler; kohortlar örtüşür ve satırlar toplanmaz; ilişki, nedensellik değil.",
            "decisive": "Bileşen çıkarılınca aynı yönde giriş kararı oluşmayan işlemler (leave-one-out).",
            "net": "Brüt fiyat K/Z - gerçekleşen giriş ücreti - gerçekleşen çıkış ücreti + funding (alacak + / ödeme -).",
            "minimum_sample": 5,
        },
        "coverage": {
            "closed_trades": len(trades),
            "with_attribution": attribution_coverage,
            "with_exchange": sum(bool(row.get("exchange")) for row in trades),
        },
        "overall": _stats(trades),
        "exchanges": _group(trades, lambda row: row.get("exchange") or "BELİRSİZ"),
        "exit_modules": _group(trades, lambda row: exit_module_name(row.get("reason"))),
        "aligned_components": {name: _stats(aligned[name]) for name in ALL_COMPONENTS},
        "decisive_components": {name: _stats(decisive[name]) for name in ALL_COMPONENTS},
    }


def _money(value: float) -> str:
    return f"${value:+,.2f}"


def _pf(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _verdict(row: dict) -> str:
    if row["count"] < 5:
        return "YETERSİZ VERİ"
    if row["net_pnl_usdt"] > 0:
        return "OLUMLU İLİŞKİ"
    if row["net_pnl_usdt"] < 0:
        return "OLUMSUZ İLİŞKİ"
    return "NÖTR"


def _table(title: str, table: dict[str, dict]) -> list[str]:
    lines = [title]
    for name, row in table.items():
        if not row["count"]:
            lines.append(f"• {name}: veri yok")
            continue
        lines.append(
            f"• {name} | n={row['count']} | kazanma=%{row['win_rate_pct']:.1f} | "
            f"brüt={_money(row['gross_pnl_usdt'])} | "
            f"ücret={_money(row['entry_fee_usdt'] + row['exit_fee_usdt'])} | "
            f"funding={_money(row['funding_usdt'])} | net={_money(row['net_pnl_usdt'])} | "
            f"PF={_pf(row['profit_factor'])} | {_verdict(row)}"
        )
    return lines


def render_session_analysis(analysis: dict) -> str:
    overall = analysis["overall"]
    evidence = analysis.get("exchange_evidence") or {}
    evidence_lines: list[str] = []
    if evidence:
        catalog = evidence.get("catalog") or {}
        rest = evidence.get("rest") or {}
        websocket = evidence.get("websocket") or {}
        evidence_lines.append("🛰️ BORSA VERİ / PAPER FILL KANITI")
        for name in sorted(set(catalog) | set(rest) | set(websocket)):
            rest_row = rest.get(name) or {}
            ws_row = websocket.get(name) or {}
            evidence_lines.append(
                f"• {str(name).upper()} | katalog={int(catalog.get(name, 0) or 0)} | "
                f"OHLCV +{int(rest_row.get('ohlcv_success', 0) or 0)}/"
                f"-{int(rest_row.get('ohlcv_errors', 0) or 0)} | "
                f"WS trade/book={int(ws_row.get('trade_messages', 0) or 0)}/"
                f"{int(ws_row.get('book_messages', 0) or 0)} | "
                f"paper fill={int(rest_row.get('paper_fills', 0) or 0)}"
            )
        for name, error in (evidence.get("errors") or {}).items():
            evidence_lines.append(f"• {str(name).upper()} erişim hatası: {error}")
        evidence_lines.append("")
    lines = [
        "🧪 OTURUM BİLEŞEN / MALİYET ANALİZİ",
        f"Kapanan={overall['count']} | Net kazanma=%{overall['win_rate_pct']:.1f} | "
        f"Brüt={_money(overall['gross_pnl_usdt'])} | "
        f"Ücret={_money(overall['entry_fee_usdt'] + overall['exit_fee_usdt'])} | "
        f"Funding={_money(overall['funding_usdt'])} | Net={_money(overall['net_pnl_usdt'])} | "
        f"PF={_pf(overall['profit_factor'])}",
        f"Leave-one-out kapsama: {analysis['coverage']['with_attribution']}/{analysis['coverage']['closed_trades']}",
        "",
        *evidence_lines,
        *_table("🏦 BORSA BAZINDA GERÇEKLEŞEN SONUÇ", analysis["exchanges"]),
        "",
        *_table("🚪 ÇIKIŞ MODÜLLERİ (giriş bileşenlerinden ayrı)", analysis["exit_modules"]),
        "",
        *_table("📈 YÖNLE UYUMLU AKTİF GİRİŞ BİLEŞENLERİ", analysis["aligned_components"]),
        "",
        *_table("🎯 BELİRLEYİCİ BİLEŞENLER — LEAVE-ONE-OUT", analysis["decisive_components"]),
        "",
        "⚠️ Bileşen kohortları örtüşür; satırlar birbirine eklenmez. Bunlar tek oturumluk gözlemsel ilişkilerdir; nedensellik kanıtı veya otomatik parametre değişikliği gerekçesi değildir.",
    ]
    return "\n".join(lines)
