"""Haber koruması testleri (FINAL v1.1)."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from core.config import NewsGuardConfig
from safety.news_guard import NewsGuard, parse_calendar_events

# Sabit olay: 2026-11-06 13:30 UTC (NFP tipik saati)
EVENT_DT = datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)
EVENT_MS = int(EVENT_DT.timestamp() * 1000)
MIN = 60_000


def _row(title="Non-Farm Employment Change", country="USD", impact="High",
         date="2026-11-06T08:30:00-05:00"):
    return {"title": title, "country": country, "impact": impact, "date": date}


def _guard(fetch=None, **overrides) -> NewsGuard:
    cfg = replace(NewsGuardConfig(), **overrides)
    return NewsGuard(cfg, fetch_json=fetch or (lambda url: [_row()]))


class ParseTests(unittest.TestCase):
    def test_parses_usd_high(self):
        events = parse_calendar_events([_row()], 30.0, ("USD",), ("High",))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start_ms, EVENT_MS - 30 * MIN)
        self.assertEqual(events[0].end_ms, EVENT_MS + 30 * MIN)

    def test_filters_country_and_impact(self):
        rows = [_row(country="EUR"), _row(impact="Medium"), _row(impact="Low")]
        self.assertEqual(parse_calendar_events(rows, 30.0, ("USD",), ("High",)), [])

    def test_skips_bad_rows(self):
        rows = [_row(date="bozuk-tarih"), _row(date=""), "string", {},
                {"country": "USD", "impact": "High"}]
        self.assertEqual(parse_calendar_events(rows, 30.0, ("USD",), ("High",)), [])

    def test_naive_datetime_rejected(self):
        rows = [_row(date="2026-11-06T13:30:00")]  # saat dilimi yok
        self.assertEqual(parse_calendar_events(rows, 30.0, ("USD",), ("High",)), [])


class BlackoutTests(unittest.TestCase):
    def test_blocks_inside_window(self):
        guard = _guard()
        guard.refresh(EVENT_MS - 60 * MIN)
        blocked, reason = guard.blackout(EVENT_MS - 10 * MIN)
        self.assertTrue(blocked)
        self.assertIn("NEWS_GUARD", reason)
        self.assertIn("Non-Farm", reason)

    def test_window_edges_inclusive(self):
        guard = _guard()
        guard.refresh(EVENT_MS - 60 * MIN)
        self.assertTrue(guard.blackout(EVENT_MS - 30 * MIN)[0])
        self.assertTrue(guard.blackout(EVENT_MS + 30 * MIN)[0])

    def test_allows_outside_window(self):
        guard = _guard()
        guard.refresh(EVENT_MS - 120 * MIN)
        self.assertFalse(guard.blackout(EVENT_MS - 31 * MIN)[0])
        self.assertFalse(guard.blackout(EVENT_MS + 31 * MIN)[0])

    def test_custom_buffer(self):
        guard = _guard(buffer_minutes=10.0)
        guard.refresh(EVENT_MS - 60 * MIN)
        self.assertFalse(guard.blackout(EVENT_MS - 15 * MIN)[0])
        self.assertTrue(guard.blackout(EVENT_MS - 5 * MIN)[0])

    def test_blocks_count_tracked(self):
        guard = _guard()
        guard.refresh(EVENT_MS - 60 * MIN)
        guard.blackout(EVENT_MS)
        guard.blackout(EVENT_MS)
        self.assertEqual(guard.status()["blocks_count"], 2)


class RefreshAndFailureTests(unittest.TestCase):
    def test_fail_open_without_data(self):
        def boom(url):
            raise OSError("network down")
        guard = _guard(fetch=boom)
        guard.refresh(EVENT_MS)
        self.assertFalse(guard.blackout(EVENT_MS)[0])  # fail-open
        self.assertEqual(guard.status()["refresh_failures"], 1)

    def test_fail_closed_without_data(self):
        def boom(url):
            raise OSError("network down")
        guard = _guard(fetch=boom, fail_closed=True)
        guard.refresh(EVENT_MS)
        blocked, reason = guard.blackout(EVENT_MS)
        self.assertTrue(blocked)
        self.assertEqual(reason, "NEWS_GUARD_NO_DATA")

    def test_stale_data_kept_on_failure(self):
        calls = {"n": 0}

        def flaky(url):
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError("geçici hata")
            return [_row()]

        guard = _guard(fetch=flaky, refresh_seconds=1.0)
        guard.refresh(EVENT_MS - 60 * MIN)
        guard.refresh(EVENT_MS - 30 * MIN)  # hata → eski veri korunur
        self.assertTrue(guard.blackout(EVENT_MS)[0])
        self.assertEqual(guard.status()["events_loaded"], 1)

    def test_refresh_throttled(self):
        calls = {"n": 0}

        def counting(url):
            calls["n"] += 1
            return [_row()]

        guard = _guard(fetch=counting, refresh_seconds=900.0)
        guard.refresh(EVENT_MS)
        guard.refresh(EVENT_MS + 60_000)  # 1 dk sonra → istek yapılmamalı
        self.assertEqual(calls["n"], 1)
        guard.refresh(EVENT_MS + 16 * MIN)
        self.assertEqual(calls["n"], 2)

    def test_local_events_file_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "events.json"
            local.write_text(json.dumps([
                _row(title="Özel Olay", date="2026-11-06T14:00:00+00:00"),
            ]), encoding="utf-8")
            guard = _guard(local_events_file=str(local))
            guard.refresh(EVENT_MS - 120 * MIN)
            self.assertEqual(guard.status()["events_loaded"], 2)
            # 14:10 UTC: yalnızca Özel Olay penceresi aktif (NFP 14:00'te biter)
            blocked, reason = guard.blackout(
                int(datetime(2026, 11, 6, 14, 10, tzinfo=timezone.utc).timestamp() * 1000)
            )
            self.assertTrue(blocked)
            self.assertIn("Özel Olay", reason)


if __name__ == "__main__":
    unittest.main()
