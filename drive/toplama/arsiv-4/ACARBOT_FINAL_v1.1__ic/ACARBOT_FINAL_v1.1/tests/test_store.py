"""Yorum 2 operasyonel + Yorum 3 — SQLite deposu testleri:
ts indeksi, hızlı günlük PnL, kısılmış kayıt, yedekleme, equity/olay tabloları.
"""

from datetime import datetime, timezone

import pytest

from core.config import OpsConfig
from state.store import StateStore


@pytest.fixture
def store(tmp_path):
    s = StateStore(tmp_path / "test_state.sqlite3", OpsConfig())
    yield s
    s.close()


class TestTrades:
    def test_append_and_load(self, store):
        store.append_trade({
            "type": "CLOSE", "symbol": "X:T", "side": "LONG",
            "pnl": 5.5, "timestamp": 1_700_000_000_000,
        })
        trades = store.load_trades()
        assert len(trades) == 1
        assert trades[0]["pnl"] == pytest.approx(5.5)

    def test_realized_pnl_since_midnight_uses_index(self, store):
        """Günlük PnL SQL SUM ile — tüm tabloyu JSON çözmek yok (Y2)."""
        today = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        midnight_ms = 1768435200000  # 2026-01-15 00:00 UTC
        store.append_trade({"type": "CLOSE", "pnl": 10.0, "timestamp": midnight_ms + 1000})
        store.append_trade({"type": "CLOSE", "pnl": -4.0, "timestamp": midnight_ms + 2000})
        store.append_trade({"type": "CLOSE", "pnl": 99.0, "timestamp": midnight_ms - 2000})  # dün
        store.append_trade({"type": "OPEN", "pnl": None, "timestamp": midnight_ms + 3000})
        realized = store.realized_pnl_since_utc_midnight(today)
        assert realized == pytest.approx(6.0)

    def test_invalid_now_rejected(self, store):
        with pytest.raises(ValueError):
            store.realized_pnl_since_utc_midnight(datetime(2026, 1, 1))  # naive


class TestThrottledSave:
    def test_save_only_when_due(self, store):
        payload = {"mode": "paper", "balance": 1000.0}
        store.mark_dirty()
        # İlk kayıt: min aralık henüz dolmadı → yine de ilk mark_dirty ile
        # kaydedilmez, aralığı aşınca kaydedilir
        assert store.save_state_if_due(payload, now_ms=0) is False
        assert store.save_state_if_due(payload, now_ms=1_100) is True
        assert store.load_state()["balance"] == 1000.0

    def test_force_save_always_writes(self, store):
        payload = {"mode": "paper", "balance": 500.0}
        assert store.save_state_if_due(payload, now_ms=0, force=True) is True
        assert store.load_state()["balance"] == 500.0

    def test_not_dirty_skips(self, store):
        assert store.save_state_if_due({"a": 1}, now_ms=100_000) is False


class TestBackupAndRecovery:
    def test_backup_creates_file(self, store, tmp_path):
        store.save_state({"mode": "paper", "balance": 777.0})
        target = store.backup(tmp_path / "backup.sqlite3")
        assert target.exists()
        restored = StateStore(target)
        try:
            assert restored.load_state()["balance"] == 777.0
        finally:
            restored.close()

    def test_rotate_backups(self, store):
        prefix = store.path.with_suffix("").name
        for i in range(7):
            store.backup(f"{store.path.parent}/{prefix}_backup_{i}.sqlite3")
        removed = store.rotate_backups(keep=5)
        # 7 yedek -> 2 tanesi silinir
        assert len(removed) == 2


class TestExtraTables:
    def test_equity_points(self, store):
        store.append_equity_point(1_000, 1_005.5, 0.5)
        store.append_equity_point(2_000, 1_010.0, 0.0)
        curve = store.load_equity_curve()
        assert curve == [(1_000, 1_005.5), (2_000, 1_010.0)]

    def test_order_events(self, store):
        store.append_order_event("abc123", 1_000, "X:T", "NEW", {"qty": 5.0})
        row = store._connection.execute(
            "SELECT order_id, status FROM orders"
        ).fetchone()
        assert row == ("abc123", "NEW")

    def test_events(self, store):
        store.append_event(1_000, "critical", "KILL_SWITCH", "tetiklendi")
        row = store._connection.execute(
            "SELECT level, code FROM events"
        ).fetchone()
        assert row == ("critical", "KILL_SWITCH")

    def test_checkpoint_does_not_raise(self, store):
        store.append_trade({"type": "CLOSE", "pnl": 1.0, "timestamp": 0})
        store.critical_checkpoint()


class TestSecurity:
    def test_files_are_restricted(self, store, tmp_path):
        import os
        mode = os.stat(store.path).st_mode & 0o777
        assert mode == 0o600
