"""
backtests/report.py — Backtest / walk-forward / ablasyon rapor biçimlendirme.

Tüm çıktılar "gerçek performans değildir" uyarısını taşır.
"""
from __future__ import annotations

from typing import Iterable


def _table(rows: list[list[str]], headers: list[str]) -> str:
    try:
        from tabulate import tabulate

        return tabulate(rows, headers=headers, tablefmt="simple")
    except ImportError:  # tabulate yoksa düz metin
        out = [" | ".join(headers)]
        out += [" | ".join(r) for r in rows]
        return "\n".join(out)


_DISCLAIMER = (
    "\nUYARI: Bu sonuçlar paper simülasyonudur. Kullanılan veri seti gerçek\n"
    "piyasa verisi değilse hiçbir performans iddiası taşımaz. Funding maliyeti\n"
    "HARİÇTİR (bilinmiyor). Geçmiş performans gelecek sonuçları göstermez.\n"
)


def render_backtest(results: dict) -> str:
    """Tek motor sonucunu metne çevirir."""
    lines = ["BACKTEST SONUCU", "-" * 50]
    for k, v in results.items():
        if isinstance(v, float):
            lines.append(f"{k:<20}: {v:.6f}")
        else:
            lines.append(f"{k:<20}: {v}")
    return "\n".join(lines) + _DISCLAIMER


def render_walk_forward(window_results: Iterable) -> str:
    """Walk-forward pencerelerini tabloya çevirir."""
    rows: list[list[str]] = []
    for w in window_results:
        m = w.metrics
        rows.append(
            [
                str(w.window_index),
                w.params_hash,
                str(m.get("trades", 0)),
                f"{m.get('realized_pnl', 0.0):+.4f}",
                f"{m.get('win_rate', 0.0) * 100:.1f}%",
                "-" if m.get("profit_factor") is None else f"{m['profit_factor']:.3f}",
                f"{m.get('max_drawdown', 0.0):.4f}",
            ]
        )
    body = _table(
        rows,
        ["pencere", "parametre_izi", "işlem", "net PnL", "win", "PF", "MDD"],
    )
    legend = (
        "\nparametre_izi: her pencere için test öncesi dondurulan parametre setinin\n"
        "SHA-256 kısaltmasıdır. Aynı iz, parametrelerin pencere içinde değişmediğini\n"
        "gösterir. Bu uygulamada parametre optimizasyonu yapılmamaktadır."
    )
    return "WALK-FORWARD SONUÇLARI\n" + body + legend + _DISCLAIMER


def render_ablation(results: Iterable) -> str:
    """Ablasyon sonuçlarını tabloya çevirir."""
    rows = [
        [
            r.family,
            str(r.trades),
            f"{r.realized_pnl:+.4f}",
            f"{r.win_rate * 100:.1f}%",
            "-" if r.profit_factor is None else f"{r.profit_factor:.3f}",
            "-" if r.family == "BASE" else f"{r.delta_pnl:+.4f}",
        ]
        for r in results
    ]
    body = _table(rows, ["aile", "işlem", "net PnL", "win", "PF", "ΔPnL"])
    note = (
        "\nBASE: hiçbir aile devre dışı değil. Diğer satırlarda ilgili ailenin\n"
        "koşulları gerekli olmaktan çıkarılmıştır. Küçük örneklemde ΔPnL\n"
        "gürültü olabilir; bu tablo nedensellik kanıtı değildir."
    )
    return "ABLASYON SONUÇLARI\n" + body + note + _DISCLAIMER
