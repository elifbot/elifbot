"""Yapılandırma — tek doğrulanmış kaynak, .env desteği, sert sınırlar.

İlke: config doğrulaması başarısızsa bot BAŞLAMAZ. Sessizce varsayılana
düşmek, yanlış eşikle gerçek veri üzerinde işlem üretmekten daha kötüdür.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..ai.council import CouncilConfig
from ..core.types import Mode
from ..execution.live_guard import assert_mode_allowed
from ..execution.paper import PaperConfig
from ..risk.manager import RiskConfig
from ..strategy.detector import DetectorConfig
from ..strategy.policy import PolicyConfig


class ConfigError(ValueError):
    """Yapılandırma geçersiz — başlatma durdurulmalı."""


def load_dotenv(path: Path | str = ".env") -> int:
    """Basit .env yükleyici (python-dotenv gerektirmez). Var olanı EZMEZ."""
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


@dataclass
class RunConfig:
    mode: Mode = Mode.PAPER
    duration_sec: float = 600.0
    drain_sec: float = 60.0
    warmup_sec: float = 45.0
    venues: list[str] = field(default_factory=lambda: ["binance_vision", "gateio"])
    symbols_per_venue: int = 25
    symbols_override: list[str] = field(default_factory=list)
    candle_interval: str = "1m"
    candle_refresh_sec: float = 30.0
    quote_refresh_sec: float = 3.0
    candle_limit: int = 120
    out_dir: str = "runs"
    run_id: str = ""
    log_level: str = "INFO"
    use_websocket: bool = True
    rest_tick_fallback: bool = True
    dashboard: bool = True
    #: Karar/kayıt yazımı için temiz DB. Eski DB DEVRALINMAZ.
    fresh_state: bool = True
    #: Koşu etiketi. "natural" = üretim eşikleri; "lifecycle-diagnostic" =
    #: yalnız yaşam döngüsü doğrulaması için gevşetilmiş eşikler.
    profile: str = "natural"
    #: Borsa başına saniyedeki REST istek bütçesi (429'u önler).
    rest_rps: float = 10.0
    #: Quote çevrimi başına sembol kotası; evren döngüsel taranır.
    quote_symbols_per_cycle: int = 40

    @property
    def filters_relaxed(self) -> bool:
        return self.profile != "natural"


@dataclass
class Config:
    run: RunConfig = field(default_factory=RunConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    council: CouncilConfig = field(default_factory=CouncilConfig)

    # ---------- kurulum ----------
    @classmethod
    def load(cls, path: Path | str | None = None,
             overrides: dict[str, Any] | None = None) -> "Config":
        load_dotenv()
        cfg = cls()
        if path:
            p = Path(path)
            if not p.exists():
                raise ConfigError(f"Config dosyası yok: {p}")
            data = json.loads(p.read_text(encoding="utf-8"))
            cfg._apply(data)
        if overrides:
            cfg._apply(overrides)
        cfg.validate()
        return cfg

    def _apply(self, data: dict[str, Any]) -> None:
        sections = {
            "run": (self.run, RunConfig), "detector": (self.detector, DetectorConfig),
            "policy": (self.policy, PolicyConfig), "risk": (self.risk, RiskConfig),
            "paper": (self.paper, PaperConfig), "council": (self.council, CouncilConfig),
        }
        for key, val in data.items():
            if key not in sections or not isinstance(val, dict):
                continue
            obj, _ = sections[key]
            for k, v in val.items():
                if not hasattr(obj, k):
                    raise ConfigError(f"Bilinmeyen ayar: {key}.{k}")
                if key == "run" and k == "mode":
                    v = Mode(str(v).upper())
                if key == "council" and k == "provider_ids":
                    v = tuple(v)
                setattr(obj, k, v)

    # ---------- doğrulama ----------
    def validate(self) -> None:
        r, d, p, rk = self.run, self.detector, self.policy, self.risk
        assert_mode_allowed(r.mode)
        if r.duration_sec <= 0:
            raise ConfigError("duration_sec pozitif olmalı")
        if r.drain_sec < 0 or r.warmup_sec < 0:
            raise ConfigError("drain/warmup negatif olamaz")
        if not r.venues:
            raise ConfigError("en az bir venue gerekli")
        if r.rest_rps <= 0:
            raise ConfigError("rest_rps pozitif olmalı")
        if r.quote_symbols_per_cycle <= 0:
            raise ConfigError("quote_symbols_per_cycle pozitif olmalı")
        if r.symbols_per_venue <= 0:
            raise ConfigError("symbols_per_venue pozitif olmalı")
        if not (0 < d.ret_min_pct < 50):
            raise ConfigError("ret_min_pct mantıksız")
        if d.rvol_min <= 0:
            raise ConfigError("rvol_min pozitif olmalı")
        if d.ret_window_ms < d.window_ms:
            raise ConfigError("ret_window_ms >= window_ms olmalı")
        if p.strategy not in ("fade", "momentum"):
            raise ConfigError("strategy fade|momentum olmalı")
        if p.max_spread_bps <= 0:
            raise ConfigError("max_spread_bps pozitif olmalı")
        if p.min_edge_ratio < 1.0:
            raise ConfigError("min_edge_ratio >= 1.0 olmalı (maliyet altı işlem yasak)")
        if not (0 < rk.risk_per_trade_pct <= 5):
            raise ConfigError("risk_per_trade_pct 0-5 arası olmalı")
        if rk.max_position_notional < rk.min_position_notional:
            raise ConfigError("max_position_notional >= min olmalı")
        if rk.atr_stop_mult <= 0 or rk.atr_tp_mult <= 0:
            raise ConfigError("ATR çarpanları pozitif olmalı")
        if rk.max_open_positions <= 0:
            raise ConfigError("max_open_positions pozitif olmalı")
        if self.council.min_consensus_score < 0 or self.council.min_consensus_score > 100:
            raise ConfigError("min_consensus_score 0-100 arası olmalı")

    # ---------- çıktı ----------
    def to_dict(self) -> dict[str, Any]:
        def ser(o: Any) -> Any:
            dd = asdict(o)
            return {k: (v.value if isinstance(v, Mode) else
                        list(v) if isinstance(v, tuple) else v)
                    for k, v in dd.items()}
        return {"run": ser(self.run), "detector": ser(self.detector),
                "policy": ser(self.policy), "risk": ser(self.risk),
                "paper": ser(self.paper), "council": ser(self.council)}

    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")