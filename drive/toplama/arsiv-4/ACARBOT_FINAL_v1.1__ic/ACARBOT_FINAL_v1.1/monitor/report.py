"""Günlük rapor ve motor karşılaştırması (Y1-5. aşama, Y2 operasyonel)."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from backtest.metrics import _group_stats
from state.store import StateStore


def utc_midnight_ms(now: datetime | None = None) -> int:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    midnight = datetime.combine(current.date(), time.min, tzinfo=timezone.utc)
    return int(midnight.timestamp() * 1000)


class PerformanceReporter:
    """SQLite kayıtlarından günlük/oturum raporu üretir."""

    def __init__(self, store: StateStore | None = None) -> None:
        self.store = store

    def daily_report(
        self,
        equity: float,
        unrealized_pnl: float,
        open_positions: int,
        kill_switch_state: str,
        safe_mode: bool,
        now: datetime | None = None,
        session_trades: list[dict[str, Any]] | None = None,
    ) -> str:
        """UTC günü özeti: gerçekleşen, açık risk, motor/sembol kırılımı."""
        if session_trades is None:
            session_trades = self._trades_since(utc_midnight_ms(now))
        closes = [t for t in session_trades if t.get("type") == "CLOSE"]
        realized = sum(float(t.get("pnl", 0.0)) for t in closes)
        wins = [t for t in closes if float(t.get("pnl", 0.0)) > 0]
        fees = sum(
            float(t.get("entry_fee", 0.0)) + float(t.get("fee", 0.0))
            for t in closes
        )
        funding = sum(float(t.get("funding_paid", 0.0)) for t in closes)
        rs = [
            float(t["r_multiple"]) for t in closes
            if isinstance(t.get("r_multiple"), (int, float))
        ]
        lines = [
            "=== GÜNLÜK RAPOR (UTC) ===",
            f"Gerçekleşen PnL: {realized:+.2f} USDT",
            f"Gerçekleşmeyen: {unrealized_pnl:+.2f} USDT | Equity: {equity:.2f}",
            f"Kapanan işlem: {len(closes)} | Kazanan: {len(wins)}",
            f"Ücret: {fees:.2f} | Funding: {funding:.2f}",
            f"Ort. R: {sum(rs)/len(rs):+.2f}" if rs else "Ort. R: yok (işlem yok)",
            f"Açık pozisyon: {open_positions} | Kill switch: {kill_switch_state}",
            f"Güvenli mod: {'EVET' if safe_mode else 'hayır'}",
        ]
        engines = _group_by(closes, "motor")
        if engines:
            lines.append("-- Motorlar --")
            for engine, stats in engines.items():
                lines.append(
                    f"{engine}: {stats['trades']} işlem, net {stats['net_pnl']:+.2f}, "
                    f"kazanma %{stats['win_rate']*100:.0f}"
                )
        symbols = _group_by(closes, "symbol")
        if symbols:
            lines.append("-- Semboller --")
            for symbol, stats in sorted(
                symbols.items(), key=lambda kv: kv[1]["net_pnl"]
            )[:5]:
                lines.append(f"{symbol}: {stats['net_pnl']:+.2f} ({stats['trades']})")
        return "\n".join(lines)

    def session_summary(self, trades: list[dict[str, Any]]) -> str:
        closes = [t for t in trades if t.get("type") == "CLOSE"]
        opens = [t for t in trades if t.get("type") == "OPEN"]
        expired = [t for t in trades if t.get("type") == "ORDER_EXPIRED"]
        realized = sum(float(t.get("pnl", 0.0)) for t in closes)
        return (
            f"Oturum: {len(opens)} giriş, {len(closes)} kapanış, "
            f"{len(expired)} dolmayan emir, net {realized:+.2f} USDT"
        )

    def _trades_since(self, start_ms: int) -> list[dict[str, Any]]:
        if self.store is None:
            return []
        trades = self.store.load_trades(limit=100_000)
        return [
            t for t in trades
            if isinstance(t.get("timestamp"), (int, float))
            and t["timestamp"] >= start_ms
        ]


def _group_by(closes: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for trade in closes:
        groups.setdefault(str(trade.get(key, "?")), []).append(trade)
    return {k: _group_stats(v) for k, v in groups.items()}


class SimpleMetrics:
    """İşlem içi sayaçlar; Prometheus metin formatında dışa aktarılabilir."""

    def __init__(self) -> None:
        self.counters: dict[str, float] = {}

    def inc(self, name: str, value: float = 1.0) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + value

    def set(self, name: str, value: float) -> None:
        self.counters[name] = value

    def render_prometheus(self) -> str:
        lines = []
        for name, value in self.counters.items():
            safe = name.replace(".", "_").replace("-", "_")
            lines.append(f"{safe} {value}")
        return "\n".join(lines) + "\n"
