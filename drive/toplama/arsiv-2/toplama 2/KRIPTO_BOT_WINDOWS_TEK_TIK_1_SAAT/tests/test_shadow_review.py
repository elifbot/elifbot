import json

from src.shadow_review import build_shadow_review, render_shadow_review
from tests.test_shadow_lab import _lab, _open, _trade


def _completed_report():
    lab = _lab()
    pos = _open(lab)
    lab.on_price_tick(pos.symbol, 102)
    trade = _trade(exit_price=102, reason="TRAILING STOP (kâr)")
    lab.on_baseline_close(pos.symbol, pos, trade, True)
    lab.close_all("TEST SONU")
    return lab.report()


def test_review_separates_bot_cohort_and_paired_filter_effects():
    review = build_shadow_review(_completed_report())
    assert review["baseline"]["coverage_complete"]
    assert review["baseline"]["analysis"]["overall"]["count"] == 1
    by_name = {row["name"]: row for row in review["variants"]}
    technical = by_name["technical-harmony"]["comparison"]
    assert technical["eliminated_baseline_trades"] == 1
    assert technical["missed_baseline_winner_rate_pct"] == 100
    assert by_name["net-exit"]["comparison"]["shadow_results_on_baseline_bot_entries"] == 1
    text = render_shadow_review(review)
    assert "bot-kapanış" in text
    assert "Reddedilen aday" in text
    json.dumps(review, allow_nan=False)


def test_review_reconstructs_v1_baseline_when_all_mirrors_are_absent():
    report = _completed_report()
    del report["baseline"]["trades"]
    for variant in report["variants"]:
        if variant["name"] != "net-exit":
            variant["trades"] = []
    review = build_shadow_review(report)
    assert review["baseline"]["coverage_complete"]
    assert review["baseline"]["reconstructed_trades"] == 1
    assert review["baseline"]["analysis"]["overall"]["count"] == 1
