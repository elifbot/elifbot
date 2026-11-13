"""
strategies/base.py — Strateji sözleşmesi ve sinyal veri yapıları.

Tüm adaylar STATUS = "SHADOW" ile başlar. Hiçbir aday kendiliğinden
ACTIVE'e terfi ETMEZ; terfi yalnızca kullanıcının açık eylemiyle olur.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

LONG = "LONG"
SHORT = "SHORT"
HOLD = "HOLD"


@dataclass(frozen=True)
class Contributor:
    """Tek bir göstergenin oyu ve değeri."""

    name: str
    value: float | None
    vote: str  # LONG / SHORT / NEUTRAL / UNAVAILABLE
    family: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": None if self.value is None else round(float(self.value), 6),
            "vote": self.vote,
            "family": self.family,
        }


@dataclass
class SignalResult:
    """Bir stratejinin tek değerlendirme çıktısı."""

    signal: str
    strategy_name: str
    regime: str
    contributor_log: list[dict[str, Any]] = field(default_factory=list)
    active_families: list[str] = field(default_factory=list)
    missing_families: list[str] = field(default_factory=list)
    data_timestamp: int = 0
    status: str = "SHADOW"
    notes: list[str] = field(default_factory=list)

    def is_entry(self) -> bool:
        return self.signal in (LONG, SHORT)


class StrategyBase(abc.ABC):
    """
    Aday strateji arayüzü.

    Sözleşme:
      * Yalnızca KAPANMIŞ mumlar verilir; son satır (iloc[-1]) en son kapanmış mumdur.
      * Değerlendirme sırasında gelecekteki satırlara erişilmez.
      * Örnek durumu (self._state) her örnek için ayrıdır; sınıf seviyesinde
        değiştirilebilir nesne TUTULMAZ.
    """

    STATUS: str = "SHADOW"          # değiştirilebilir sınıf alanı değil; sabit
    NAME: str = "base"
    REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
    MIN_ROWS: int = 30

    def __init__(self) -> None:
        # Her örnek kendi durumunu oluşturur (paylaşılan mutable state yok).
        self._state: dict[str, Any] = {"evaluations": 0, "last_signal": HOLD}
        # Ablasyon: devre dışı bırakılan ailelerin koşulları GEREKLİ OLMAKTAN
        # çıkar (koşul "sağlanmış" sayılır). Aile ayrıştırma analizi için.
        self.disabled_families: set[str] = set()

    def family_enabled(self, family: str) -> bool:
        """Aile ablasyon anahtarı açık mı?"""
        return family not in self.disabled_families

    def _req(self, family: str, condition: bool) -> bool:
        """Koşul, ailesi devre dışıysa GEREKLİ DEĞİLDİR (ablasyon)."""
        return (not self.family_enabled(family)) or bool(condition)

    # -- yardımcılar -------------------------------------------------------
    def _check_frame(self, df: pd.DataFrame) -> str | None:
        """Veri yeterliliğini kontrol eder; sorun varsa açıklama döndürür."""
        if df is None or df.empty:
            return "bos_veri"
        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            return f"eksik_kolon:{','.join(missing)}"
        if len(df) < self.MIN_ROWS:
            return f"yetersiz_satir:{len(df)}<{self.MIN_ROWS}"
        if pd.isna(df.iloc[-1]["close"]):
            return "nan_kapanis"
        return None

    def _hold(self, reason: str, df: pd.DataFrame | None = None) -> SignalResult:
        ts = int(df.iloc[-1]["open_time"]) if df is not None and not df.empty else 0
        self._state["evaluations"] += 1
        self._state["last_signal"] = HOLD
        return SignalResult(
            signal=HOLD,
            strategy_name=self.NAME,
            regime=reason,
            contributor_log=[],
            active_families=[],
            missing_families=[],
            data_timestamp=ts,
            status=self.STATUS,
            notes=[reason],
        )

    @staticmethod
    def _last(df: pd.DataFrame, col: str) -> float | None:
        """Son KAPANMIŞ mumdaki değeri döndürür (lookahead yok)."""
        if col not in df.columns:
            return None
        v = df.iloc[-1][col]
        if pd.isna(v):
            return None
        return float(v)

    # -- arayüz ------------------------------------------------------------
    @abc.abstractmethod
    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        """Son kapanmış mum için sinyal üretir."""

    @property
    def evaluations(self) -> int:
        return int(self._state["evaluations"])
