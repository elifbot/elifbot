"""Pretty-print the V20 funnel from a report JSON.

    python tools/read_report.py reports/paper_10min.json
"""
import json
import sys


def line(label, n, base=None):
    pct = f"  ({100*n/base:5.1f}% of previous)" if base else ""
    print(f"  {label:<34}{n:>8}{pct}")


def main(path):
    r = json.load(open(path, encoding="utf-8"))
    f = r.get("funnel", {})
    print(f"\n=== ACARBOT {r.get('version')}  mode={r.get('mode')}  cycles={r.get('cycles')}  duration={r.get('duration_sec')}s  final={r.get('final')} ===")
    print(f"universe discovered: {r.get('universe_discovered')}   per exchange: {r.get('exchange_discovered')}")
    print(f"ranked candidates (last cycle): {r.get('exchange_ranked')}   scanned snapshots: {r.get('exchange_scanned')}")
    if r.get("truncated_cycles"):
        print(f"!! {r['truncated_cycles']} cycle(s) were truncated by the time budget; cycle durations: {r.get('cycle_durations_sec')}")
    for ex, st in (r.get("exchange_status") or {}).items():
        print(f"!! {ex} status: {st}")
    print("\nRANK FILTER REJECTIONS (why a symbol never became a candidate)")
    for ex, c in (r.get("rank_rejections") or {}).items():
        print(f"  {ex}: {c}")
    print("\nSNAPSHOT DROPS:", r.get("snapshot_dropped"))
    print("STRATEGY REJECTIONS:", r.get("strategy_rejections"))
    print(f"\nSCORE  min={r.get('score_min')}  max={r.get('score_max')}  mean={r.get('score_mean')}")
    print("  |score| >= threshold:", r.get("score_pass_counts"))
    print("\nFUNNEL (events: the same symbol is re-evaluated every cycle)")
    prev = None
    for label, key in (("candidates ranked", "candidates"), ("detailed snapshots", "snapshots"), ("scored", "scored"),
                       ("passed min_score", "passed_min_score")):
        n = f.get(key, 0); line(label, n, prev); prev = n
    for key in ("rejected_sizing", "rejected_risk", "rejected_correlation"):
        line(key.replace("rejected_", "REJECTED at ").upper(), f.get(key, 0))
    line("PAPER ACCEPTED", f.get("paper_accepted", 0))
    line("already open (skipped, not rejected)", f.get("already_open_skipped", 0))
    print("\nWHY REJECTED (events / unique symbols)")
    uniq = r.get("paper_rejections_unique", {})
    for k, v in sorted((r.get("paper_rejections") or {}).items(), key=lambda kv: -kv[1]):
        print(f"  {k:<44}{v:>6} / {uniq.get(k, 0)}")
    if r.get("live_rejections"):
        print("LIVE REJECTIONS:", r["live_rejections"])
    print("\nCORRELATION GATE:", r.get("correlation_gate"))
    print("PAPER ACCOUNT:", r.get("paper"))
    print("ORDER SKIPS (sizing):", r.get("order_skips"))
    print("VOLUME SAMPLES (sanity-check these against the exchange UI):")
    for ex, rows in (r.get("volume_samples") or {}).items():
        for x in rows:
            print(f"  {ex}: {x}")


if __name__ == "__main__":
    main(sys.argv[1])
