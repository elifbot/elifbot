"""Backtest yürütme varsayımları: gecikme ve yön-aware kayma.

Bu modül emir defteri/kuyruk simülasyonu DEĞİLDİR. Sabit ve ATR'ye bağlı
kaymayı muhafazakâr bir stres varsayımı olarak uygular. Varsayılanlar sıfırdır;
böylece eski backtest davranışı korunur.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionModel:
    """Giriş ve çıkışta fiyatı daima pozisyon aleyhine kötüleştirir."""

    latency_ms: int = 0
    fixed_slippage_bps: float = 0.0
    atr_slippage_fraction: float = 0.0
    max_slippage_bps: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.latency_ms,
            self.fixed_slippage_bps,
            self.atr_slippage_fraction,
        )
        if any(not math.isfinite(float(v)) or float(v) < 0 for v in values):
            raise ValueError("gecikme ve kayma parametreleri negatif olamaz")
        if self.max_slippage_bps is not None:
            if not math.isfinite(self.max_slippage_bps) or self.max_slippage_bps < 0:
                raise ValueError("max_slippage_bps negatif olamaz")

    def slippage_rate(self, price: float, atr: float | None = None) -> float:
        """Toplam kayma oranı (bps değil, ondalık oran)."""
        if not math.isfinite(price) or price <= 0:
            raise ValueError("fiyat pozitif olmalı")
        rate = self.fixed_slippage_bps / 10_000.0
        if atr is not None and self.atr_slippage_fraction > 0:
            if math.isfinite(atr) and atr > 0:
                rate += self.atr_slippage_fraction * (atr / price)
        if self.max_slippage_bps is not None:
            rate = min(rate, self.max_slippage_bps / 10_000.0)
        return rate

    def execution_price(
        self,
        raw_price: float,
        side: str,
        *,
        is_entry: bool,
        atr: float | None = None,
    ) -> float:
        """Yürütme fiyatını döndürür.

        LONG giriş daha pahalı, LONG çıkış daha düşük; SHORT giriş daha düşük,
        SHORT çıkış daha pahalı olur. Yani kayma her iki yönde de maliyettir.
        """
        side = side.upper()
        if side not in ("LONG", "SHORT"):
            raise ValueError("side LONG veya SHORT olmalı")
        if not math.isfinite(raw_price) or raw_price <= 0:
            raise ValueError("ham fiyat pozitif olmalı")
        rate = self.slippage_rate(raw_price, atr)
        direction = 1.0 if side == "LONG" else -1.0
        if is_entry:
            adjusted = raw_price * (1.0 + direction * rate)
        else:
            adjusted = raw_price * (1.0 - direction * rate)
        if adjusted <= 0 or not math.isfinite(adjusted):
            raise ValueError("kayma sonrası fiyat geçersiz")
        return adjusted


__all__ = ["ExecutionModel"]
