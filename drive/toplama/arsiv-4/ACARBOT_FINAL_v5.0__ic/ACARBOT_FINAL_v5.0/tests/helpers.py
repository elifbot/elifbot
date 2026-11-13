"""Paylaşılan test yardımcıları: sentetik mum ve tick üretimi."""

from __future__ import annotations

from infra.market_data.models import Candle

START_MS = 1_700_000_000_000
INTERVAL_MS = 300_000  # 5 dakika


def make_candles(
    closes: list[float],
    start_ms: int = START_MS,
    interval_ms: int = INTERVAL_MS,
    volumes: list[float] | None = None,
    wick_fraction: float = 0.001,
) -> list[Candle]:
    """Kapanış listesinden mum üretir; yüksek/düşük hafif fitillidir."""
    candles: list[Candle] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        open_price = previous
        spread = max(abs(close - open_price), open_price * wick_fraction)
        high = max(open_price, close) + spread * 0.15
        low = min(open_price, close) - spread * 0.15
        volume = volumes[index] if volumes else 10.0
        candles.append(Candle(
            timestamp=start_ms + index * interval_ms,
            open=open_price, high=high, low=low, close=close,
            volume=volume,
        ))
        previous = close
    return candles


def flat_series(
    price: float = 100.0,
    count: int = 80,
    volume: float = 10.0,
) -> list[float]:
    return [price] * count


def dip_series(
    price: float = 100.0,
    count: int = 80,
    dip_pct: float = 1.5,
    volume: float = 10.0,
    spike_volume: float = 25.0,
) -> tuple[list[float], list[float]]:
    """Sonda `dip_pct` düşüş olan kapanış/hacim listesi (FADE-LONG senaryosu)."""
    closes = [price] * count
    volumes = [volume] * count
    closes[-2] = price * (1 - dip_pct / 100.0)
    closes[-1] = price * (1 - dip_pct / 100.0 - 0.001)
    volumes[-1] = spike_volume
    return closes, volumes


def pump_series(
    price: float = 100.0,
    count: int = 80,
    pump_pct: float = 1.5,
    volume: float = 10.0,
    spike_volume: float = 25.0,
) -> tuple[list[float], list[float]]:
    """Sonda `pump_pct` yükseliş olan kapanış/hacim listesi (FADE-SHORT)."""
    closes = [price] * count
    volumes = [volume] * count
    closes[-2] = price * (1 + pump_pct / 100.0)
    closes[-1] = price * (1 + pump_pct / 100.0 + 0.001)
    volumes[-1] = spike_volume
    return closes, volumes


# ---------------------------------------------------------------------------
# v5.0 — test yapılandırmaları
# ---------------------------------------------------------------------------
def apex_config(base=None):
    """APEX profili: portföy tavanları KAPALI, doğal sınır serbest teminat.

    v5.0'da işlem başı hedef net risk 25 USDT ve nominal tavan kapalı olduğu
    için notional 900-5.400 USDT aralığına çıkar. Legacy portföy tavanları
    (gross 3.000 / directional 1.000) bu akışı reddeder; akış testleri APEX
    yapılandırması kullanır. Korunanlar: teminat yeterliliği, 25 USDT net
    risk, drawdown koruması, likidasyon modeli.
    """
    from dataclasses import replace as _r
    from core.config import SuperConfig
    cfg = base or SuperConfig()
    cfg.portfolio = _r(
        cfg.portfolio,
        max_positions=0, max_positions_per_group=0, max_group_notional=0.0,
        gross_notional_cap=0.0, net_directional_notional_cap=0.0,
        total_open_risk_cap=0.0, daily_soft_loss=0.0, daily_hard_loss=0.0,
    )
    return cfg


def legacy_capped_config(base=None):
    """v4.0 ve öncesi: sabit 50 USDT teminat + 500 USDT nominal tavan.

    Dar stoplarda net risk ~2-3 USDT'ye kırılırdı. Bu davranışı test eden
    senaryolar (klasik stopun acil stoptan ÖNCE tetiklenmesi gibi) için
    korunur.
    """
    from dataclasses import replace as _r
    from core.config import SuperConfig
    cfg = base or SuperConfig()
    cfg.account = _r(
        cfg.account, margin_per_position=50.0, max_notional_per_position=500.0,
    )
    return cfg
