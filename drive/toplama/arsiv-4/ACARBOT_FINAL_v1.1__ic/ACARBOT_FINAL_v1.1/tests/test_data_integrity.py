"""Yorum 1-F — veri bütünlüğü testleri: boşluk, bayatlık, ısınma,
borsalar arası sapma ve güvenli mod.
"""

import pytest

from core.config import DataConfig
from infra.feed import DataIntegrityManager


@pytest.fixture
def dim():
    config = DataConfig(
        warmup_seconds=2.0,
        warmup_min_ticks=3,
        tick_freshness_s=10.0,
        global_stale_s=60.0,
        global_stale_symbol_fraction=0.5,
        cross_exchange_divergence_pct=0.5,
        stale_symbol_cooldown_s=900.0,
    )
    return DataIntegrityManager(config, now_ms=1_700_000_000_000)


class TestWarmup:
    def test_entries_blocked_during_warmup(self, dim):
        base = 1_700_000_000_000
        # Yeterli tick var ama süre dolmadı
        for i in range(5):
            dim.record_tick("X:A", base + i * 100)
        assert not dim.is_warmed_up(base + 1_000)
        allowed, reason = dim.entry_allowed("X:A", base + 1_000)
        assert not allowed
        assert reason == "warmup"

    def test_entries_allowed_after_warmup(self, dim):
        base = 1_700_000_000_000
        for i in range(5):
            dim.record_tick("X:A", base + i * 100)
        # Isınma süresi (2 sn) + tazelik (10 sn) içinde
        later = base + 3_000
        assert dim.is_warmed_up(later)
        allowed, reason = dim.entry_allowed("X:A", later)
        assert allowed
        assert reason is None

    def test_symbol_without_ticks_blocked(self, dim):
        base = 1_700_000_000_000
        for i in range(5):
            dim.record_tick("X:A", base + i * 100)  # A ısınır, B hiç tick almaz
        later = base + 3_000
        allowed, reason = dim.entry_allowed("X:B", later)
        assert not allowed
        assert reason == "stale_symbol"


class TestStaleness:
    def test_stale_symbol_blocks_entry(self, dim):
        base = 1_700_000_000_000
        for i in range(5):
            dim.record_tick("X:A", base + i * 100)  # ısınmayı tamamla
        # 30 sn sonra tick taze değil
        later = base + 30_000
        allowed, reason = dim.entry_allowed("X:A", later)
        assert not allowed
        assert reason == "stale_symbol"

    def test_marked_stale_cooldown(self, dim):
        base = 1_700_000_000_000
        dim.record_tick("X:A", base)
        dim.record_tick("X:A", base + 1_000)
        dim.mark_symbol_stale("X:A", base + 2_000)
        # Taze tick gelse bile bayat damgası engeller
        dim.record_tick("X:A", base + 2_500)
        allowed, reason = dim.entry_allowed("X:A", base + 3_000)
        assert not allowed
        assert reason == "stale_symbol"


class TestCandleGaps:
    def test_no_gap_initially(self, dim):
        base = 1_700_000_000_000
        assert dim.on_candle_closed("X:A", base, base) == "ok"

    def test_gap_detected_on_missing_candles(self, dim):
        base = 1_700_000_000_000
        dim.on_candle_closed("X:A", base, base)
        # 3 mum sonra (1 mum boşluk var: base+300k atlandı)
        status = dim.on_candle_closed("X:A", base + 2 * 300_000, base + 600_000)
        assert status == "gap_backfilled"

    def test_gap_blocked_when_backfill_disabled(self):
        dim = DataIntegrityManager(DataConfig(gap_backfill_enabled=False))
        base = 1_700_000_000_000
        dim.on_candle_closed("X:A", base, base)
        status = dim.on_candle_closed("X:A", base + 2 * 300_000, base + 600_000)
        assert status == "gap_blocked"

    def test_continuous_candles_no_gap(self, dim):
        base = 1_700_000_000_000
        dim.on_candle_closed("X:A", base, base)
        assert dim.on_candle_closed("X:A", base + 300_000, base + 300_000) == "ok"
        assert dim.on_candle_closed("X:A", base + 600_000, base + 600_000) == "ok"


class TestCrossExchangeDivergence:
    def test_small_divergence_allowed(self, dim):
        dim.record_cross_price("binance", "BTCUSDT", 100.0)
        dim.record_cross_price("okx", "BTCUSDT", 100.2)  # %0.2
        assert dim.divergence_blocked("BTCUSDT") is False

    def test_large_divergence_blocks(self, dim):
        dim.record_cross_price("binance", "BTCUSDT", 100.0)
        dim.record_cross_price("okx", "BTCUSDT", 101.0)  # %1.0 > 0.5
        assert dim.divergence_blocked("BTCUSDT") is True
        base = 1_700_000_000_000
        for i in range(5):
            dim.record_tick("X:BTCUSDT", base + i * 100)  # ısınma koşulu
        allowed, reason = dim.entry_allowed("X:BTCUSDT", base + 3_000)
        assert not allowed
        assert reason == "cross_exchange_divergence"

    def test_single_exchange_no_comparison(self, dim):
        dim.record_cross_price("binance", "BTCUSDT", 100.0)
        assert dim.divergence_blocked("BTCUSDT") is False


class TestSafeMode:
    def test_global_staleness_triggers_safe_mode(self, dim):
        """Sembollerin yarısından fazlası bayatsa GÜVENLİ MOD (Y1-F)."""
        base = 1_700_000_000_000
        # Isınmayı tamamla
        for symbol in ("X:A", "X:B", "X:C", "X:D"):
            for i in range(5):
                dim.record_tick(symbol, base + i * 100)
        warm_base = base + 3_000
        assert dim.is_warmed_up(warm_base)
        # A ve B taze kalsın, C ve D bayatsın (%50 ≥ eşik)
        dim.record_tick("X:A", warm_base)
        dim.record_tick("X:B", warm_base)
        dim.update_global_state(warm_base + 61_000)
        assert dim.safe_mode is True
        assert dim.safe_mode_reason == "global_stale_data"
        allowed, reason = dim.entry_allowed("X:A", warm_base + 61_000)
        assert not allowed
        assert reason == "safe_mode"

    def test_safe_mode_releases_when_fresh(self, dim):
        base = 1_700_000_000_000
        for symbol in ("X:A", "X:B"):
            for i in range(5):
                dim.record_tick(symbol, base + i * 100)
        warm = base + 1_500  # ısınma (2 sn) henüz tamamlanmadı
        dim.update_global_state(warm)
        assert dim.safe_mode is True  # warmup
        assert dim.safe_mode_reason == "warmup"
        dim.record_tick("X:A", warm)
        dim.record_tick("X:B", warm)
        dim.update_global_state(warm + 1_000)  # ısınma bitti, veri taze
        assert dim.safe_mode is False
