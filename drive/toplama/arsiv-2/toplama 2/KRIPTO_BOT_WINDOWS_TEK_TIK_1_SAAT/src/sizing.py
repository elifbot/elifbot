"""Pozisyon boyutlandırma: Sabit 50 USDT marj, %10 kasa, ATR ve yarım-Kelly modelleri.

Kâr/zarar geçmişi kelly_stats.json dosyasında saklanır.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)


class KellyTracker:
    def __init__(
        self,
        path: str | Path = "kelly_stats.json",
        maxlen: int = 200,
        min_trades: int = 20,
    ):
        self.path = Path(path)
        self.min_trades = max(1, int(min_trades))
        self.history: deque[float] = deque(maxlen=int(maxlen))
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            history = data.get("history", []) if isinstance(data, dict) else []
            if not isinstance(history, list):
                raise ValueError("history bir liste olmalı")
            for value in history[-self.history.maxlen :]:
                number = float(value)
                if math.isfinite(number):
                    self.history.append(number)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log.warning(
                "Kelly istatistiği okunamadı (%s); güvenli varsayılan kullanılıyor",
                type(exc).__name__,
            )

    def _save(self):
        """Dosyanın yarım yazılmasını önleyerek atomik olarak kalıcılaştırır."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"history": list(self.history)}, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def record(self, pnl_pct: float):
        value = float(pnl_pct)
        if not math.isfinite(value):
            raise ValueError("Kelly PnL değeri sonlu bir sayı olmalı")
        self.history.append(value / 100)
        self._save()

    def stats(self) -> dict:
        n = len(self.history)
        if n == 0:
            return {"n": 0, "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
        wins = [x for x in self.history if x > 0]
        losses = [-x for x in self.history if x < 0]
        win_rate = len(wins) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        return {
            "n": n,
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 5),
            "avg_loss": round(avg_loss, 5),
        }

    def fraction(self) -> float | None:
        """Tam Kelly kesri (f*). Veri yetersizse None döner; negatif beklentide <= 0 döner."""
        if len(self.history) < self.min_trades:
            return None
        st = self.stats()
        w = st["win_rate"]
        avg_win = st["avg_win"]
        avg_loss = st["avg_loss"]
        if avg_win <= 0:
            return -1.0
        if avg_loss <= 0:
            return min(1.0, w)
        b = avg_win / avg_loss
        return w - (1.0 - w) / b


class PositionSizer:
    def __init__(
        self,
        base_risk_pct: float = 1.0,
        atr_mult: float = 1.5,
        kelly_on: bool = True,
        kelly_fraction: float = 0.5,
        kelly_min_risk: float = 0.25,
        kelly_max_risk: float = 2.0,
        kelly_min_trades: int = 20,
        stats_path: str | Path = "kelly_stats.json",
        min_notional_usdt: float = 5.0,
        mode: str = "atr_kelly",
        capital_pct: float = 10.0,
        leverage: int = 20,
        fixed_margin_usdt: float = 50.0,
    ):
        self.base_risk_pct = float(base_risk_pct)
        self.atr_mult = float(atr_mult)
        self.kelly_on = bool(kelly_on)
        self.kelly_fraction = float(kelly_fraction)
        self.kelly_min_risk = float(kelly_min_risk)
        self.kelly_max_risk = float(kelly_max_risk)
        self.min_notional_usdt = float(min_notional_usdt)
        self.kelly = KellyTracker(stats_path, min_trades=kelly_min_trades)
        self.mode = mode
        self.capital_pct = float(capital_pct)
        self.leverage = int(leverage)
        self.fixed_margin_usdt = float(fixed_margin_usdt)

    def risk_pct(self) -> tuple[float, dict]:
        """O anki risk/marj yüzdesi + açıklama. (risk_pct, bilgi)"""
        if self.mode == "sabit_usdt":
            return 0.0, {
                "kaynak": f"sabit_${self.fixed_margin_usdt:g}_{self.leverage}x",
                "margin_usdt": self.fixed_margin_usdt,
                "leverage": self.leverage,
            }
        if self.mode == "kasa_10_20x":
            return self.capital_pct, {
                "kaynak": f"kasa_%{self.capital_pct:g}_{self.leverage}x",
                "capital_pct": self.capital_pct,
                "leverage": self.leverage,
            }
        if not self.kelly_on:
            return self.base_risk_pct, {"kaynak": "sabit"}
        f = self.kelly.fraction()
        if f is None:
            return self.base_risk_pct, {
                "kaynak": "sabit (Kelly için veri yetersiz)",
                "islem_sayisi": self.kelly.stats()["n"],
            }
        if f <= 0:
            return 0.0, {
                "kaynak": "kelly (negatif beklenti: giriş yok)",
                "kelly_f": round(f, 3),
                **self.kelly.stats(),
            }
        kelly_pct = f * self.kelly_fraction * 100
        risk = max(self.kelly_min_risk, min(self.kelly_max_risk, kelly_pct))
        return risk, {
            "kaynak": "yarım-Kelly",
            "kelly_f": round(f, 3),
            **self.kelly.stats(),
        }

    def size(
        self,
        balance_usdt: float,
        entry: float,
        stop: float,
        atr: float | None = None,
        leverage_override: int | None = None,
    ) -> tuple[float, dict]:
        """Pozisyon miktarı + teşhis bilgisi. (miktar, bilgi)"""
        eff_lev = int(leverage_override if leverage_override is not None else self.leverage)
        if self.mode == "sabit_usdt":
            margin_usdt = self.fixed_margin_usdt
            if balance_usdt < margin_usdt or entry <= 0 or margin_usdt <= 0:
                return 0.0, {
                    "kaynak": "sabit_usdt",
                    "neden": f"bakiye sabit ${margin_usdt:g} marj için yetersiz",
                    "leverage": eff_lev,
                    "margin_usdt": margin_usdt,
                }
            notional_usdt = margin_usdt * eff_lev
            qty = notional_usdt / entry
            capital_pct = margin_usdt / balance_usdt * 100.0
            info = {
                "kaynak": f"sabit_${margin_usdt:g}_{eff_lev}x",
                "risk_pct": round(capital_pct, 3),
                "capital_pct": round(capital_pct, 3),
                "leverage": eff_lev,
                "margin_usdt": round(margin_usdt, 2),
                "notional": round(notional_usdt, 2),
            }
            if notional_usdt < self.min_notional_usdt:
                info["neden"] = f"min. tutar (${self.min_notional_usdt}) altı"
                return 0.0, info
            return qty, info
        if self.mode == "kasa_10_20x":
            if balance_usdt <= 0 or entry <= 0:
                return 0.0, {"kaynak": "kasa_10_20x", "neden": "bakiye/fiyat 0"}
            margin_usdt = balance_usdt * (self.capital_pct / 100.0)
            notional_usdt = margin_usdt * eff_lev
            qty = notional_usdt / entry
            info = {
                "kaynak": f"kasa_%{self.capital_pct:g}_{eff_lev}x",
                "risk_pct": round(self.capital_pct, 2),
                "capital_pct": round(self.capital_pct, 2),
                "leverage": eff_lev,
                "margin_usdt": round(margin_usdt, 2),
                "notional": round(notional_usdt, 2),
            }
            if notional_usdt < self.min_notional_usdt:
                info["neden"] = f"min. tutar (${self.min_notional_usdt}) altı"
                return 0.0, info
            return qty, info

        risk_pct, r_info = self.risk_pct()
        if balance_usdt <= 0 or entry <= 0 or risk_pct <= 0:
            return 0.0, {**r_info, "neden": r_info.get("kaynak", "risk sıfır")}
        stop_dist = abs(entry - stop)
        if atr is not None and atr > 0 and self.mode in ("atr", "atr_kelly"):
            stop_dist = max(stop_dist, float(atr) * self.atr_mult)
        if stop_dist <= 0:
            return 0.0, {**r_info, "neden": "stop mesafesi sıfır"}
        risk_usdt = balance_usdt * (risk_pct / 100.0)
        qty = risk_usdt / stop_dist
        notional_usdt = qty * entry
        margin_usdt = notional_usdt / max(1, eff_lev)
        info = {
            **r_info,
            "risk_pct": round(risk_pct, 3),
            "leverage": eff_lev,
            "margin_usdt": round(margin_usdt, 2),
            "notional": round(notional_usdt, 2),
        }
        if notional_usdt < self.min_notional_usdt:
            info["neden"] = f"min. tutar (${self.min_notional_usdt}) altı"
            return 0.0, info
        return qty, info
