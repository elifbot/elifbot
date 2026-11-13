"""Run telemetry: one place that records the whole funnel and builds the JSON report.

Funnel (what the 10 min READ_ONLY -> 10 min PAPER run is meant to expose):

    ranked candidates -> detailed snapshots -> scored -> >= min_score
        -> SIZING -> RISK -> CORRELATION -> PAPER ACCEPTED / REJECTED(+reason)
"""
from __future__ import annotations
import json
import time
from collections import Counter, defaultdict

VERSION = "20.0.0-acarbot"


class Telemetry:
    THRESHOLDS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.72)

    def __init__(self, extra_thresholds=()):
        self.thresholds = tuple(sorted(set(self.THRESHOLDS) | set(extra_thresholds)))
        self._pass = Counter()
        self.snapshot_dropped = Counter()
        self.strategy_rejections = Counter()
        self.rank_rejections = defaultdict(Counter)        # exchange -> reason -> n
        self.exchange_discovered = Counter()
        self.exchange_ranked = Counter()                    # candidates that passed rank filters (last cycle sum)
        self.exchange_scanned = Counter()                   # detailed snapshots actually built
        self.signals_by_exchange = Counter()
        self.signals_by_side = Counter()
        self.funnel = Counter()
        self.paper_rejections = Counter()                   # "STAGE:reason" -> events
        self.paper_rejections_unique = defaultdict(set)     # "STAGE:reason" -> {ex:sym:side}
        self.paper_accepted_unique = set()
        self.live_rejections = Counter()
        self.live_rejections_unique = defaultdict(set)
        self.exchange_status = {}
        self.volume_samples = {}
        self.order_skips = Counter()
        self.score_min = None
        self.score_max = None
        self.score_sum = 0.0
        self.score_count = 0
        self.score_histogram = {f"{i/10:.1f}-{(i+1)/10:.1f}": 0 for i in range(10)}
        self.truncated_cycles = 0
        self.cycle_durations = []
        self.notes = []

    # ---- recording helpers -------------------------------------------------
    def record_score(self, score: float):
        self.score_min = score if self.score_min is None else min(self.score_min, score)
        self.score_max = score if self.score_max is None else max(self.score_max, score)
        self.score_sum += score
        self.score_count += 1
        for th in self.thresholds:
            if abs(score) >= th - 1e-12:
                self._pass[f"{th:.2f}"] += 1
        a = min(0.999999, abs(score))
        b = min(9, int(a * 10))
        self.score_histogram[f"{b/10:.1f}-{(b+1)/10:.1f}"] += 1

    def record_paper_rejection(self, stage: str, reason: str, key: str):
        label = f"{stage}:{reason}"
        self.paper_rejections[label] += 1
        self.paper_rejections_unique[label].add(key)
        self.funnel[f"rejected_{stage.lower()}"] += 1
        self.funnel["paper_rejected"] += 1

    def record_live_rejection(self, stage: str, reason: str, key: str):
        label = f"{stage}:{reason}"
        self.live_rejections[label] += 1
        self.live_rejections_unique[label].add(key)
        self.funnel["live_rejected"] += 1

    def pass_counts(self):
        """Exact number of scored snapshots with |score| >= threshold (not histogram-estimated)."""
        return {f"{th:.2f}": self._pass.get(f"{th:.2f}", 0) for th in self.thresholds}

    # ---- report ------------------------------------------------------------
    def build_report(self, *, mode, universe_discovered, cycles, elapsed, errors, unique_signals,
                     signals_seen, detail_per_exchange, exchanges, final, paper_summary=None,
                     correlation_stats=None, config_echo=None):
        mean = self.score_sum / self.score_count if self.score_count else None
        funnel = dict(self.funnel)
        funnel.setdefault("detailed_snapshots", sum(self.exchange_scanned.values()))
        return {
            "version": VERSION,
            "mode": mode,
            "final": final,
            "timestamp": int(time.time() * 1000),
            "duration_sec": elapsed,
            "cycles": cycles,
            "truncated_cycles": self.truncated_cycles,
            "cycle_durations_sec": [round(x, 1) for x in self.cycle_durations],
            "exchanges": exchanges,
            "universe_discovered": universe_discovered,
            "universe": universe_discovered,  # backwards-compatible alias (V15 report key)
            "exchange_discovered": dict(self.exchange_discovered),
            "exchange_ranked": dict(self.exchange_ranked),
            "exchange_scanned": dict(self.exchange_scanned),
            "universe_scanned_unique_snapshots": sum(self.exchange_scanned.values()),
            "detailed_snapshots": sum(self.exchange_scanned.values()),
            "detail_per_exchange": detail_per_exchange,
            "detail_per_cycle": detail_per_exchange,
            "signals_seen": signals_seen,
            "unique_signals": unique_signals,
            "errors": errors,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "score_mean": mean,
            "score_histogram": dict(self.score_histogram),
            "score_pass_counts": self.pass_counts(),
            "rank_rejections": {ex: dict(c) for ex, c in self.rank_rejections.items()},
            "snapshot_dropped": dict(self.snapshot_dropped),
            "strategy_rejections": dict(self.strategy_rejections),
            "signals_by_exchange": dict(self.signals_by_exchange),
            "signals_by_side": dict(self.signals_by_side),
            "funnel": funnel,
            "paper_rejections": dict(self.paper_rejections),
            "paper_rejections_unique": {k: len(v) for k, v in self.paper_rejections_unique.items()},
            "paper_accepted_unique": len(self.paper_accepted_unique),
            "live_rejections": dict(self.live_rejections),
            "live_rejections_unique": {k: len(v) for k, v in self.live_rejections_unique.items()},
            "paper": paper_summary or {},
            "correlation_gate": correlation_stats or {},
            "order_skips": dict(self.order_skips),
            "exchange_status": self.exchange_status,
            "volume_samples": self.volume_samples,
            "notes": self.notes,
            "config": config_echo or {},
        }

    @staticmethod
    def write(path: str, report: dict):
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        import os
        os.replace(tmp, path)
