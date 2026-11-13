"""Shadow Lab JSON'unu bot-kapanış ve eşleştirilmiş pozisyon kohortlarıyla inceler."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from .attribution import build_session_analysis
from .cohort_report import split_cohorts
from .shadow_lab import _extended_metrics, _top2_share


def _num(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pf(value) -> str:
    return "∞" if value is None else f"{float(value):.2f}"


def _money(value) -> str:
    return f"{_num(value):+,.2f}"


def _position_id(row: dict) -> str:
    return str(row.get("position_id") or "")


def build_shadow_review(report: dict) -> dict:
    baseline_all = report["baseline"].get("trades")
    if baseline_all is None:
        # İlk v1 kanıtlarında baseline trades alanı yoksa exact mirror kayıtlarını
        # kullan. Bütün mirror'lardan elenen nadir adayları ise reddedilen kararın
        # baseline_outcome alanı ve net-exit giriş şablonuyla işaretli kur.
        baseline_all = []
        seen = set()
        net_templates = {}
        for variant in report.get("variants", []):
            for trade in variant.get("trades", []):
                pid = _position_id(trade)
                if variant.get("name") == "net-exit":
                    net_templates[pid] = trade
                if trade.get("paired_baseline") and pid not in seen:
                    baseline_all.append(trade)
                    seen.add(pid)
        for variant in report.get("variants", []):
            for decision in variant.get("decisions", []):
                pid = _position_id(decision)
                outcome = decision.get("baseline_outcome") or {}
                if decision.get("accepted") or not outcome or pid in seen:
                    continue
                template = net_templates.get(pid)
                if template is None:
                    continue
                reconstructed = copy.deepcopy(template)
                reconstructed.pop("shadow_variant", None)
                reconstructed.pop("paired_baseline", None)
                reconstructed.update(outcome)
                reconstructed["reason"] = outcome.get("reason")
                reconstructed["reconstructed_baseline"] = True
                reconstructed["roe_pct"] = _num(
                    reconstructed.get("pnl_pct")
                ) * _num(reconstructed.get("leverage"))
                baseline_all.append(reconstructed)
                seen.add(pid)
    baseline_bot, baseline_manual = split_cohorts(baseline_all)
    baseline_bot_by_id = {_position_id(row): row for row in baseline_bot}
    start_balance = _num(
        (report.get("variants") or [{}])[0].get("start_balance_usdt")
    ) or 100000.0

    def performance(trades):
        return {
            "analysis": build_session_analysis(trades),
            "extended": _extended_metrics(trades, start_balance),
            "top2_share_of_net_pct": _top2_share(trades),
        }

    review = {
        "schema": "shadow-review-v1",
        "source_schema": report.get("schema"),
        "generated_at": report.get("generated_at"),
        "method": {
            "performance": "Botun kendi kapattığı işlemler; manuel/süre-sonu kohortu performansa katılmaz.",
            "paired": "Aynı position_id ile baseline-bot girişlerine bağlı shadow sonucu; varyantın kapanış kohortundan bağımsız eşleştirme.",
            "promotion": "Tek run otomatik canlı kural/parametre kararı değildir; zararsızlık garanti edilmez.",
        },
        "baseline": {
            **performance(baseline_bot),
            "manual_early_count": len(baseline_manual),
            "observed_trades": report["baseline"].get("trades_observed", len(baseline_all)),
            "recovered_trades": len(baseline_all),
            "reconstructed_trades": sum(
                bool(row.get("reconstructed_baseline")) for row in baseline_all
            ),
            "coverage_complete": (
                len(baseline_all)
                == int(report["baseline"].get("trades_observed", len(baseline_all)))
            ),
        },
        "variants": [],
    }

    for variant in report.get("variants", []):
        all_trades = variant.get("trades", [])
        bot_trades, manual_trades = split_cohorts(all_trades)
        by_id = {_position_id(row): row for row in all_trades}
        decisions = variant.get("decisions", [])
        rejected_ids = {
            _position_id(row) for row in decisions if not row.get("accepted")
        }
        accepted_ids = {
            _position_id(row) for row in decisions if row.get("accepted")
        }
        eliminated = [
            row for pid, row in baseline_bot_by_id.items() if pid in rejected_ids
        ]
        preserved = [
            row for pid, row in baseline_bot_by_id.items() if pid in accepted_ids
        ]
        baseline_winners = sum(
            _num(row.get("net_pnl_usdt")) > 0 for row in baseline_bot
        )
        eliminated_winners = sum(
            _num(row.get("net_pnl_usdt")) > 0 for row in eliminated
        )
        paired = []
        for pid, baseline in baseline_bot_by_id.items():
            shadow = by_id.get(pid)
            if shadow is None:
                continue
            delta = _num(shadow.get("net_pnl_usdt")) - _num(
                baseline.get("net_pnl_usdt")
            )
            paired.append(
                {
                    "position_id": pid,
                    "symbol": baseline.get("symbol"),
                    "side": baseline.get("side"),
                    "exchange": baseline.get("exchange"),
                    "baseline_reason": baseline.get("reason"),
                    "shadow_reason": shadow.get("reason"),
                    "baseline_exit_price": baseline.get("exit_price"),
                    "shadow_exit_price": shadow.get("exit_price"),
                    "baseline_net_usdt": _num(baseline.get("net_pnl_usdt")),
                    "shadow_net_usdt": _num(shadow.get("net_pnl_usdt")),
                    "delta_net_usdt": delta,
                    "baseline_mfe_usdt": _num(baseline.get("mfe_usdt")),
                    "baseline_mae_usdt": _num(baseline.get("mae_usdt")),
                    "shadow_mfe_usdt": _num(shadow.get("mfe_usdt")),
                    "shadow_mae_usdt": _num(shadow.get("mae_usdt")),
                    "shadow_stop_price": shadow.get("stop_price"),
                }
            )
        baseline_scope_net = sum(
            _num(row.get("net_pnl_usdt")) for row in baseline_bot
        )
        shadow_scope_net = sum(
            _num(by_id[pid].get("net_pnl_usdt"))
            for pid in baseline_bot_by_id
            if pid in by_id
        )
        rejected_details = []
        for decision in decisions:
            pid = _position_id(decision)
            if decision.get("accepted") or pid not in baseline_bot_by_id:
                continue
            rejected_details.append(
                {
                    "position_id": pid,
                    "symbol": decision.get("symbol"),
                    "side": decision.get("side"),
                    "reason": decision.get("reason"),
                    "measurements": decision.get("measurements", {}),
                    "baseline_outcome": decision.get("baseline_outcome", {}),
                }
            )
        review["variants"].append(
            {
                "name": variant.get("name"),
                "kind": variant.get("kind"),
                **performance(bot_trades),
                "manual_early_count": len(manual_trades),
                "accepted_entries": variant.get("accepted_entries", 0),
                "rejected_entries": variant.get("rejected_entries", 0),
                "comparison": {
                    "baseline_bot_entries": len(baseline_bot),
                    "shadow_results_on_baseline_bot_entries": sum(
                        pid in by_id for pid in baseline_bot_by_id
                    ),
                    "preserved_baseline_trades": len(preserved),
                    "eliminated_baseline_trades": len(eliminated),
                    "eliminated_baseline_winners": eliminated_winners,
                    "eliminated_baseline_losers": sum(
                        _num(row.get("net_pnl_usdt")) < 0 for row in eliminated
                    ),
                    "missed_baseline_winner_rate_pct": (
                        eliminated_winners / baseline_winners * 100.0
                        if baseline_winners > 0 else None
                    ),
                    "eliminated_baseline_net_usdt": sum(
                        _num(row.get("net_pnl_usdt")) for row in eliminated
                    ),
                    "baseline_bot_net_usdt": baseline_scope_net,
                    "shadow_net_on_same_baseline_bot_entries_usdt": shadow_scope_net,
                    "total_delta_vs_baseline_usdt": shadow_scope_net - baseline_scope_net,
                    "paired_exit_delta_usdt": sum(row["delta_net_usdt"] for row in paired),
                    "improved_pairs": sum(row["delta_net_usdt"] > 1e-9 for row in paired),
                    "worsened_pairs": sum(row["delta_net_usdt"] < -1e-9 for row in paired),
                    "unchanged_pairs": sum(abs(row["delta_net_usdt"]) <= 1e-9 for row in paired),
                },
                "paired_trades": paired,
                "rejected_details": rejected_details,
                "closeout_completed": variant.get("open_positions", 0) == 0,
            }
        )
    return review


def render_shadow_review(review: dict) -> str:
    baseline = review["baseline"]
    base_stats = baseline["analysis"]["overall"]
    base_ext = baseline["extended"]
    lines = [
        "# Shadow Lab — bot-kapanış ve eşleştirilmiş pozisyon incelemesi",
        "",
        "> Manuel/süre-sonu kapanışlar performans kohortundan ayrıldı. Eşleştirme aynı `position_id` ile yapılır. Tek run canlı kural veya zararsızlık garantisi değildir.",
        "",
        f"Baseline kapanış kapsaması: **{baseline['recovered_trades']}/{baseline['observed_trades']}** | "
        f"işaretli rekonstrüksiyon: {baseline['reconstructed_trades']} | "
        f"durum: **{'TAM' if baseline['coverage_complete'] else 'EKSİK'}**.",
        "",
        "## 1. Botun kapattığı işlemlerde performans",
        "",
        "| Varyant | İşlem | K/Z | Net | PF | Medyan net | Max DD | İlk 2/net | Trailing maliyet zararı |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def performance_row(name, stats, ext, top2):
        trailing = (
            f"{ext['trailing_gross_nonnegative_net_loss_count']} / "
            f"{_money(ext['trailing_gross_nonnegative_net_loss_usdt'])}"
        )
        return (
            f"| {name} | {stats['count']} | {stats['wins']}/{stats['losses']} | "
            f"{_money(stats['net_pnl_usdt'])} | {_pf(stats['profit_factor'])} | "
            f"{_money(ext['median_net_usdt'])} | {_money(ext['closed_equity_max_drawdown_usdt'])} | "
            f"{f'{top2:.1f}%' if top2 is not None else '—'} | {trailing} |"
        )

    lines.append(
        performance_row(
            "BASELINE", base_stats, base_ext, baseline["top2_share_of_net_pct"]
        )
    )
    for variant in review["variants"]:
        lines.append(
            performance_row(
                variant["name"], variant["analysis"]["overall"],
                variant["extended"], variant["top2_share_of_net_pct"],
            )
        )

    lines.extend(
        [
            "",
            "## 2. Aynı baseline-bot pozisyonları üzerindeki etki",
            "",
            "`Toplam fark`, reddedilen işlemlerin yokluğunu ve kabul edilenlerdeki çıkış farkını birlikte içerir. `Çıkış farkı` yalnız iki tarafta da kapanışı olan aynı pozisyonlardır.",
            "",
            "| Varyant | Korunan / elenen | Kaçırılan kazanan | Toplam fark | Çıkış farkı | İyileşen / kötüleşen / aynı |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for variant in review["variants"]:
        comp = variant["comparison"]
        missed = comp["missed_baseline_winner_rate_pct"]
        lines.append(
            f"| {variant['name']} | {comp['preserved_baseline_trades']} / {comp['eliminated_baseline_trades']} | "
            f"{f'{missed:.1f}%' if missed is not None else '—'} | "
            f"{_money(comp['total_delta_vs_baseline_usdt'])} | {_money(comp['paired_exit_delta_usdt'])} | "
            f"{comp['improved_pairs']} / {comp['worsened_pairs']} / {comp['unchanged_pairs']} |"
        )

    net_variant = next(
        (row for row in review["variants"] if row["name"] == "net-exit"), None
    )
    if net_variant:
        lines.extend(["", "## 3. Net Exit çıkış dağılımı", ""])
        for reason, stats in net_variant["analysis"]["exit_modules"].items():
            lines.append(
                f"- **{reason}:** {stats['count']} işlem | K/Z {stats['wins']}/{stats['losses']} | "
                f"net {_money(stats['net_pnl_usdt'])}"
            )
        changed = sorted(
            (row for row in net_variant["paired_trades"] if abs(row["delta_net_usdt"]) > 1e-9),
            key=lambda row: abs(row["delta_net_usdt"]), reverse=True,
        )
        if changed:
            lines.extend(["", "| Sembol | Baseline çıkış | Shadow çıkış | Baseline net | Shadow net | Fark |", "|---|---|---|---:|---:|---:|"])
            for row in changed[:30]:
                lines.append(
                    f"| {row['symbol']} {row['side']} | {row['baseline_reason']} | {row['shadow_reason']} | "
                    f"{_money(row['baseline_net_usdt'])} | {_money(row['shadow_net_usdt'])} | {_money(row['delta_net_usdt'])} |"
                )

    lines.extend(["", "## 4. Borsa ve rejim dağılımı", ""])
    for name, performance in [("BASELINE", baseline)] + [
        (row["name"], row) for row in review["variants"]
    ]:
        ext = performance["extended"]
        exchange = ", ".join(
            f"{key}: {value['trades']} / {_money(value['net_pnl_usdt'])}"
            for key, value in ext["exchanges"].items()
        ) or "veri yok"
        regimes = ", ".join(
            f"{key}: {value['trades']} / {_money(value['net_pnl_usdt'])}"
            for key, value in ext["regimes"].items()
        ) or "veri yok"
        lines.append(f"- **{name}** — Borsa: {exchange}. Rejim: {regimes}.")

    lines.extend(["", "## 5. Reddedilen adayların baseline sonuçları", ""])
    any_rejected = False
    for variant in review["variants"]:
        details = variant["rejected_details"]
        if not details:
            continue
        any_rejected = True
        lines.extend([f"### {variant['name']}", "", "| Sembol | Ret nedeni | Baseline net | MFE | MAE | Stop | Ücret + funding |", "|---|---|---:|---:|---:|---:|---:|"])
        for row in details:
            outcome = row["baseline_outcome"]
            costs = (
                _num(outcome.get("entry_fee_usdt"))
                + _num(outcome.get("exit_fee_usdt"))
            )
            lines.append(
                f"| {row['symbol']} {row['side']} | {row['reason']} | "
                f"{_money(outcome.get('net_pnl_usdt'))} | {_money(outcome.get('mfe_usdt'))} | "
                f"{_money(outcome.get('mae_usdt'))} | {_num(outcome.get('stop_price')):.8g} | "
                f"{_money(costs)} / {_money(outcome.get('funding_usdt'))} |"
            )
        lines.append("")
    if not any_rejected:
        lines.append("Bot-kapanış kohortuna denk gelen reddedilen aday yok.")

    lines.extend(["", "## 6. Ayrı tutulan manuel/erken kapanışlar", ""])
    lines.append(
        f"- Baseline: {baseline['manual_early_count']} | "
        + " | ".join(
            f"{row['name']}: {row['manual_early_count']}" for row in review["variants"]
        )
    )
    lines.append("Bu kohortta çıkış performansı değerlendirilmez; giriş kanıtı ayrı `cohort-report.md` içindedir.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shadow_json", type=Path)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.shadow_json.read_text(encoding="utf-8"))
    review = build_shadow_review(source)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    text = render_shadow_review(review)
    args.output_prefix.with_suffix(".md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
