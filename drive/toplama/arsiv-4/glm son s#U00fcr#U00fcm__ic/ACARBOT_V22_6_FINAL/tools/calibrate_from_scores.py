"""Offline threshold calibration from a score log (JSONL, one object per scored snapshot).

Works with the V15 reference log and with logs written by `--score-log` in V22.

    python tools/calibrate_from_scores.py reference_data/v15_live_scores_2026-11-10.jsonl
"""
import json
import sys
from collections import Counter

THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.72)


def main(path):
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    if not rows:
        print("empty log"); return 1
    scores = [abs(float(r["score"])) for r in rows]
    print(f"{len(rows)} scored snapshots, max |score| = {max(scores):.4f}, mean = {sum(scores)/len(scores):.4f}")
    span = max(float(r["ts"]) for r in rows) - min(float(r["ts"]) for r in rows)
    hours = max(span, 1.0) / 3600
    print(f"observed window: {span/60:.1f} min\n")
    print(f"{'threshold':>9} {'pass':>6} {'pass %':>7} {'LONG':>6} {'SHORT':>6} {'unique symbols':>15} {'~per hour':>10}")
    for th in THRESHOLDS:
        sel = [r for r in rows if abs(float(r["score"])) >= th]
        side = Counter("LONG" if float(r["score"]) > 0 else "SHORT" for r in sel)
        syms = {(r.get("ex"), r.get("sym")) for r in sel}
        print(f"{th:>9.2f} {len(sel):>6} {100*len(sel)/len(rows):>6.1f}% {side['LONG']:>6} {side['SHORT']:>6} {len(syms):>15} {len(syms)/hours:>10.0f}")
    print("\nNote: unique-symbol counts per hour assume the observed window repeats; this is NOT a profitability estimate.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "reference_data/v15_live_scores_2026-11-10.jsonl"))
