"""Metrikler, sinyal katkı analizi (attribution) ve Markdown rapor. Kârlılık iddiası üretmez."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence

from .models import Config, Trade
from .signals import VOTE_NAMES

MIN_TRADES_FOR_SIGNIFICANCE = 30


def max_drawdown_pct(curve: Sequence[tuple[int, float]], start: float) -> float:
    peak, dd = start, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak * 100.0)
    return dd


def metrics(trades: Sequence[Trade], curve: Sequence[tuple[int, float]], cfg: Config) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "note": "işlem yok"}
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gp, gl = sum(t.pnl for t in wins), -sum(t.pnl for t in losses)
    pnl = sum(t.pnl for t in trades)
    rs = [t.r_mult for t in trades]
    mean_r = sum(rs) / n
    sd_r = math.sqrt(sum((x - mean_r) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    out = {
        "trades": n,
        "win_rate_pct": round(len(wins) / n * 100, 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "expectancy_r": round(mean_r, 4),
        "expectancy_usd": round(pnl / n, 4),
        "net_pnl_usd": round(pnl, 2),
        "return_pct": round(pnl / cfg.equity * 100, 2),
        "avg_win_usd": round(gp / len(wins), 4) if wins else 0.0,
        "avg_loss_usd": round(-gl / len(losses), 4) if losses else 0.0,
        "fees_usd": round(sum(t.fees for t in trades), 2),
        "funding_usd": round(sum(t.funding for t in trades), 2),
        "r_stdev": round(sd_r, 3),
        "t_stat_r": round(mean_r / (sd_r / math.sqrt(n)), 2) if sd_r > 0 else None,
        "avg_bars_held": round(sum(t.bars for t in trades) / n, 1),
        "significant": n >= MIN_TRADES_FOR_SIGNIFICANCE,
    }
    if curve:
        out["max_drawdown_pct"] = round(max_drawdown_pct(curve, cfg.equity), 2)
    return out


def _agg(ts: Sequence[Trade]) -> dict:
    n = len(ts)
    if not n:
        return {"n": 0}
    return {"n": n, "win_pct": round(sum(1 for t in ts if t.pnl > 0) / n * 100, 1),
            "avg_r": round(sum(t.r_mult for t in ts) / n, 3),
            "pnl": round(sum(t.pnl for t in ts), 2)}


def attribution(trades: Sequence[Trade]) -> dict:
    """Hangi oy / çıkış / sembol / yön nasıl sonuç verdi? (İlişki gösterir, nedensellik değil.)"""
    by_vote = {}
    for name in VOTE_NAMES:
        agree = [t for t in trades if t.votes.get(name, 0) == t.side]
        other = [t for t in trades if t.votes.get(name, 0) != t.side]
        by_vote[name] = {"hemfikir": _agg(agree), "değil": _agg(other)}
    groups: dict[str, dict[str, list[Trade]]] = {"exit": defaultdict(list), "symbol": defaultdict(list),
                                                 "side": defaultdict(list)}
    for t in trades:
        groups["exit"][t.reason].append(t)
        groups["symbol"][t.sym].append(t)
        groups["side"]["long" if t.side > 0 else "short"].append(t)
    return {"vote": by_vote,
            **{k: {name: _agg(v) for name, v in g.items()} for k, g in groups.items()}}


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def render_markdown(title: str, meta: dict, m: dict, attr: dict, stats: dict, trips: dict,
                    wf: dict | None = None) -> str:
    L = [f"# {title}", "", "> **PAPER** · gerçek emir yok · özel API anahtarı yok. "
         "Bu rapor kârlılık kanıtı DEĞİLDİR.", ""]
    L += ["## Koşu", *[f"- **{k}:** {v}" for k, v in meta.items()], ""]
    L += ["## Sonuç"]
    if m.get("trades", 0) == 0:
        L += ["İşlem açılmadı. Nedenler aşağıdaki ret sayaçlarında.", ""]
    else:
        for k, v in m.items():
            L.append(f"- {k}: {v}")
        if not m.get("significant"):
            L += ["", f"**UYARI:** {m['trades']} işlem < {MIN_TRADES_FOR_SIGNIFICANCE}; sonuçlar "
                  "istatistiksel olarak anlamsızdır (KISMİ)."]
        L.append("")
    if stats:
        rej = {k[7:]: v for k, v in stats.items() if k.startswith("REJECT_")}
        ev = {k[5:]: v for k, v in stats.items() if k.startswith("EVAL_")}
        L += ["## Karar hunisi", f"- Değerlendirmeler: {ev}", f"- Üretilen sinyal: {stats.get('SIGNALS', 0)}",
              f"- Açılan pozisyon: {stats.get('OPENED', 0)}", f"- Ret nedenleri: {rej or 'yok'}",
              f"- Devre kesici: {trips or 'tetiklenmedi'}", ""]
    if attr and m.get("trades", 0):
        L += ["## Katkı analizi (ilişki, nedensellik değil)", "", "| Oy | hemfikir n | ort. R | değil n | ort. R |",
              "|---|---:|---:|---:|---:|"]
        for name, d in attr["vote"].items():
            a, o = d["hemfikir"], d["değil"]
            L.append(f"| {name} | {a['n']} | {a.get('avg_r', '-')} | {o['n']} | {o.get('avg_r', '-')} |")
        for key, title2 in (("exit", "Çıkış nedeni"), ("side", "Yön"), ("symbol", "Sembol")):
            L += ["", f"### {title2}", "| ad | n | kazanç % | ort. R | PnL |", "|---|---:|---:|---:|---:|"]
            for name, d in sorted(attr[key].items()):
                L.append(f"| {name} | {d['n']} | {d['win_pct']} | {d['avg_r']} | {d['pnl']} |")
        L.append("")
    if wf:
        L += ["## Walk-forward (örneklem-dışı)", f"- Fold sayısı: {wf['n_folds']}",
              f"- OOS (seçilen ayarlar): {wf['oos']}", f"- OOS (sabit varsayılan): {wf['baseline_oos']}", "",
              "| fold | seçilen ayar | OOS işlem | OOS ort. R | sabit ayar ort. R |", "|---:|---|---:|---:|---:|"]
        for i, f in enumerate(wf["folds"], 1):
            L.append(f"| {i} | {f['chosen']} | {f['test'].get('trades', 0)} | "
                     f"{f['test'].get('expectancy_r', '-')} | {f['baseline'].get('expectancy_r', '-')} |")
        o, b = wf["oos"].get("expectancy_r"), wf["baseline_oos"].get("expectancy_r")
        if o is None or b is None:
            verdict = "Karşılaştırma için yeterli işlem yok."
        elif o <= b:
            verdict = ("Seçilen ayarlar sabit varsayılandan **daha iyi değil**: parametre araması bu veride "
                       "aşırı uyum (overfit) üretiyor veya hiçbir şey eklemiyor.")
        else:
            verdict = ("Seçilen ayarlar sabit varsayılandan daha iyi; yine de beklenti (R) negatifse "
                       "bu, maliyetleri karşılayan bir avantaj bulunduğu anlamına gelmez.")
        L += ["", verdict]
    L += ["", "## Dürüst sınırlar",
          "- Dolum: taker ücreti + kayma + varsayılan makas; emir defteri derinliği ve kısmi dolum yok.",
          "- Tasfiye yaklaşıktır (1/kaldıraç − bakım marjı); gerçek tasfiye motoru modellenmedi.",
          "- Funding sabit varsayımdır (geçmiş funding arşivi yok).",
          "- Sentetik veri sonuçları gerçek piyasa hakkında hiçbir şey söylemez.", ""]
    return "\n".join(L)
