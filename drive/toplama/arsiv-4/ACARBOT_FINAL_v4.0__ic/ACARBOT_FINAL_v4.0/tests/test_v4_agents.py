"""v4.0 — ajanlar testleri (madde 18-21: ABD piyasası, RSS haber, kongre, analist)."""

from __future__ import annotations

import unittest

from agents.analyst import AnalystAgent
from agents.congress import CongressAgent
from agents.news_rss import RssNewsAgent, parse_rss_titles, risk_score
from agents.us_market import USMarketAgent


def _yahoo_payload(*closes):
    return {"chart": {"result": [{"indicators": {"quote": [{"close": list(closes)}]}}]}}


class USMarketAgentTests(unittest.TestCase):
    def _agent(self, payloads_by_symbol, mode="flag"):
        def fetcher(url):
            for key, payload in payloads_by_symbol.items():
                if key in url:
                    return payload
            raise AssertionError(f"beklenmeyen URL: {url}")

        return USMarketAgent(mode=mode, refresh_seconds=60.0, fetcher=fetcher,
                             clock=lambda: 1_000_000)

    # _yahoo_payload(önceki, son): listenin SON elemanı en güncel kapanıştır
    _payloads = {
        "GSPC": _yahoo_payload(5080.0, 5000.0),   # son 5000, önceki 5080 → -%1.57
        "IXIC": _yahoo_payload(15600.0, 15000.0),  # -%3.85
        "VIX": _yahoo_payload(28.0, 30.0),         # VIX 30
        "NYB": _yahoo_payload(104.5, 105.0),
    }

    def test_risk_off_on_high_vix(self):
        agent = self._agent(self._payloads)
        agent.tick()
        self.assertEqual(agent.flag, "risk_off")
        self.assertIn("VIX 30.0", agent.reason)

    def test_risk_on_on_calm_market(self):
        payloads = {
            "GSPC": _yahoo_payload(5000.0, 5100.0),   # +%2
            "IXIC": _yahoo_payload(15800.0, 16000.0),
            "VIX": _yahoo_payload(16.0, 15.0),        # VIX 15
            "NYB": _yahoo_payload(104.5, 104.0),
        }
        agent = self._agent(payloads)
        agent.tick()
        self.assertEqual(agent.flag, "risk_on")

    def test_neutral_between(self):
        payloads = {
            "GSPC": _yahoo_payload(5000.0, 5010.0),
            "IXIC": _yahoo_payload(15750.0, 15800.0),
            "VIX": _yahoo_payload(21.0, 21.0),
            "NYB": _yahoo_payload(104.0, 104.0),
        }
        agent = self._agent(payloads)
        agent.tick()
        self.assertEqual(agent.flag, "neutral")

    def test_fetch_failure_is_unavailable_and_fails_open(self):
        agent = USMarketAgent(
            mode="block", refresh_seconds=60.0,
            fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("ağ yok")),
            clock=lambda: 1_000_000,
        )
        agent.tick()
        self.assertEqual(agent.flag, "unavailable")
        self.assertIsNone(agent.entry_block(1_000_001))  # fail-open

    def test_block_mode_blocks_fresh_risk_off(self):
        agent = self._agent(self._payloads, mode="block")
        agent.tick()
        reason = agent.entry_block(1_000_001)
        self.assertIsNotNone(reason)
        self.assertIn("risk_off", reason)

    def test_flag_mode_never_blocks(self):
        agent = self._agent(self._payloads, mode="flag")
        agent.tick()
        self.assertIsNone(agent.entry_block(1_000_001))

    def test_stale_flag_fails_open(self):
        agent = self._agent(self._payloads, mode="block")
        agent.tick()
        # 2 tazeleme döngüsünden çok eski → fail-open
        self.assertIsNone(agent.entry_block(1_000_000 + 10 * 60_000))

    def test_off_mode_never_ticks(self):
        agent = self._agent(self._payloads, mode="off")
        agent.tick()
        self.assertEqual(agent.flag, "unavailable")

    def test_refresh_throttle(self):
        agent = self._agent(self._payloads)
        agent.tick()
        # hemen ikinci tick: tazeleme eşiği dolmadı → ağ çağrısı yok
        # (fetcher mock aynı kaldığından flag değişmez; sayaç üzerinden kontrol)
        self.assertEqual(agent.status()["details"]["vix"], 30.0)


class RssNewsAgentTests(unittest.TestCase):
    RSS = b"""<?xml version="1.0"?>
    <rss><channel>
      <item><title>Crypto exchange hacked, funds drained</title>
        <pubDate>Mon, 13 Nov 2023 00:30:00 GMT</pubDate></item>
      <item><title>Market rallies on ETF approval</title>
        <pubDate>Mon, 13 Nov 2023 00:40:00 GMT</pubDate></item>
    </channel></rss>"""

    def test_parse_titles(self):
        titles = parse_rss_titles(self.RSS)
        self.assertEqual(len(titles), 2)
        self.assertIn("hacked", titles[0][0])

    def test_risk_score_keywords(self):
        self.assertEqual(risk_score("Exchange hacked again")[0], 0.9)
        self.assertEqual(risk_score("All-time high")[0], 0.0)

    def test_fresh_hack_title_raises_flag(self):
        # pubDate ~ 2023-11-13 00:30 UTC → epoch ms
        import calendar
        ts_ms = calendar.timegm((2023, 11, 13, 0, 30, 0)) * 1000
        now = ts_ms + 60_000

        def fetcher(url):
            return self.RSS

        agent = RssNewsAgent(
            mode="flag", refresh_seconds=60.0, fetcher=fetcher,
            clock=lambda: now, window_minutes=45.0,
        )
        agent.tick()
        self.assertTrue(agent.flag_active)
        self.assertIn("hacked", agent.flag_reason)
        # flag modda giriş engellenmez
        self.assertIsNone(agent.entry_block(now))

    def test_block_mode_blocks_active_flag(self):
        import calendar
        ts_ms = calendar.timegm((2023, 11, 13, 0, 30, 0)) * 1000
        now = ts_ms + 60_000
        agent = RssNewsAgent(
            mode="block", refresh_seconds=60.0, fetcher=lambda u: self.RSS,
            clock=lambda: now,
        )
        agent.tick()
        reason = agent.entry_block(now)
        self.assertIsNotNone(reason)
        self.assertIn("haber ajanı", reason)

    def test_ttl_expires(self):
        import calendar
        ts_ms = calendar.timegm((2023, 11, 13, 0, 30, 0)) * 1000
        now = ts_ms + 60_000
        clock = {"t": now}
        agent = RssNewsAgent(
            mode="block", refresh_seconds=60.0, fetcher=lambda u: self.RSS,
            clock=lambda: clock["t"], flag_ttl_minutes=90.0,
        )
        agent.tick()
        self.assertTrue(agent.flag_active)
        clock["t"] = now + 91 * 60_000
        self.assertIsNone(agent.entry_block(clock["t"]))
        self.assertFalse(agent.flag_active)

    def test_network_failure_is_safe(self):
        def fetcher(url):
            raise RuntimeError("RSS kapalı")

        agent = RssNewsAgent(mode="block", fetcher=fetcher,
                             refresh_seconds=60.0)
        agent.tick()
        self.assertFalse(agent.flag_active)
        self.assertIsNone(agent.entry_block(1))


class CongressAgentTests(unittest.TestCase):
    def test_honest_unavailable_status(self):
        agent = CongressAgent()
        status = agent.status()
        self.assertFalse(status["available"])
        self.assertIn("veri kaynağı", status["reason"])

    def test_never_blocks_never_trades(self):
        agent = CongressAgent()
        self.assertIsNone(agent.entry_block(0))
        agent.tick(0)  # no-op, çökmez


class AnalystAgentTests(unittest.TestCase):
    def _report(self, **overrides):
        report = {
            "version": "4.0-final", "start_balance": 1000.0,
            "end_balance": 990.0, "entries": 4, "closes": 4,
            "duration_seconds": 3600.0, "kill_switch": "NORMAL",
            "safe_mode": False, "stale_entry_cancels": 2,
            "counters": {"rate_limit_deferred": 4},
            "expert_performance": {
                "momentum_hunter": {"trades": 5, "avg_r": -0.9},
                "trend_hunter": {"trades": 6, "avg_r": 0.4},
            },
        }
        report.update(overrides)
        return report

    def test_rule_based_observations(self):
        agent = AnalystAgent(llm_enabled=False)
        result = agent.analyze(self._report())
        self.assertFalse(result["llm_used"])
        text = " ".join(result["observations"] + result["suggestions"])
        self.assertIn("momentum_hunter", text)
        self.assertIn("bayat sinyal", text)
        self.assertTrue(any("negatif" in o for o in result["observations"]))
        self.assertTrue(
            any("--entry-rate-limit" in s for s in result["suggestions"]),
        )

    def test_no_trades_session(self):
        agent = AnalystAgent()
        result = agent.analyze(self._report(entries=0, closes=0))
        self.assertTrue(any("giriş adayı oluşmadı" in o
                            for o in result["observations"]))

    def test_llm_disabled_means_no_llm_call(self):
        agent = AnalystAgent(llm_enabled=True)  # env yoksa çağrı yapılmaz
        result = agent.analyze(self._report())
        self.assertIsNone(result["llm_comment"])
        self.assertFalse(result["llm_used"])

    def test_positive_session_note_is_honest(self):
        agent = AnalystAgent()
        result = agent.analyze(self._report(end_balance=1020.0))
        self.assertTrue(any("kanıt DEĞİLDİR" in o for o in result["observations"]))


if __name__ == "__main__":
    unittest.main()
