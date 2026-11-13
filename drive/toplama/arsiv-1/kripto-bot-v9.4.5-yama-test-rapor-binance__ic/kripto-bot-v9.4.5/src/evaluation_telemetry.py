"""Read-only classification of existing counters; never participates in decisions."""
ENTRY_RETRY_REASON = 'ONE_ATTEMPT_PER_CLOSED_BAR'
POSITION_RETRY_REASON = 'POSITION_WAIT_NEXT_CLOSED_BAR'


def evaluation_telemetry_snapshot(engine):
    total = int(engine.metrics.get('signals_evaluated', 0))
    reasons = dict(getattr(getattr(engine, 'v94_router', None), 'rejections', {}))
    entry_retry = int(reasons.get(ENTRY_RETRY_REASON, 0))
    position_retry = int(reasons.get(POSITION_RETRY_REASON, 0))
    retry = entry_retry + position_retry
    return {
        'evaluation_calls_total': total,
        'entry_retry_suppressed': entry_retry,
        'position_retry_suppressed': position_retry,
        'retry_suppressed_total': retry,
        'non_retry_evaluation_calls': total - retry,
        'retry_suppression_pct': 100.0 * retry / total if total else None,
        'counter_consistent': 0 <= retry <= total,
        'non_retry_reason_counts': {k: v for k, v in reasons.items()
                                    if k not in (ENTRY_RETRY_REASON, POSITION_RETRY_REASON)},
        'unique_signal_count': None,
        'scope': 'Call counters, NOT unique opportunities, mature cohorts, or independent signals',
        'strategy_policy_changed': False,
    }
