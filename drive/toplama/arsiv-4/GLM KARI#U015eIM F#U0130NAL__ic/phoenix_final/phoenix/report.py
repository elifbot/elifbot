"""Metrikler ve katkı (attribution) analizi → Markdown rapor.

sentez-bot'un dürüstlük disiplini: kısa koşular istatistiksel olarak anlamsızdır ve
rapor bunu açıkça yazar; oy/çıkış/sembol bazlı katkılar gösterilir.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Sequence

from .models import Trade


def metrics(trades: Sequence[Trade], equity_curve: Sequence[tuple], cfg) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "not": "İşlem yok — anlamlı metrik hesaplanamaz"}
    pnls = [t.pnl for t in trades]
    rs = [t.r_mult for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp, gl = sum(wins), -sum(losses)
    # max drawdown (sermaye eğrisinden)
    max_dd = 0.0
    if equity_curve:
        peak = equity_curve[0][1]
        for _, v in equity_curve:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak * 100)
    ret = (equity_curve[-1][1] / equity_curve[0][1] - 1) * 100 if equity_curve and equity_curve[0][1] else 0.0
    return {
        "n": n,
        "kazanma_orani_pct": round(100 * len(wins) / n, 1),
        "net_pnl": round(sum(pnls), 2),
        "net_getiri_pct": round(ret, 2),
        "ort_R": round(sum(rs) / n, 3),
        "profit_factor": round(gp / gl, 2) if gl > 0 else (None if gp == 0 else math.inf),
        "ort_kazanc": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "ort_kayip": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_dd_pct": round(max_dd, 2),
        "toplam_ucret": round(sum(t.fees for t in trades), 2),
        "toplam_funding": round(sum(t.funding for t in trades), 2),
        "long_n": sum(1 for t in trades if t.side > 0),
        "short_n": sum(1 for t in trades if t.side < 0),
        "kucuk_orneklem": n < 30,
    }


def attribution(trades: Sequence[Trade]) -> dict:
    out: dict[str, dict] = {}
    by_reason: Counter[str] = Counter()
    pnl_reason: defaultdict[str, float] = defaultdict(float)
    pnl_sym: defaultdict[str, float] = defaultdict(float)
    pnl_side: defaultdict[str, float] = defaultdict(float)
    pnl_vote: defaultdict[str, float] = defaultdict(float)
    for t in trades:
        by_reason[t.reason] += 1
        pnl_reason[t.reason] += t.pnl
        pnl_sym[t.sym] += t.pnl
        pnl_side["long" if t.side > 0 else "short"] += t.pnl
        for k, v in t.votes.items():
            if v:
                pnl_vote[f"{k}{'+' if v > 0 else '-'}"] += t.pnl
    for name, c in by_reason.items():
        out[f"ci:{name}"] = {"n": c, "pnl": round(pnl_reason[name], 2)}
    for sym, p in sorted(pnl_sym.items(), key=lambda kv: kv[1]):
        out[f"sym:{sym}"] = {"pnl": round(p, 2)}
    for sd, p in pnl_side.items():
        out[f"yön:{sd}"] = {"pnl": round(p, 2)}
    top_votes = sorted(pnl_vote.items(), key=lambda kv: kv[1])[:6]
    for name, p in top_votes:
        out[f"oy:{name}"] = {"pnl": round(p, 2)}
    return out


def render_markdown(title: str, ctx: dict, m: dict, attr: dict, stats: dict,
                    trips: dict, note: str = "") -> str:
    lines = [f"# {title}", ""]
    lines += [f"- {k}: {v}" for k, v in ctx.items()]
    lines += ["", "## Metrikler", "", "| metrik | değer |", "|---|---|"]
    for k, v in m.items():
        lines.append(f"| {k} | {v} |")
    if m.get("kucuk_orneklem"):
        lines += ["", "> ⚠️ 30'dan az işlem: istatistiksel olarak ANLAMSIZ. Kanıt olarak kullanmayın."]
    if attr:
        lines += ["", "## Katkı analizi (en iyi/kötü)", "", "| kategori | bilgi |", "|---|---|"]
        for k, v in attr.items():
            lines.append(f"| {k} | {v} |")
    if trips:
        lines += ["", "## Devre kesici tetikleri", "", "| neden | sayı |", "|---|---|"]
        for k, v in sorted(trips.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v} |")
    if stats:
        interesting = {k: v for k, v in sorted(stats.items()) if not k.startswith("EVAL_") or v}
        lines += ["", "## Motor istatistikleri", "", "```", str(dict(interesting)), "```"]
    if note:
        lines += ["", f"> {note}"]
    return "\n".join(lines) + "\n"
