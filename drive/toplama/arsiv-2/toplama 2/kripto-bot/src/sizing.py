"""Dinamik pozisyon boyutlandırma: %10 Kasa × Dinamik Kaldıraç (20x/10x/5x) + ATR + Kelly.

Modlar:
  • kasa_10_20x (VARSAYILAN): Her işlemde kasanın %10'u marj (teminat) olarak
    ayrılır ve aktif kaldıraçla (normalde 20x, yüksek oynaklıkta 10x, aşırı
    oynaklık/veto yaklaşımında 5x) pozisyon açılır:
      marj_usdt = kasa × %10
      notional_usdt = marj_usdt × aktif_kaldıraç
      miktar = notional_usdt / giriş_fiyatı
  • atr_kelly / atr / kelly / sabit:
      1) ATR SIZING: miktar = risk_tutarı / max(stop_mesafesi, ATR × katsayı)
      2) KELLY CRITERION: yarım-Kelly ile dinamik risk yüzdesi (%0.25..%2.0)

Kâr/zarar geçmişi kelly_stats.json dosyasında saklanır.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path


class KellyTracker:
    def __init__(
        self,
        path: str | Path = "kelly_stats.json",
        min_trades: int = 20,
        max_history: int = 200,
    ):
        self.path = Path(path)
        self.min_trades = min_trades
        self.history: deque[float] = deque(maxlen=max_history)
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for v in data.get("history", [])[-self.history.maxlen :]:
                    self.history.append(float(v))
        except Exception:
            pass

    def _save(self):
        try:
            self.path.write_text(
                json.dumps({"history": list(self.history)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def record(self, pnl_pct: float):
        try:
            self.history.append(float(pnl_pct) / 100)
        except Exception:
            return
        self._save()

    def stats(self) -> dict:
        h = list(self.history)
        n = len(h)
        if n == 0:
            return {"n": 0, "winrate": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
        wins = [x for x in h if x >= 0]
        losses = [x for x in h if x < 0]
        return {
            "n": n,
            "winrate": len(wins) / n,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": abs(sum(losses) / len(losses)) if losses else 0.0,
        }

    def kelly_fraction(self) -> float | None:
        """Tam Kelly f değeri (0..1). Veri yetersizse None."""
        s = self.stats()
        if s["n"] < self.min_trades or s["avg_loss"] <= 0:
            return None
        p, b = s["winrate"], s["avg_win"] / s["avg_loss"]
        if b <= 0:
            return None
        f = (p * b - (1 - p)) / b
        return max(0.0, min(1.0, f))


class PositionSizer:
    def __init__(
        self,
        base_risk_pct: float = 1.0,
        atr_mult: float = 1.5,
        min_notional_usdt: float = 10.0,
        kelly_on: bool = True,
        kelly_fraction: float = 0.5,
        kelly_min_risk: float = 0.25,
        kelly_max_risk: float = 2.0,
        kelly_min_trades: int = 20,
        stats_path: str | Path = "kelly_stats.json",
        mode: str = "atr_kelly",
        capital_pct: float = 10.0,
        leverage: int = 20,
    ):
        self.base_risk_pct = base_risk_pct
        self.atr_mult = atr_mult
        self.min_notional_usdt = min_notional_usdt
        self.kelly_on = kelly_on
        self.kelly_fraction = kelly_fraction
        self.kelly_min_risk = kelly_min_risk
        self.kelly_max_risk = kelly_max_risk
        self.kelly = KellyTracker(stats_path, kelly_min_trades)
        self.mode = mode
        self.capital_pct = capital_pct
        self.leverage = int(leverage)

    def risk_pct(self) -> tuple[float, dict]:
        """O anki risk/marj yüzdesi + açıklama. (risk_pct, bilgi)"""
        if self.mode == "kasa_10_20x":
            return self.capital_pct, {
                "kaynak": f"kasa_%{self.capital_pct:g}_{self.leverage}x",
                "leverage": self.leverage,
                "capital_pct": self.capital_pct,
                **self.kelly.stats(),
            }
        if not self.kelly_on:
            return self.base_risk_pct, {"kaynak": "sabit"}
        f = self.kelly.kelly_fraction()
        if f is None:
            return self.base_risk_pct, {
                "kaynak": "sabit (Kelly için veri yetersiz)",
                "islem_sayisi": self.kelly.stats()["n"],
            }
        kelly_pct = f * self.kelly_fraction * 100
        risk = max(self.kelly_min_risk, min(self.kelly_max_risk, kelly_pct))
        return risk, {
            "kaynak": "kelly",
            "kelly_f": round(f, 3),
            "ham_kelly_pct": round(kelly_pct, 2),
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
        if self.mode == "kasa_10_20x":
            if balance_usdt <= 0 or entry <= 0:
                return 0.0, {"kaynak": "kasa_10_20x", "neden": "bakiye/fiyat 0"}
            margin_usdt = balance_usdt * (self.capital_pct / 100.0)
            notional_usdt = margin_usdt * eff_lev
            qty = notional_usdt / entry
            info = {
                "kaynak": f"kasa_%{self.capital_pct:g}_{eff_lev}x",
                "risk_pct": self.capital_pct,
                "capital_pct": self.capital_pct,
                "leverage": eff_lev,
                "margin_usdt": round(margin_usdt, 2),
                "notional": round(notional_usdt, 2),
            }
            if notional_usdt < self.min_notional_usdt:
                info["neden"] = f"min. tutar (${self.min_notional_usdt}) altı"
                return 0.0, info
            return qty, info

        info = {}
        risk_pct, kinfo = self.risk_pct()
        info.update(kinfo)
        info["risk_pct"] = round(risk_pct, 3)
        risk_usdt = balance_usdt * risk_pct / 100

        stop_dist = abs(entry - stop)
        eff_dist = stop_dist
        if atr and atr > 0:
            atr_dist = atr * self.atr_mult
            eff_dist = max(stop_dist, atr_dist)
            info["atr"] = round(atr, 6)
            info["atr_kisit"] = atr_dist > stop_dist
        info["risk_mesafesi"] = round(eff_dist, 6)

        if eff_dist <= 0 or entry <= 0 or balance_usdt <= 0:
            return 0.0, info
        qty = risk_usdt / eff_dist
        info["notional"] = round(qty * entry, 2)
        info["leverage"] = eff_lev
        info["margin_usdt"] = round((qty * entry) / max(1, eff_lev), 2)
        if qty * entry < self.min_notional_usdt:
            info["neden"] = f"min. tutar (${self.min_notional_usdt}) altı"
            return 0.0, info
        return qty, info
