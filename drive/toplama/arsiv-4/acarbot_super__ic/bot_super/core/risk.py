"""Risk yönetimi — süper sürüm.

Kapsam (üç inceleme yorumunun birleşimi):

  [Y1-A] Emir yaşam döngüsü -> exec/orders.py (burada boyutlandırma tarafı)
  [Y1-B] 25 USDT zarar garantisi değil  -> NET tavan: boyutlandırma ve acil
         durdurma tüm maliyetleri (giriş ücreti + çıkış ücreti + kayma +
         ek kayma) ÖNCEDEN düşer.
  [Y1-C] Funding ve likidasyon hesaplaması -> FundingConfig + likidasyon izleme
  [Y1-G] Portföy yönetimi -> korelasyon grupları, toplam risk tavanı,
         yönsel denge, portföy drawdown koruması
  [Y2-4] Net PnL tabanlı zarar kontrolü
  [Y2-7] Portföy düzeyi risk limiti + kill switch
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from core.config import FundingConfig, SuperConfig
from core.portfolio import (
    Portfolio,
    compute_funding_payment,
    compute_liquidation_price,
)


class MaxPositionsReached(Exception):
    code = "MAX_POSITIONS_REACHED"


class InsufficientFunds(ValueError):
    code = "INSUFFICIENT_FUNDS"


class DailyLossLimitReached(ValueError):
    code = "DAILY_LOSS_LIMIT"


class PortfolioRiskBlocked(ValueError):
    code = "PORTFOLIO_RISK_BLOCKED"


class KillSwitchActive(Exception):
    code = "KILL_SWITCH_ACTIVE"


class KillSwitchState(str, Enum):
    NORMAL = "NORMAL"
    SOFT_STOP = "SOFT_STOP"      # yeni giriş yok, açık pozisyonlar yönetilir
    HARD_HALT = "HARD_HALT"      # her şey kapatılır, bot durur


@dataclass(frozen=True)
class TradePlan:
    side: str
    entry: float
    quantity: float
    margin: float
    notional: float
    stop_loss: float
    take_profit: float | None
    leverage: float
    estimated_entry_fee: float
    estimated_exit_cost: float
    estimated_funding_buffer: float
    net_risk_at_stop: float          # R birimi: stop'a gidilirse beklenen NET zarar
    liquidation_price: float
    rejection_code: str | None = None


@dataclass
class RiskDecision:
    allowed: bool
    reason: str | None = None


class RiskManager:
    """Boyutlandırma + portföy kontrolleri + kill switch.

    Boyutlandırma formülü (Y1-B / Y2-4 düzeltmesi):

        net_risk = notional * stop_pct
                 + notional * (maker_fee + taker_fee + kayma + ek_kayma)
                 + funding_tamponu
        net_risk <= max_loss_per_position (25 USDT)

    Eski kod brüt PnL üzerinden -25 kontrolü yapıyor, ücret/kayma sonra
    ekleniyordu; gap senaryosunda -25,53 çıkıyordu. Artık hem planlama hem
    acil çıkış NET hesaplar.
    """

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        acc = self.config.account
        if abs(acc.margin_per_position * acc.leverage - acc.max_notional_per_position) > 1e-8:
            raise ValueError("margin * leverage == max_notional olmalı")
        self.kill_switch_state = KillSwitchState.NORMAL

    # ------------------------------------------------------------------
    # Maliyet modeli
    # ------------------------------------------------------------------

    def round_trip_cost_rate(self) -> float:
        acc = self.config.account
        return (
            acc.maker_fee_rate
            + acc.taker_fee_rate
            + acc.stop_slippage_rate
            + acc.extra_slippage_rate
        )

    def estimated_funding_buffer(self, planned_hold_hours: float = 2.0) -> float:
        """Tutma süresi için muhafazakâr funding tahmini (rate > 0 = LONG öder)."""
        f = self.config.funding
        if not f.enabled:
            return 0.0
        periods = max(1, int(planned_hold_hours / f.interval_hours) + 1)
        return (
            self.config.account.max_notional_per_position
            * f.default_rate_per_8h
            * periods
        )

    # ------------------------------------------------------------------
    # Boyutlandırma
    # ------------------------------------------------------------------

    def plan(
        self,
        entry: float,
        stop_distance_fraction: float,
        side: str,
        motor: str = "fade",
        atr: float | None = None,
    ) -> TradePlan:
        """Net-riske göre boyutlandırılmış işlem planı üretir.

        Nominal tavanı (500) ve net zarar tavanını (25) AYNI ANDA uygular;
        ikisinden küçük olan belirleyicidir. Yorum 2 #4'ün tespiti doğruydu:
        dar stoplarda asıl sınırlayıcı nominaldir — bu durumda stop mesafesi
        zaten küçük olduğundan tipik net risk ~2-3 USDT olur ve 25 USDT
        gerçek bir TAVAN olarak (garanti değil, limit olarak) çalışır.
        """
        acc = self.config.account
        if not isfinite(entry) or entry <= 0:
            raise ValueError("entry pozitif olmalı")
        if not 0 < stop_distance_fraction < 1:
            raise ValueError("stop mesafesi (0,1) aralığında olmalı")
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side LONG veya SHORT olmalı")

        cost_rate = self.round_trip_cost_rate()
        funding_buffer = self.estimated_funding_buffer()
        # Notional üst sınırı: net zarar tavanına sığan en büyük pozisyon.
        per_unit_risk_rate = stop_distance_fraction + cost_rate
        risk_capped_notional = (
            (acc.max_loss_per_position - funding_buffer) / per_unit_risk_rate
        )
        notional = min(acc.max_notional_per_position, max(risk_capped_notional, 0.0))
        if notional <= 0:
            raise ValueError("maliyetler zarar bütçesini tüketiyor")

        quantity = notional / entry
        direction = 1.0 if side == "LONG" else -1.0
        stop_loss = entry * (1.0 - direction * stop_distance_fraction)
        take_profit = None
        exit_cfg = self.config.exit
        if exit_cfg.tp1_r_multiple > 0:
            risk_per_unit = entry * stop_distance_fraction
            take_profit = entry * (
                1.0 + direction * exit_cfg.tp1_r_multiple * stop_distance_fraction
            ) if risk_per_unit > 0 else None
        liq = compute_liquidation_price(entry, side, acc.leverage, self.config.funding)
        net_risk = notional * per_unit_risk_rate + funding_buffer
        return TradePlan(
            side=side,
            entry=entry,
            quantity=quantity,
            margin=acc.margin_per_position,
            notional=notional,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=acc.leverage,
            estimated_entry_fee=notional * acc.maker_fee_rate,
            estimated_exit_cost=notional * (acc.taker_fee_rate + acc.stop_slippage_rate + acc.extra_slippage_rate),
            estimated_funding_buffer=funding_buffer,
            net_risk_at_stop=net_risk,
            liquidation_price=liq,
        )

    # ------------------------------------------------------------------
    # Portföy kontrolleri (Y1-G, Y2-7)
    # ------------------------------------------------------------------

    def check_portfolio(
        self,
        portfolio: Portfolio,
        symbol: str,
        side: str,
        planned_notional: float,
        planned_net_risk: float,
        prices: dict[str, float],
        daily_realized_pnl: float,
        daily_unrealized_pnl: float | None = None,
    ) -> RiskDecision:
        """Yeni giriş öncesi TÜM portföy kurallarını sırayla değerlendirir."""
        cfg = self.config.portfolio
        acc = self.config.account
        daily_pnl = daily_realized_pnl
        if daily_unrealized_pnl is not None:
            daily_pnl += daily_unrealized_pnl

        if self.kill_switch_state == KillSwitchState.HARD_HALT:
            return RiskDecision(False, "KILL_SWITCH_HARD_HALT")
        if daily_pnl <= -cfg.daily_hard_loss:
            return RiskDecision(False, "DAILY_HARD_LOSS_KILL_SWITCH")
        if self.kill_switch_state == KillSwitchState.SOFT_STOP:
            return RiskDecision(False, "KILL_SWITCH_SOFT_STOP")
        if daily_pnl <= -cfg.daily_soft_loss:
            return RiskDecision(False, "DAILY_SOFT_LOSS_LIMIT")

        if len(portfolio.positions) >= cfg.max_positions:
            return RiskDecision(False, "MAX_POSITIONS_REACHED")

        # Toplam açık risk tavanı
        if portfolio.total_open_net_risk() + planned_net_risk > cfg.total_open_risk_cap + 1e-9:
            return RiskDecision(False, "TOTAL_OPEN_RISK_CAP")

        # Brüt / yönsel nominal tavanları
        projected_gross = portfolio.total_notional(prices) + planned_notional
        if projected_gross > cfg.gross_notional_cap + 1e-9:
            return RiskDecision(False, "GROSS_NOTIONAL_CAP")
        side_sign = 1.0 if side == "LONG" else -1.0
        projected_directional = (
            portfolio.directional_notional(prices) + side_sign * planned_notional
        )
        if abs(projected_directional) > cfg.net_directional_notional_cap + 1e-9:
            return RiskDecision(False, "DIRECTIONAL_BALANCE_CAP")

        # Korelasyon grubu sınırları
        base = symbol.rsplit(":", 1)[-1].replace("USDT", "").upper()
        group = self.config.group_of(base)
        if group is not None:
            same_group = sum(
                1 for s in portfolio.positions
                if self.config.group_of(s.rsplit(":", 1)[-1].replace("USDT", "").upper()) == group
            )
            if same_group >= cfg.max_positions_per_group:
                return RiskDecision(False, f"CORRELATION_GROUP_CAP:{group}")
            group_notional = sum(
                p.quantity * prices.get(s, p.entry)
                for s, p in portfolio.positions.items()
                if self.config.group_of(s.rsplit(":", 1)[-1].replace("USDT", "").upper()) == group
            )
            if group_notional + planned_notional > cfg.max_group_notional + 1e-9:
                return RiskDecision(False, f"CORRELATION_GROUP_NOTIONAL:{group}")

        # Teminat yeterliliği
        required = acc.margin_per_position * (1.0 + acc.maker_fee_rate)
        if portfolio.free_balance() < required:
            return RiskDecision(False, "INSUFFICIENT_FUNDS")

        # Portföy drawdown koruması
        if portfolio.drawdown_pct(prices) >= cfg.portfolio_drawdown_pct:
            return RiskDecision(False, "PORTFOLIO_DRAWDOWN_PROTECTION")

        return RiskDecision(True, None)

    # ------------------------------------------------------------------
    # Kill switch (Y2-7)
    # ------------------------------------------------------------------

    def evaluate_kill_switch(
        self,
        portfolio: Portfolio,
        prices: dict[str, float],
        daily_realized_pnl: float,
    ) -> KillSwitchState:
        """Her tick'te çağrılır; SOFT_STOP / HARD_HALT geçişlerini yönetir."""
        cfg = self.config.portfolio
        daily_pnl = daily_realized_pnl + portfolio.unrealized_pnl(prices)
        if self.kill_switch_state == KillSwitchState.HARD_HALT:
            return self.kill_switch_state
        if daily_pnl <= -cfg.daily_hard_loss:
            self.kill_switch_state = KillSwitchState.HARD_HALT
        elif daily_pnl <= -cfg.daily_soft_loss:
            if self.kill_switch_state == KillSwitchState.NORMAL:
                self.kill_switch_state = KillSwitchState.SOFT_STOP
        # Not: SOFT_STOP -> NORMAL dönüşü UTC günü değişince dışarıdan resetlenir.
        return self.kill_switch_state

    def reset_daily(self, hard_too: bool = False) -> None:
        """UTC günü rollover'da soft stopu sıfırlar; hard halt isteğe bağlı."""
        if self.kill_switch_state == KillSwitchState.HARD_HALT and not (
            hard_too or self.config.portfolio.kill_switch_reset_on_new_day
        ):
            return
        self.kill_switch_state = KillSwitchState.NORMAL

    # ------------------------------------------------------------------
    # Funding ve likidasyon izleme (Y1-C)
    # ------------------------------------------------------------------

    def apply_funding_if_due(
        self,
        position,                                   # core.portfolio.Position
        mark_price: float,
        now_ms: int,
        funding_rate: float | None = None,
    ) -> float | None:
        """Funding zamanı geldiyse ödemeyi hesaplar, uygular ve döndürür."""
        f = self.config.funding
        if not f.enabled:
            return None
        from core.portfolio import next_funding_timestamp_ms
        interval_ms = int(f.interval_hours * 3_600_000)
        prev_boundary = (now_ms // interval_ms) * interval_ms
        if prev_boundary <= position.opened_at_ms:
            return None  # pozisyon bu funding döneminden önce açılmadı
        if position.funding_events and max(
            int(e) for e in position.funding_events  # type: ignore[arg-type]
        ) >= prev_boundary:
            return None  # bu dönem zaten ödendi
        rate = f.default_rate_per_8h if funding_rate is None else funding_rate
        notional = position.quantity * mark_price
        payment = compute_funding_payment(notional, rate, position.side)
        position.funding_paid += payment
        position.funding_events.append(float(prev_boundary))
        return payment

    def check_liquidation(self, position, mark_price: float) -> bool:
        """Mark fiyatı likidasyon seviyesini geçtiyse True döndürür."""
        if position.side == "LONG":
            return mark_price <= position.liquidation_price
        return mark_price >= position.liquidation_price

    def margin_warning(self, position, mark_price: float) -> bool:
        f = self.config.funding
        return position.margin_used_fraction(mark_price) >= f.margin_warning_fraction
