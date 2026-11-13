"""Giriş politikası — kapı zinciri, mum-başına tek deneme, MTF teyidi.

ARŞİVDEN DEVRALINAN SÖZLEŞMELER
  * ONE_ATTEMPT_PER_CLOSED_BAR: bir sembol-mum anahtarı deneme hakkını bir
    kez kullanır. İlk ret (spread/ilk fiyat sapması) hakkı tüketir; sonraki
    mumda yeniden açılır. Bu kalıcı kilit DEĞİLDİR ve gevşetilmemiştir.
  * Kapı retleri ayrı ayrı sayılır. "Değerlendirme tekrarı" ekonomik ret
    sayılmaz (v9.4.4 doğruluk düzeltmesi).
  * unique_signal_count ayrı tutulur; tekrar eden değerlendirmeler sinyal
    sayısını şişirmez.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import Candle, GateResult, Quote, Side, Signal
from . import indicators


@dataclass
class PolicyConfig:
    strategy: str = "fade"            # fade | momentum
    maker_only: bool = True
    max_spread_bps: float = 8.0
    max_price_deviation_bps: float = 25.0
    require_mtf: bool = True
    rsi_long_max: float = 72.0        # fade LONG için aşırı alım engeli
    rsi_short_min: float = 28.0
    max_choppiness: float = 61.5
    min_atr_pct: float = 0.05
    max_atr_pct: float = 6.0
    max_extension_atr: float = 3.0
    funding_blackout_min: float = 3.0
    max_contra_flow: float = 35.0
    roundtrip_fee_bps: float = 7.0
    slippage_bps_per_side: float = 3.0
    min_edge_ratio: float = 1.15      # beklenen hareket / toplam maliyet
    one_attempt_per_closed_bar: bool = True


@dataclass
class PolicyState:
    attempted_bars: set[str] = field(default_factory=set)
    gate_counts: dict[str, int] = field(default_factory=dict)
    unique_signals: set[str] = field(default_factory=set)
    evaluation_repeats: int = 0

    def count(self, code: str) -> None:
        self.gate_counts[code] = self.gate_counts.get(code, 0) + 1

    def summary(self) -> dict[str, Any]:
        return {
            "attempted_bars": len(self.attempted_bars),
            "unique_signal_count": len(self.unique_signals),
            "evaluation_repeats": self.evaluation_repeats,
            "gate_counts": dict(sorted(self.gate_counts.items(), key=lambda kv: -kv[1])),
        }


def closed_bar_key(symbol: str, ts_ms: int, bar_ms: int = 60_000) -> str:
    """Dedektör penceresi kapanmış mum anahtarı. 1 dakikalık varsayılan."""
    return f"{symbol}:{(ts_ms // bar_ms) * bar_ms}"


def total_cost_bps(cfg: PolicyConfig, spread_bps: float) -> float:
    return cfg.roundtrip_fee_bps + 2.0 * cfg.slippage_bps_per_side + max(0.0, spread_bps)


class EntryPolicy:
    """Sinyali işleme çevirmeden önceki sert kapı zinciri."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.cfg = config or PolicyConfig()
        self.state = PolicyState()

    def entry_side(self, signal: Signal) -> Side:
        """Dedektör piyasa yönünü verir; fade bunu tersine çevirir."""
        return signal.side.opposite if self.cfg.strategy == "fade" else signal.side

    def evaluate(
        self, signal: Signal, quote: Quote | None,
        candles_1m: list[Candle], candles_15m: list[Candle] | None = None,
        funding: dict[str, float] | None = None,
    ) -> tuple[bool, list[GateResult], dict[str, Any]]:
        cfg = self.cfg
        gates: list[GateResult] = []
        side = self.entry_side(signal)
        bar = closed_bar_key(signal.symbol, signal.ts_ms)
        metrics: dict[str, Any] = {"entry_side": side.value, "closed_bar_key": bar}

        def gate(name: str, ok: bool, code: str = "", detail: str = "",
                 value: float | None = None, threshold: float | None = None) -> bool:
            g = GateResult(name, ok, code or name.upper(), detail, value, threshold)
            gates.append(g)
            if not ok:
                self.state.count(g.code)
            return ok

        # 1) mum-başına tek deneme hakkı
        if cfg.one_attempt_per_closed_bar:
            if bar in self.state.attempted_bars:
                self.state.evaluation_repeats += 1
                gate("one_attempt_per_bar", False, "ONE_ATTEMPT_PER_CLOSED_BAR",
                     "Bu sembol-mum deneme hakkını kullandı")
                return False, gates, metrics
            self.state.attempted_bars.add(bar)
        self.state.unique_signals.add(signal.signal_id)

        # 2) makas
        spread = quote.spread_bps if quote else float("inf")
        metrics["spread_bps"] = spread if quote else 0.0
        if not gate("spread", spread <= cfg.max_spread_bps, "SPREAD_TOO_WIDE",
                    "Makas eşiği aştı", spread, cfg.max_spread_bps):
            return False, gates, metrics

        # 3) canlı fiyat sapması — sinyalden bu yana fiyat kaçtı?
        if quote:
            ref = quote.ask if side is Side.LONG else quote.bid
            dev = abs(ref / signal.price - 1.0) * 10_000.0 if signal.price > 0 else 1e9
            metrics["price_deviation_bps"] = dev
            if not gate("price_deviation", dev <= cfg.max_price_deviation_bps,
                        "PRICE_MOVED_AWAY", "Fiyat sinyalden uzaklaştı",
                        dev, cfg.max_price_deviation_bps):
                return False, gates, metrics

        # 4) indikatör ısınması
        snap = indicators.snapshot(candles_1m)
        metrics.update({f"i1m_{k}": v for k, v in snap.items()})
        if snap["candles"] < 60:
            gate("indicator_warmup", False, "INDICATOR_WARMUP",
                 f"Yalnız {snap['candles']} mum")
            return False, gates, metrics

        atr_pct = snap["atr_pct"]
        if atr_pct is None:
            gate("atr_ready", False, "ATR_NOT_READY", "ATR hesaplanamadı")
            return False, gates, metrics
        metrics["atr_pct"] = atr_pct
        if not gate("atr_band", cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct,
                    "ATR_OUT_OF_BAND", "Volatilite bandı dışında",
                    atr_pct, cfg.max_atr_pct):
            return False, gates, metrics

        # 5) testere
        chop = snap["choppiness"]
        if chop is not None:
            metrics["choppiness"] = chop
            if not gate("choppiness", chop <= cfg.max_choppiness,
                        "CHOPPY_REGIME", "Testere rejimi", chop, cfg.max_choppiness):
                return False, gates, metrics

        # 6) RSI aşırılığı
        r = snap["rsi"]
        if r is not None:
            ok = r <= cfg.rsi_long_max if side is Side.LONG else r >= cfg.rsi_short_min
            if not gate("rsi_extreme", ok, "RSI_EXTREME",
                        "RSI giriş yönü için aşırı", r,
                        cfg.rsi_long_max if side is Side.LONG else cfg.rsi_short_min):
                return False, gates, metrics

        # 7) MTF teyidi (15m)
        mtf_aligned = True
        if cfg.require_mtf and candles_15m:
            s15 = indicators.snapshot(candles_15m)
            metrics.update({f"i15m_{k}": v for k, v in s15.items()})
            t15 = s15["ema_trend"]
            if t15 is not None and t15 != 0:
                mtf_aligned = (t15 > 0) == (side is Side.LONG)
                if not gate("mtf_alignment", mtf_aligned, "MTF_CONFLICT",
                            "15m trend giriş yönüne ters", float(t15)):
                    return False, gates, metrics
        metrics["mtf_aligned"] = mtf_aligned

        # 8) aşırı uzama
        atr_abs = snap["atr"]
        if atr_abs and atr_abs > 0 and candles_1m:
            base = indicators.ema([c.close for c in candles_1m], 21)
            if base:
                ext = abs(signal.price - base) / atr_abs
                metrics["extension_atr"] = ext
                if not gate("extension", ext <= cfg.max_extension_atr,
                            "OVER_EXTENDED", "ATR'ye göre aşırı uzama",
                            ext, cfg.max_extension_atr):
                    return False, gates, metrics

        # 9) ters para akışı
        flow = signal.flow_score
        aligned_flow = flow if side is Side.LONG else -flow
        if not gate("flow_alignment", aligned_flow >= -cfg.max_contra_flow,
                    "CONTRA_FLOW", "Para akışı girişe ters",
                    aligned_flow, -cfg.max_contra_flow):
            return False, gates, metrics

        # 10) funding karartması
        f = funding or {}
        mins = float(f.get("minutes_to_funding", 999.0))
        metrics["funding_rate"] = float(f.get("rate", 0.0))
        metrics["minutes_to_funding"] = mins
        if not gate("funding_window", mins >= cfg.funding_blackout_min,
                    "FUNDING_BLACKOUT", "Funding anına çok yakın",
                    mins, cfg.funding_blackout_min):
            return False, gates, metrics

        # 11) maliyet / kenar — EN SERT KAPI
        cost = total_cost_bps(cfg, spread if quote else 0.0)
        expected = max(0.0, (atr_pct or 0.0) * 100.0 * 0.35)
        metrics["roundtrip_cost_bps"] = cost
        metrics["expected_move_bps"] = expected
        ratio = expected / cost if cost > 0 else 0.0
        metrics["edge_ratio"] = ratio
        if not gate("edge_vs_cost", ratio >= cfg.min_edge_ratio,
                    "EDGE_BELOW_COST", "Beklenen hareket maliyeti karşılamıyor",
                    ratio, cfg.min_edge_ratio):
            return False, gates, metrics

        self.state.count("ACCEPTED")
        return True, gates, metrics