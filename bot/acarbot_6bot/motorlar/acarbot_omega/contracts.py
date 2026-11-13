# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — Kesin Decimal Kontrat Matematiği, Maliyet Modeli ve -$20 Stop Çözücü (contracts.py)
===================================================================================================
Birleştirilen Miras:
  - ACARBOT-V10 (contract_math.py): Decimal hassasiyetli Linear & Inverse kontrat ve lot/tick adımı
  - PHOENIX V4 (risk.py): Komisyon + çıkış ücreti + kayma rezervli kesin net -$20 stop çözücü
  - ACARBOT V6.2 (costs.py): Varsayılan açık tam sürtünme maliyeti (komisyon + spread + kayma + fonlama)
  - APEX v1.1 (derivatives_risk.py): Stop-likidasyon güvenlik tamponu doğrulaması
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from math import isfinite
from typing import Literal, Optional

from .config import OmegaConfig

DELIVERY_SUFFIX_RE = re.compile(r"(?:_|-)(\d{6})$")


def to_dec(val: float | str | Decimal) -> Decimal:
    dec = val if isinstance(val, Decimal) else Decimal(str(val))
    if not dec.is_finite():
        raise ValueError(f"Geçersiz Decimal değer: {val}")
    return dec


def normalize_exchange_and_symbol(exchange: str, symbol: str) -> tuple[str, str]:
    """
    Yanlış aynalanmış (CNAME) akışları doğrular:
    - 'binance_coinm' akışından USDT/USDC paritesi gelirse otomatik 'binance' (USDⓈ-M) olarak düzeltir!
    - Böylece hacim çarpanı ve kontrat tipi %100 saf kalır.
    """
    ex = exchange.strip().lower()
    sym = symbol.strip().upper()
    if ex == "binance_coinm" and not ("USD_" in sym and not sym.startswith("USDT")):
        if sym.endswith("USDT") or sym.endswith("USDC") or "USDT_" in sym or "USDC_" in sym:
            ex = "binance"
    elif ex == "binance" and ("USD_PERP" in sym or re.search(r"USD_\d{6}$", sym)):
        if "USDT" not in sym and "USDC" not in sym:
            ex = "binance_coinm"
    return ex, sym


def extract_base_asset(symbol: str) -> str:
    """Farklı borsalardaki aynı baz coini bulur (örn. BTCUSDT, BTC-USDT-SWAP, BTCUSD_261225 -> BTC)."""
    s = symbol.strip().upper()
    if "-" in s:
        return s.split("-", 1)[0]
    s = re.sub(r"_\d{6}$", "", s)
    s = re.sub(r"_PERP$", "", s)
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)]
    return s


@dataclass(frozen=True)
class ContractSpec:
    exchange: str
    symbol: str
    segment: Literal["BINANCE_USDM", "BINANCE_COINM", "OKX_SWAP", "OKX_FUTURES"]
    kind: Literal["linear", "inverse"]
    settlement: str
    base_asset: str
    contract_face_usd: Decimal  # Inverse kontratlarda 1 kontratın USD değeri (BTC=100$, diğer=10$)
    lot_step: Decimal
    min_qty: Decimal
    tick_size: Decimal
    is_delivery: bool = False
    delivery_code: Optional[str] = None

    def quantize_price(self, price: float) -> float:
        p = to_dec(max(1e-10, price))
        q = (p / self.tick_size).to_integral_value(rounding=ROUND_HALF_UP) * self.tick_size
        return float(max(self.tick_size, q))

    def compute_order_quantity(self, notional_usd: float, entry_price: float) -> tuple[float, float]:
        """
        Hedef USD büyüklük ($500) için kesin kontrat / coin miktarını ve gerçek USD büyüklüğü döndürür.
        - Linear kontrat: qty = notional_usd / entry_price (coin adedi)
        - Inverse kontrat (COIN-M / OKX USD-SWAP): qty = kontrat adedi (örn. 5 kontrat × $100 = $500)
        """
        if entry_price <= 0 or notional_usd <= 0:
            raise ValueError("Fiyat ve büyüklük pozitif olmalıdır.")
        n_dec = to_dec(notional_usd)
        px_dec = to_dec(entry_price)

        if self.kind == "inverse":
            raw_contracts = n_dec / self.contract_face_usd
            q_contracts = (raw_contracts / self.lot_step).to_integral_value(rounding=ROUND_HALF_UP) * self.lot_step
            if q_contracts < self.min_qty:
                q_contracts = self.min_qty
            effective_notional = float(q_contracts * self.contract_face_usd)
            return float(q_contracts), effective_notional

        raw_coins = n_dec / px_dec
        q_coins = (raw_coins / self.lot_step).to_integral_value(rounding=ROUND_DOWN) * self.lot_step
        if q_coins < self.min_qty:
            q_coins = self.min_qty
        effective_notional = float(q_coins * px_dec)
        return float(q_coins), effective_notional

    def gross_pnl_usd(self, side: int, entry_price: float, exit_price: float, notional_usd: float) -> float:
        """
        Hem Linear hem Inverse kontratlar için kesin brüt USD PnL hesabı:
        - Linear:  side * (exit / entry - 1) * notional_usd
        - Inverse: side * (1 - entry / exit) * notional_usd  (1/entry - 1/exit kesin ters kontrat formülü!)
        """
        if entry_price <= 0 or exit_price <= 0:
            return 0.0
        if self.kind == "inverse":
            return float(side) * (1.0 - (entry_price / exit_price)) * notional_usd
        return float(side) * ((exit_price / entry_price) - 1.0) * notional_usd


def infer_tick_size(price: float) -> Decimal:
    if price >= 10000:
        return Decimal("0.1")
    if price >= 100:
        return Decimal("0.01")
    if price >= 1:
        return Decimal("0.0001")
    if price >= 0.01:
        return Decimal("0.00001")
    return Decimal("0.0000001")


def parse_contract_spec(exchange: str, symbol: str, ref_price: float = 100.0) -> ContractSpec:
    ex, sym = normalize_exchange_and_symbol(exchange, symbol)
    base = extract_base_asset(sym)
    tick = infer_tick_size(ref_price)
    m_deliv = DELIVERY_SUFFIX_RE.search(sym)
    deliv_code = m_deliv.group(1) if m_deliv else None

    if ex == "okx":
        is_swap = sym.endswith("-SWAP")
        seg: Literal["OKX_SWAP", "OKX_FUTURES"] = "OKX_SWAP" if is_swap else "OKX_FUTURES"
        parts = sym.split("-")
        quote = parts[1] if len(parts) >= 2 else "USDT"
        is_inverse = quote == "USD"
        face = Decimal("100") if (is_inverse and base == "BTC") else Decimal("10")
        return ContractSpec(
            exchange="okx",
            symbol=sym,
            segment=seg,
            kind="inverse" if is_inverse else "linear",
            settlement=base if is_inverse else quote,
            base_asset=base,
            contract_face_usd=face,
            lot_step=Decimal("1") if is_inverse else Decimal("0.0001"),
            min_qty=Decimal("1") if is_inverse else Decimal("0.0001"),
            tick_size=tick,
            is_delivery=not is_swap,
            delivery_code=deliv_code,
        )

    if ex == "binance_coinm":
        face = Decimal("100") if base == "BTC" else Decimal("10")
        return ContractSpec(
            exchange="binance_coinm",
            symbol=sym,
            segment="BINANCE_COINM",
            kind="inverse",
            settlement=base,
            base_asset=base,
            contract_face_usd=face,
            lot_step=Decimal("1"),
            min_qty=Decimal("1"),
            tick_size=tick,
            is_delivery=not sym.endswith("_PERP"),
            delivery_code=deliv_code,
        )

    settlement = "USDC" if "USDC" in sym else "USDT"
    return ContractSpec(
        exchange="binance",
        symbol=sym,
        segment="BINANCE_USDM",
        kind="linear",
        settlement=settlement,
        base_asset=base,
        contract_face_usd=Decimal("1"),
        lot_step=Decimal("0.0001"),
        min_qty=Decimal("0.0001"),
        tick_size=tick,
        is_delivery=deliv_code is not None,
        delivery_code=deliv_code,
    )


@dataclass(frozen=True)
class CostBreakdown:
    entry_fee_usd: float
    exit_fee_usd: float
    spread_usd: float
    entry_slippage_usd: float
    exit_slippage_usd: float
    funding_reserve_usd: float

    @property
    def fee_only_usd(self) -> float:
        return self.entry_fee_usd + self.exit_fee_usd

    @property
    def total_friction_usd(self) -> float:
        return (
            self.entry_fee_usd
            + self.exit_fee_usd
            + self.spread_usd
            + self.entry_slippage_usd
            + self.exit_slippage_usd
            + self.funding_reserve_usd
        )


class CostModel:
    """Varsayılan açık gerçek işlem sürtünme modeli (ACARBOT v6.2 + PHOENIX V4 birleşimi)."""

    def __init__(self, cfg: OmegaConfig) -> None:
        self.cfg = cfg

    def estimate(
        self,
        notional_usd: float,
        spread_bps: Optional[float] = None,
        funding_rate: float = 0.0,
        side: int = 1,
        maker_entry: bool = False,
    ) -> CostBreakdown:
        in_bps = self.cfg.maker_fee_bps if maker_entry else self.cfg.taker_fee_bps
        out_bps = self.cfg.taker_fee_bps
        sp_bps = spread_bps if (spread_bps is not None and spread_bps >= 0) else self.cfg.default_spread_bps
        in_slip_bps = 0.0 if maker_entry else self.cfg.entry_slippage_bps
        out_slip_bps = self.cfg.exit_slippage_bps

        # Pozisyon yönü fonlama ödüyorsa ihtiyatlı rezerv ayır (örn. LONG iken pozitif funding)
        adverse_funding = max(0.0, float(side) * funding_rate)
        funding_usd = notional_usd * adverse_funding * 0.5  # Yarım fonlama dönemi ihtiyat payı

        return CostBreakdown(
            entry_fee_usd=round(notional_usd * (in_bps / 10_000.0), 4),
            exit_fee_usd=round(notional_usd * (out_bps / 10_000.0), 4),
            spread_usd=round(notional_usd * (sp_bps * 0.5 / 10_000.0), 4),
            entry_slippage_usd=round(notional_usd * (in_slip_bps / 10_000.0), 4),
            exit_slippage_usd=round(notional_usd * (out_slip_bps / 10_000.0), 4),
            funding_reserve_usd=round(funding_usd, 4),
        )

    def solve_exact_net_stop_price(
        self,
        spec: ContractSpec,
        entry_price: float,
        side: int,
        notional_usd: float,
        costs: Optional[CostBreakdown] = None,
    ) -> float:
        """
        Giriş komisyonu + çıkış komisyonu + çıkış kayma rezervi düşüldükten sonra
        gerçekleşen NET zararın -$20.00'ı ASLA aşmamasını sağlayan kesin stop fiyatını çözer!
        """
        c = costs or self.estimate(notional_usd=notional_usd, side=side)
        # Fiyat hareketine kalan maksimum brüt zarar bütçesi:
        price_loss_budget = max(
            1.0,
            self.cfg.hard_stop_loss_usd - c.entry_fee_usd - c.exit_fee_usd - c.exit_slippage_usd,
        )
        loss_frac = price_loss_budget / max(notional_usd, 1e-9)

        if spec.kind == "inverse":
            # Inverse brüt zarar: side * (1 - entry / stop) * notional = -price_loss_budget
            # LONG (+1): 1 - entry/stop = -loss_frac -> stop = entry / (1 + loss_frac)
            # SHORT (-1): -(1 - entry/stop) = -loss_frac -> entry/stop = 1 + loss_frac? Hayır:
            # SHORT brüt PnL = -1 * (1 - entry/stop) = (entry/stop - 1) = -loss_frac -> entry/stop = 1 - loss_frac -> stop = entry / (1 - loss_frac)
            denom = (1.0 + loss_frac) if side > 0 else max(0.05, 1.0 - loss_frac)
            raw_stop = entry_price / denom
        else:
            raw_stop = entry_price * (1.0 - float(side) * loss_frac)

        return spec.quantize_price(max(1e-10, raw_stop))

    def verify_stop_before_liquidation(
        self,
        entry_price: float,
        stop_price: float,
        side: int,
        maintenance_margin_rate: float = 0.005,
    ) -> tuple[bool, float]:
        """10x kaldıraçta -$20 SL (~%3.80) ile tahmini likidasyon (~%9.50) arasında güvenli tamponu doğrular."""
        if not all(isfinite(v) for v in (entry_price, stop_price)) or entry_price <= 0:
            return False, 0.0
        lev = float(self.cfg.leverage)
        if side > 0:
            est_liq = entry_price * (1.0 - (1.0 / lev) + maintenance_margin_rate)
            buffer_pct = ((stop_price - est_liq) / entry_price) * 100.0
            return buffer_pct >= self.cfg.liquidation_safety_buffer_pct, est_liq
        est_liq = entry_price * (1.0 + (1.0 / lev) - maintenance_margin_rate)
        buffer_pct = ((est_liq - stop_price) / entry_price) * 100.0
        return buffer_pct >= self.cfg.liquidation_safety_buffer_pct, est_liq
