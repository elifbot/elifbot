"""ACARBOT v2.0 — Beta tahmini, BTC şok testi, beta ayarlı yön tavanı.

Şartname (A. Zorunlu, madde 3):
  "Beta ayarlı net yön tavanı + BTC şok testi. Betalar gerçek 5 dakikalık
   getirilerden hesaplansın, sabit değerle değil. Her girişten önce
   'BTC ∓%3 giderse toplam kayıp' hesaplanıp equity'nin belirli bir
   yüzdesini (%15) aşıyorsa giriş engellensin."

Kurallar:
  - Beta = cov(r_sembol, r_btc) / var(r_btc) — son N adet 5 dakikalık
    kapanış getirisi üzerinden. Yeterli getiri yoksa beta None döner ve
    şok testi "uygulanmadı" olarak RAPORLANIR (yer tutucu beta kullanılmaz).
  - Şok testi: BTC %∓s senaryosunda portföy + aday pozisyonun tahmini
    kaybı = Σ beta_i × nominal_i × şok. En kötü senaryo, equity'nin
    cap_pct'ini aşarsa giriş engellenir.
  - Beta ayarlı yön tavanı: Σ beta_i × işaretli nominal_i tavanı aşarsa
    giriş engellenir. Beta'sı bilinmeyen sembol ham nominaliyle sayılır
    (muhafazakâr; beta 1.0 varsayımı DEĞİL, yüzey değeriyle sayım).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from core.config import RiskGateConfig
from core.portfolio import Position


def returns_from_closes(closes: Sequence[float]) -> list[float]:
    """Kapanışlardan basit getiriler (oransal)."""
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0 and isfinite(closes[i]) and isfinite(prev):
            out.append(closes[i] / prev - 1.0)
    return out


class BetaEstimator:
    """Sembol ↔ BTC 5 dakikalık getiri betaları (GERÇEK veri)."""

    def __init__(self, cfg: RiskGateConfig | None = None) -> None:
        self.cfg = cfg or RiskGateConfig()

    def beta(
        self,
        symbol_closes: Sequence[float],
        btc_closes: Sequence[float],
    ) -> float | None:
        """Son N ortak getiriden beta. Yetersiz veri → None ("uygulanmadı")."""
        r_s = returns_from_closes(symbol_closes)
        r_b = returns_from_closes(btc_closes)
        n = min(len(r_s), len(r_b), self.cfg.beta_max_returns)
        if n < self.cfg.beta_min_returns:
            return None
        r_s = r_s[-n:]
        r_b = r_b[-n:]
        mean_s = sum(r_s) / n
        mean_b = sum(r_b) / n
        cov = sum((a - mean_s) * (b - mean_b) for a, b in zip(r_s, r_b)) / n
        var_b = sum((b - mean_b) ** 2 for b in r_b) / n
        if var_b <= 1e-18:
            return None
        value = cov / var_b
        if not isfinite(value):
            return None
        return value


@dataclass(frozen=True)
class ShockTestResult:
    available: bool
    worst_loss: float = 0.0        # en kötü senaryodaki tahmini kayıp (USDT)
    cap: float = 0.0               # izin verilen üst sınır (USDT)
    loss_pct: float = 0.0          # equity'nin yüzdesi olarak
    blocked: bool = False
    reason: str | None = None
    betas: dict[str, float] | None = None

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "worst_loss": round(self.worst_loss, 4),
            "cap": round(self.cap, 4),
            "loss_pct": round(self.loss_pct, 3),
            "blocked": self.blocked,
            "reason": self.reason,
            "betas": (
                None if self.betas is None
                else {k: round(v, 3) for k, v in self.betas.items()}
            ),
        }


def base_asset_of(symbol: str) -> str:
    """'binance:BTCUSDT' → 'BTC'; 'BTC-USDT-SWAP' → 'BTC'."""
    core = symbol.rsplit(":", 1)[-1].upper()
    core = core.replace("-USDT-SWAP", "").replace("-USDC-SWAP", "")
    return core.replace("USDT", "").replace("USDC", "")


class BtcShockTester:
    """Giriş öncesi BTC şok senaryosu hesabı."""

    def __init__(self, cfg: RiskGateConfig | None = None) -> None:
        self.cfg = cfg or RiskGateConfig()

    def evaluate(
        self,
        positions: dict[str, Position],
        prices: dict[str, float],
        planned_symbol: str | None,
        planned_side: str | None,
        planned_notional: float,
        planned_beta: float | None,
        betas: dict[str, float],
        equity: float,
    ) -> ShockTestResult:
        """Şok senaryolarını değerlendirir.

        betas: mevcut sembollerin beta haritası (base asset anahtarlı).
        planned_beta None ve plan varsa → test "uygulanmadı" döner.
        """
        cap = equity * self.cfg.btc_shock_loss_cap_pct / 100.0
        shock = self.cfg.btc_shock_pct / 100.0

        # Aday pozisyon beta'sı yoksa test uygulanamaz (rapor şeffaf).
        if planned_symbol is not None and planned_beta is None:
            return ShockTestResult(
                available=False, cap=cap,
                reason="beta_uygulanmadi",
            )

        exposures: list[tuple[str, float]] = []  # (anahtar, beta×signed nominal)
        for symbol, position in positions.items():
            price = prices.get(symbol, position.entry)
            notional = position.quantity * price
            signed = notional if position.side == "LONG" else -notional
            beta = betas.get(base_asset_of(symbol))
            if beta is None:
                # Bilinmeyen beta: ham nominal ile sayılır (yüzey değeri,
                # uydurma beta değil) — muhafazakâr davranış korunur.
                exposures.append((symbol, signed))
            else:
                exposures.append((symbol, beta * signed))
        if planned_symbol is not None and planned_notional > 0:
            signed = planned_notional if planned_side == "LONG" else -planned_notional
            exposures.append((planned_symbol, planned_beta * signed))  # type: ignore[operator]

        worst_loss = 0.0
        worst_scenario = 0.0
        for scenario in (-shock, shock):
            pnl = sum(exposure * scenario for _, exposure in exposures)
            if -pnl > worst_loss:
                worst_loss = -pnl
                worst_scenario = scenario
        loss_pct = worst_loss / equity * 100.0 if equity > 0 else 0.0
        blocked = worst_loss > cap
        return ShockTestResult(
            available=True,
            worst_loss=worst_loss,
            cap=cap,
            loss_pct=loss_pct,
            blocked=blocked,
            reason="btc_shok_tavanı" if blocked else None,
            betas=betas or None,
        )


def beta_adjusted_directional_notional(
    positions: dict[str, Position],
    prices: dict[str, float],
    planned_symbol: str | None,
    planned_side: str | None,
    planned_notional: float,
    planned_beta: float | None,
    betas: dict[str, float],
) -> float:
    """Σ beta_i × işaretli nominal_i. Beta'sız sembol yüzey değeriyle girer."""
    total = 0.0
    for symbol, position in positions.items():
        price = prices.get(symbol, position.entry)
        notional = position.quantity * price
        signed = notional if position.side == "LONG" else -notional
        beta = betas.get(base_asset_of(symbol))
        total += signed if beta is None else beta * signed
    if planned_symbol is not None and planned_notional > 0:
        signed = planned_notional if planned_side == "LONG" else -planned_notional
        total += signed if planned_beta is None else planned_beta * signed
    return total
