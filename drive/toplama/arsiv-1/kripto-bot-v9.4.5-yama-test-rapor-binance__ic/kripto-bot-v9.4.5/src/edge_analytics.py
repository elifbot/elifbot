"""src/edge_analytics.py — Brüt Kenar vs Ücret Sonrası Net Kenar, R-Çarpanı ve Bootstrap Güven Aralığı.

Amaç (Denetim Madde 2.b, 2.c, 3.2, 3.8, 3.10):
  - Ücretsiz brüt beklentiyi (`pre_fee_gross_expectancy`) ve ücret sonrası net beklentiyi
    (`post_fee_net_expectancy`) hem USDT hem baz puan (`bps` / notional) cinsinden ayrı ölçer.
  - Her işlemin R-çarpanını (`1R = $40.0` marj stopu risk birimi) hesaplar.
  - Bootstrap %95 güven aralığını (`n_boot = 1000`, sabit tohum `42`) hesaplar; örneklem `< 30`
    olduğunda istatistiksel anlamsızlık uyarısını açıkça raporlar.
  - Abartılı sıfatlar olmadan tek standart karar tablosu üretir.
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Any

MIN_STATISTICAL_TRADES = 30


def _bootstrap_mean_ci(
    values: list[float], *, n_boot: int = 1000, alpha: float = 0.05, seed: int = 42
) -> tuple[float, float] | None:
    n = len(values)
    if n < 2:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(max(100, int(n_boot))):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_idx = max(0, min(len(means) - 1, int((alpha / 2.0) * len(means))))
    hi_idx = max(0, min(len(means) - 1, int((1.0 - alpha / 2.0) * len(means))))
    return (round(means[lo_idx], 4), round(means[hi_idx], 4))


def compute_edge_separation_report(
    closed_trades: list[dict[str, Any]],
    *,
    starting_balance: float = 1000.0,
    one_r_usdt: float = 40.0,
    leverage_default: int = 10,
    margin_default_usdt: float = 50.0,
) -> dict[str, Any]:
    """Kapanan işlemlerden brüt kenar, komisyon yükü, R-dağılımı, CI ve MaxDD tablosu üretir."""
    n = len(closed_trades)
    r_unit = max(0.01, float(one_r_usdt))

    gross_list: list[float] = []
    fee_list: list[float] = []
    net_list: list[float] = []
    gross_bps_list: list[float] = []
    fee_bps_list: list[float] = []
    net_bps_list: list[float] = []
    r_mult_list: list[float] = []

    eq = float(starting_balance)
    peak_eq = eq
    max_dd_usdt = 0.0
    max_dd_pct = 0.0

    for t in closed_trades:
        gross = float(t.get("gross_pnl", t.get("pnl_usdt", 0.0)) or 0.0)
        fee = float(
            t.get("fee_usdt")
            if t.get("fee_usdt") is not None
            else ((t.get("entry_fee_usdt") or 0.0) + (t.get("exit_fee_usdt") or 0.0))
        )
        net = (
            float(t["net_pnl_usdt"])
            if t.get("net_pnl_usdt") is not None
            else float(t.get("pnl_usdt", gross - fee))
        )
        # Eğer closed_rows formatında gross_pnl ve pnl_usdt(=net) verildiyse tutarlılığı koru
        if "gross_pnl" in t and "pnl_usdt" in t and "net_pnl_usdt" not in t:
            gross = float(t["gross_pnl"])
            net = float(t["pnl_usdt"])

        margin = float(t.get("margin_usdt") or margin_default_usdt)
        lev = int(t.get("leverage") or leverage_default)
        notional = max(1.0, margin * max(1, lev))

        gross_list.append(gross)
        fee_list.append(fee)
        net_list.append(net)
        gross_bps_list.append((gross / notional) * 10_000.0)
        fee_bps_list.append((fee / notional) * 10_000.0)
        net_bps_list.append((net / notional) * 10_000.0)
        r_mult_list.append(net / r_unit)

        eq += net
        peak_eq = max(peak_eq, eq)
        dd = peak_eq - eq
        if dd > max_dd_usdt:
            max_dd_usdt = dd
            max_dd_pct = (dd / peak_eq * 100.0) if peak_eq > 0 else 0.0

    low_sample = n < MIN_STATISTICAL_TRADES
    sample_note = (
        f"DÜŞÜK ÖRNEKLEM ({n} < {MIN_STATISTICAL_TRADES}): kazanma oranı ve güven aralığı "
        "istatistiksel kanıt sayılmaz."
        if low_sample
        else f"Yeterli örneklem (N={n} >= {MIN_STATISTICAL_TRADES})."
    )

    gross_tot = sum(gross_list)
    fee_tot = sum(fee_list)
    net_tot = sum(net_list)

    r_sorted = sorted(r_mult_list)
    r_stats = {
        "one_r_usdt": round(r_unit, 2),
        "mean_r": round(sum(r_mult_list) / n, 4) if n else 0.0,
        "median_r": round(statistics.median(r_mult_list), 4) if n else 0.0,
        "min_r": round(r_sorted[0], 4) if n else 0.0,
        "max_r": round(r_sorted[-1], 4) if n else 0.0,
    }

    gross_ci = _bootstrap_mean_ci(gross_list)
    net_ci = _bootstrap_mean_ci(net_list)

    return {
        "trade_count": n,
        "low_sample_warning": low_sample,
        "sample_warning_text": sample_note,
        "gross_total_usdt": round(gross_tot, 4),
        "fees_total_usdt": round(fee_tot, 4),
        "net_total_usdt": round(net_tot, 4),
        "pre_fee_expectancy_usdt": round(gross_tot / n, 4) if n else 0.0,
        "fee_per_trade_usdt": round(fee_tot / n, 4) if n else 0.0,
        "post_fee_expectancy_usdt": round(net_tot / n, 4) if n else 0.0,
        "pre_fee_edge_bps": round(sum(gross_bps_list) / n, 2) if n else 0.0,
        "fee_cost_bps": round(sum(fee_bps_list) / n, 2) if n else 0.0,
        "post_fee_edge_bps": round(sum(net_bps_list) / n, 2) if n else 0.0,
        "fee_to_abs_gross_ratio": (
            round(fee_tot / abs(gross_tot), 3) if abs(gross_tot) > 1e-9 else None
        ),
        "bootstrap_95_ci_gross_per_trade_usdt": list(gross_ci) if gross_ci else None,
        "bootstrap_95_ci_net_per_trade_usdt": list(net_ci) if net_ci else None,
        "r_multiple_distribution": r_stats,
        "max_drawdown_usdt": round(max_dd_usdt, 4),
        "max_drawdown_pct": round(max_dd_pct, 4),
    }
