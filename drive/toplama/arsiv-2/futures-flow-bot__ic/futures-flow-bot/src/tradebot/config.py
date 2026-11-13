"""Ayarlar. Bilinmeyen anahtar hata verir (yazim hatasi sessizce yutulmasin diye)."""
from __future__ import annotations

import dataclasses
import os
import typing
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RiskCfg:
    margin_per_trade_usd: float = 50.0
    leverage: int = 10
    margin_mode: str = "isolated"
    stop_loss_usd: float = 25.0
    free_margin_reserve_pct: float = 5.0
    symbol_cooldown_sec: float = 300.0
    max_open_positions: int | None = None
    daily_loss_limit_usd: float | None = None
    max_same_direction_positions: int | None = None


@dataclass
class ExchangeCfg:
    enabled: bool = True
    paper_balance_usd: float = 500.0
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    min_24h_volume_usd: float = 10_000_000.0
    max_symbols: int = 400


@dataclass
class ScannerCfg:
    flow_window_sec: int = 10
    volume_window_sec: int = 60
    baseline_minutes: int = 30
    min_baseline_minutes: int = 5
    baseline_floor_usd: float = 1000.0
    indicator_candle_seconds: int = 60
    min_flow_usd: float = 3000.0
    max_idle_sec: float = 20.0
    eval_interval_sec: float = 1.0


@dataclass
class EntryCfg:
    threshold: int = 4
    delta_min: float = 0.35
    vol_ratio_min: float = 3.0
    change_min_pct: float = 0.10
    rsi_long_min: float = 50.0
    rsi_long_max: float = 78.0
    rsi_short_min: float = 22.0
    rsi_short_max: float = 50.0


@dataclass
class EntryOrderCfg:
    mode: str = "maker"
    timeout_sec: float = 5.0


@dataclass
class ExitCfg:
    score_threshold: int = 3
    min_net_profit_usd: float = 0.5
    exit_when_losing_on_reversal: bool = True
    delta_flip: float = 0.0
    vol_ratio_fade: float = 1.0
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    adverse_change_pct: float = 0.10
    breakeven_activation_usd: float = 5.0
    breakeven_buffer_pct: float = 0.10
    trail_activation_usd: float = 6.0
    trail_giveback_pct: float = 40.0
    time_stop_minutes: float = 30.0


@dataclass
class PaperCfg:
    slippage_pct: float = 0.03
    stop_slippage_pct: float = 0.05


@dataclass
class SafetyCfg:
    halt_on_stale_data_sec: float = 10.0
    resume_after_fresh_sec: float = 15.0
    max_consecutive_api_errors: int = 5
    api_error_pause_sec: float = 60.0


@dataclass
class AlertCfg:
    notify_trades: bool = False
    summary_interval_min: int = 60


@dataclass
class StorageCfg:
    path: str = "data/tradebot.db"


@dataclass
class Config:
    mode: str = "paper"
    risk: RiskCfg = field(default_factory=RiskCfg)
    scanner: ScannerCfg = field(default_factory=ScannerCfg)
    entry: EntryCfg = field(default_factory=EntryCfg)
    entry_order: EntryOrderCfg = field(default_factory=EntryOrderCfg)
    exit: ExitCfg = field(default_factory=ExitCfg)
    paper: PaperCfg = field(default_factory=PaperCfg)
    safety: SafetyCfg = field(default_factory=SafetyCfg)
    alerts: AlertCfg = field(default_factory=AlertCfg)
    storage: StorageCfg = field(default_factory=StorageCfg)
    exchanges: dict = field(default_factory=lambda: {"binance": ExchangeCfg(), "okx": ExchangeCfg()})

    @property
    def stop_distance(self) -> float:
        """Girise gore stop mesafesi (kesir). 25$ / 500$ = 0.05"""
        return self.risk.stop_loss_usd / (self.risk.margin_per_trade_usd * self.risk.leverage)


def _build(cls, data):
    data = data or {}
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ValueError(f"Bilinmeyen ayar ({cls.__name__}): {sorted(unknown)}")
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        value, typ = data[f.name], hints[f.name]
        if dataclasses.is_dataclass(typ):
            value = _build(typ, value)
        kwargs[f.name] = value
    return cls(**kwargs)


def validate(cfg: Config) -> None:
    if cfg.mode not in {"paper", "testnet", "live"}:
        raise ValueError("mode paper | testnet | live olmali")
    r = cfg.risk
    if r.margin_per_trade_usd <= 0 or r.leverage < 1 or r.stop_loss_usd <= 0:
        raise ValueError("marjin, kaldirac ve stop pozitif olmali")
    if r.margin_mode != "isolated":
        raise ValueError("Bu surum sadece isolated marjin destekler")
    # Tasfiye fiyati ~ 1/kaldirac civarindadir; stop tasfiyeden yeterince once olmali.
    if cfg.stop_distance >= 0.9 / r.leverage:
        raise ValueError(
            f"Stop mesafesi (%{cfg.stop_distance*100:.1f}) tasfiyeye cok yakin/uzak: "
            f"{r.leverage}x kaldiracta stop %{90/r.leverage:.1f}'den kucuk olmali"
        )
    if cfg.entry_order.mode not in {"maker", "taker"}:
        raise ValueError("entry_order.mode maker | taker olmali")
    if not any(e.enabled for e in cfg.exchanges.values()):
        raise ValueError("En az bir borsa acik olmali")
    for name in cfg.exchanges:
        if name not in {"binance", "okx"}:
            raise ValueError(f"Desteklenmeyen borsa: {name}")


def assert_live_allowed(cfg: Config) -> None:
    if cfg.mode == "live" and os.getenv("LIVE_TRADING_CONFIRM") != "I_UNDERSTAND_THE_RISK":
        raise RuntimeError(
            "mode: live icin ortam degiskeni LIVE_TRADING_CONFIRM=I_UNDERSTAND_THE_RISK gerekir. "
            "Once testnet/demo ile uzun sure test edin."
        )


def load_config(path: str | Path | None = None) -> Config:
    data = {}
    if path:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    exchanges = data.pop("exchanges", None)
    cfg = _build(Config, data)
    if exchanges is not None:
        cfg.exchanges = {k: _build(ExchangeCfg, v) for k, v in exchanges.items()}
    validate(cfg)
    return cfg


def load_dotenv(path: str = ".env") -> None:
    """Basit .env okuyucu (ek bagimlilik yok). Var olan ortam degiskenlerini ezmez."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
