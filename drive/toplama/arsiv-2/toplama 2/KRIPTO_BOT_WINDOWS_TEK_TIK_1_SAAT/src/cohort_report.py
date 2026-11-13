"""Bot kapanışları ile manuel/erken kapanışları ayrı raporlar.

Manuel/erken kapanan pozisyonlar performans kohortuna katılmaz; yalnız giriş
kararını destekleyen gerçek bileşenlerle listelenir. Botun kendi kapattığı
işlemler mevcut maliyet/attribüsyon analizinin tamamını alır.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .attribution import build_session_analysis, render_session_analysis

MANUAL_CLOSE_MARKERS = (
    "SÜRELİ PAPER ÖLÇÜMÜ SONU",
    "TELEGRAM /KILL",
    "WEB PANELİ ACİL KILL-SWITCH",
    "WEB PANELİ MANUEL KAPAMA",
)


def is_manual_close(trade: dict) -> bool:
    reason = str(trade.get("reason") or "").upper()
    return any(marker in reason for marker in MANUAL_CLOSE_MARKERS)


def split_cohorts(trades: list[dict]) -> tuple[list[dict], list[dict]]:
    bot_closed = [row for row in trades if not is_manual_close(row)]
    manual_closed = [row for row in trades if is_manual_close(row)]
    return bot_closed, manual_closed


def _context(trade: dict) -> dict:
    raw = trade.get("entry_context") or {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _aligned_components(values: dict, direction: float) -> dict[str, float]:
    rows = []
    for name, value in (values or {}).items():
        try:
            contribution = float(value) * direction
        except (TypeError, ValueError):
            continue
        if contribution > 0:
            rows.append((str(name), contribution))
    return {
        name: round(contribution, 6)
        for name, contribution in sorted(
            rows, key=lambda item: abs(item[1]), reverse=True
        )
    }


def _positive_score(value, direction: float) -> float | None:
    try:
        score = float(value) * direction
    except (TypeError, ValueError):
        return None
    return round(score, 6) if score > 0 else None


def entry_rationale(trade: dict) -> dict:
    """Yalnız giriş kanıtını döndürür; çıkış fiyatı ve K/Z içermez."""
    context = _context(trade)
    side = str(trade.get("side") or context.get("side") or "").upper()
    direction = 1.0 if side == "LONG" else -1.0
    indicators = context.get("indicators") or {}
    flow = context.get("orderflow") or {}
    inputs = context.get("decision_inputs") or {}
    combined = context.get("combined") or {}
    mtf = str((context.get("mtf") or {}).get("trend") or "").upper()
    mtf_aligned = (side == "LONG" and mtf in {"BULLISH", "UP"}) or (
        side == "SHORT" and mtf in {"BEARISH", "DOWN"}
    )
    modules = {}
    for name, value in (
        ("technical_all", indicators.get("score")),
        ("orderflow_all", flow.get("score")),
        ("news_score", inputs.get("news_score")),
        ("ml_score", inputs.get("ml_score")),
    ):
        score = _positive_score(value, direction)
        if score is not None:
            modules[name] = score
    if mtf_aligned:
        modules["mtf_filter"] = mtf

    decisive = set()
    for group in (context.get("attribution") or {}).values():
        if not isinstance(group, dict):
            continue
        for name, row in group.items():
            if isinstance(row, dict) and row.get("decisive"):
                decisive.add(str(name))

    return {
        "position_id": str(trade.get("position_id") or ""),
        "symbol": str(trade.get("symbol") or ""),
        "side": side,
        "exchange": str(trade.get("exchange") or "BELİRSİZ"),
        "entry_price": float(trade.get("entry") or 0.0),
        "leverage": int(trade.get("leverage") or 0),
        "margin_usdt": float(trade.get("margin_usdt") or 0.0),
        "signal": combined.get("signal"),
        "total_score": combined.get("total"),
        "regime": combined.get("regime"),
        "technical_support": _aligned_components(
            indicators.get("active_components") or {}, direction
        ),
        "orderflow_support": _aligned_components(
            flow.get("score_components") or {}, direction
        ),
        "module_support": modules,
        "decisive_leave_one_out": sorted(decisive),
        "close_reason": str(trade.get("reason") or ""),
    }


def bot_trade_detail(trade: dict) -> dict:
    """Bot kohortundaki tek pozisyonun giriş/çıkış ve gerçekleşen maliyetlerini ver."""
    detail = entry_rationale(trade)
    gross = float(trade.get("pnl_usdt") or 0.0)
    entry_fee = float(trade.get("entry_fee_usdt") or 0.0)
    exit_fee = float(trade.get("exit_fee_usdt") or 0.0)
    funding = float(trade.get("funding_usdt") or 0.0)
    net = trade.get("net_pnl_usdt")
    detail.update(
        {
            "closed_ts": trade.get("ts"),
            "exit_price": float(trade.get("exit_price") or 0.0),
            "quantity": float(trade.get("qty") or 0.0),
            "price_pnl_pct": float(trade.get("pnl_pct") or 0.0),
            "roe_pct": float(trade.get("roe_pct") or 0.0),
            "gross_pnl_usdt": gross,
            "entry_fee_usdt": entry_fee,
            "exit_fee_usdt": exit_fee,
            "funding_usdt": funding,
            "net_pnl_usdt": (
                float(net) if net is not None else gross - entry_fee - exit_fee + funding
            ),
        }
    )
    return detail


def build_cohort_report(trades: list[dict]) -> dict:
    bot_closed, manual_closed = split_cohorts(trades)
    overall = build_session_analysis(trades)["overall"]
    return {
        "method": {
            "manual_close_markers": list(MANUAL_CLOSE_MARKERS),
            "manual": "Manuel/erken kapanışlar performans kohortundan çıkarılır; yalnız giriş kanıtı raporlanır.",
            "bot": "Botun kendi kapattığı işlemlerde maliyet, net K/Z, çıkış ve giriş bileşenleri ayrıntılıdır.",
            "reconciliation": "Genel kasa mutabakatı tüm paper kapanışlarını kapsar; bot performans kohortu değildir.",
        },
        "coverage": {
            "total_closed": len(trades),
            "bot_closed": len(bot_closed),
            "manual_closed": len(manual_closed),
        },
        "reconciliation": {
            key: overall[key]
            for key in (
                "gross_pnl_usdt",
                "entry_fee_usdt",
                "exit_fee_usdt",
                "funding_usdt",
                "net_pnl_usdt",
            )
        },
        "bot_closed_analysis": build_session_analysis(bot_closed),
        "bot_closed_trades": [bot_trade_detail(row) for row in bot_closed],
        "manual_entries": [entry_rationale(row) for row in manual_closed],
    }


def _components(values: dict) -> str:
    if not values:
        return "aktif destek kaydı yok"
    return ", ".join(
        f"{name}={value:+g}" if isinstance(value, (int, float)) else f"{name}={value}"
        for name, value in values.items()
    )


def _entry_evidence_lines(row: dict) -> list[str]:
    return [
        f"  Sinyal={row['signal'] or '—'} | "
        f"skor={row['total_score'] if row['total_score'] is not None else '—'} | "
        f"rejim={row['regime'] or '—'} | kapanış kaydı={row['close_reason'] or '—'}",
        f"  Teknik destek: {_components(row['technical_support'])}",
        f"  Order-flow destek: {_components(row['orderflow_support'])}",
        f"  Modül/MTF destek: {_components(row['module_support'])}",
        "  Leave-one-out belirleyici: "
        + (", ".join(row["decisive_leave_one_out"]) or "kayıt yok"),
    ]


def render_cohort_report(report: dict) -> str:
    coverage = report["coverage"]
    lines = [
        "🔬 BOT / MANUEL KAPANIŞ KOHORT RAPORU",
        f"Toplam={coverage['total_closed']} | Bot kapanışı={coverage['bot_closed']} | "
        f"Manuel/erken kapanış={coverage['manual_closed']}",
    ]
    reconciliation = report.get("reconciliation")
    if reconciliation:
        lines.extend(
            [
                "",
                "🧾 GENEL PAPER KASA MUTABAKATI — PERFORMANS KOHORTU DEĞİL",
                f"Brüt={reconciliation['gross_pnl_usdt']:+,.2f} USDT | "
                f"giriş ücreti={reconciliation['entry_fee_usdt']:,.2f} | "
                f"çıkış ücreti={reconciliation['exit_fee_usdt']:,.2f} | "
                f"funding={reconciliation['funding_usdt']:+,.2f} | "
                f"net={reconciliation['net_pnl_usdt']:+,.2f} USDT",
                "Tüm paper kapanışlarını kapsar; manuel/erken kapanışları bot performansına eklemez.",
            ]
        )
    session = report.get("session") or {}
    if session:
        lines.append(
            f"Başlangıç kasası={float(session.get('start_balance') or 0):,.2f} USDT | "
            f"kontrollü kapanış={'tamam' if session.get('closeout_completed') else 'tamamlanmadı'} | "
            f"açık kalan={int(session.get('closeout_open_positions') or 0)}"
        )
    lines.extend(
        [
            "",
            "🤖 BOTUN KENDİ KAPATTIĞI İŞLEMLER — AYRINTILI ANALİZ",
            render_session_analysis(report["bot_closed_analysis"]),
            "",
            "🧾 BOTUN KAPATTIĞI POZİSYONLAR — TEK TEK GİRİŞ/ÇIKIŞ VE GİRİŞ KANITI",
        ]
    )
    bot_rows = report.get("bot_closed_trades") or []
    if not bot_rows:
        lines.append("• Bot kapanışı yok.")
    for row in bot_rows:
        lines.extend(
            [
                f"• {row['position_id'] or 'ID-YOK'} | {row['symbol']} {row['side']} "
                f"[{row['exchange']}] | giriş={row['entry_price']:,.8g} | "
                f"çıkış={row['exit_price']:,.8g} | {row['leverage']}x / "
                f"${row['margin_usdt']:,.2f} marj",
                f"  Brüt={row['gross_pnl_usdt']:+,.2f} | "
                f"giriş ücreti={row['entry_fee_usdt']:,.4f} | "
                f"çıkış ücreti={row['exit_fee_usdt']:,.4f} | "
                f"funding={row['funding_usdt']:+,.4f} | "
                f"net={row['net_pnl_usdt']:+,.2f} USDT | ROE={row['roe_pct']:+.2f}%",
                *_entry_evidence_lines(row),
            ]
        )
    lines.extend(
        [
            "",
            "🧭 MANUEL/ERKEN KAPANANLAR — YALNIZ GİRİŞ KANITI",
            "Bu satırlar bot performans kohortuna dahil değildir; K/Z ve çıkış performansı bu bölümde değerlendirilmez.",
        ]
    )
    if not report["manual_entries"]:
        lines.append("• Manuel/erken kapanış yok.")
    for row in report["manual_entries"]:
        lines.extend(
            [
                f"• {row['position_id'] or 'ID-YOK'} | {row['symbol']} {row['side']} "
                f"[{row['exchange']}] | giriş={row['entry_price']:,.8g} | "
                f"{row['leverage']}x / ${row['margin_usdt']:,.2f} marj",
                *_entry_evidence_lines(row),
            ]
        )
    lines.append(
        "⚠️ Aktif katkı kohortları örtüşür; leave-one-out belirleyiciliği ayrıdır. "
        "Tek oturum nedensellik veya otomatik parametre değişikliği gerekçesi değildir."
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trades_json", type=Path)
    parser.add_argument("--analysis", type=Path, help="Mevcut oturum_analizi JSON'u")
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    trades = json.loads(args.trades_json.read_text(encoding="utf-8"))
    report = build_cohort_report(trades)
    if args.analysis:
        existing = json.loads(args.analysis.read_text(encoding="utf-8"))
        report["session"] = existing.get("session")
        report["bot_closed_analysis"]["exchange_evidence"] = existing.get(
            "exchange_evidence", {}
        )
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    text = render_cohort_report(report)
    args.output_prefix.with_suffix(".md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
