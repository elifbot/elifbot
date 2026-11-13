"""
strategies/composite.py — Aile bazlı birleşik skorlama.

UYARI (metodolojik): Aynı fiyat serisinden türetilen göstergeler BAĞIMSIZ
kanıt DEĞİLDİR. Örneğin EMA şeridi, MACD ve Supertrend aynı kapanış
serisinin dönüşümleridir; üçünün aynı yönde olması olasılığı, bağımsız üç
kanıtın aynı yönde olmasından çok daha yüksektir. Bu modül bu nedenle her
AİLEYİ tek bir oy kaynağı sayar ve aile başına katkıyı sınırlar (cap).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from strategies.base import HOLD, LONG, SHORT, SignalResult

FAMILY_WEIGHTS: dict[str, float] = {
    "A": 1.0,   # trend
    "B": 1.0,   # momentum
    "C": 1.0,   # volatilite
    "D": 1.0,   # hacim
    "E": 0.5,   # piyasa yapısı (henüz yalnızca SHADOW)
    "F": 0.0,   # vadeli mikroyapı — veri yok, katkı yok
    "G": 0.5,   # bağlam
}
FAMILY_CAP = 1.0  # bir ailenin toplam katkısı bu değeri aşamaz


@dataclass
class FamilyScore:
    """Aile bazlı oy toplamı."""

    family: str
    long_votes: float = 0.0
    short_votes: float = 0.0
    neutral_votes: float = 0.0

    @property
    def net(self) -> float:
        raw = (self.long_votes - self.short_votes) * FAMILY_WEIGHTS.get(self.family, 0.0)
        return max(-FAMILY_CAP, min(FAMILY_CAP, raw))


@dataclass
class CompositeResult:
    signal: str
    long_score: float
    short_score: float
    family_scores: dict[str, float] = field(default_factory=dict)
    agreeing_strategies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def score_families(results: list[SignalResult]) -> dict[str, FamilyScore]:
    """Sonuçlardaki contributor_log'dan aile oylarını toplar."""
    scores: dict[str, FamilyScore] = {}
    for res in results:
        for entry in res.contributor_log:
            fam = str(entry.get("family") or "?")
            fs = scores.setdefault(fam, FamilyScore(family=fam))
            vote = entry.get("vote")
            if vote == LONG:
                fs.long_votes += 1.0
            elif vote == SHORT:
                fs.short_votes += 1.0
            else:
                fs.neutral_votes += 1.0
    return scores


def composite_signal(
    results: list[SignalResult], *, threshold: float = 0.5
) -> CompositeResult:
    """
    Aday stratejilerin sinyallerini ve aile oylarını birleştirir.

    Not: yalnızca SHADOW adayların çıktısıdır; canlı işlem kararı DEĞİLDİR.
    """
    warnings: list[str] = [
        "Aynı fiyat serisinden türeyen aileler bağımsız kanıt değildir.",
        "F ailesi (funding/OI/mark/CVD) verisi YOK; katkısı sıfırdır.",
    ]

    entries = [r for r in results if r.is_entry()]
    longs = [r.strategy_name for r in entries if r.signal == LONG]
    shorts = [r.strategy_name for r in entries if r.signal == SHORT]

    fams = score_families(results)
    long_score = sum(max(0.0, f.net) for f in fams.values())
    short_score = sum(max(0.0, -f.net) for f in fams.values())

    if len(longs) > len(shorts) and long_score >= threshold:
        signal = LONG
    elif len(shorts) > len(longs) and short_score >= threshold:
        signal = SHORT
    else:
        signal = HOLD

    if longs and shorts:
        warnings.append("Aday stratejiler çelişiyor (hem LONG hem SHORT) — HOLD tercih edilir.")

    return CompositeResult(
        signal=signal,
        long_score=round(long_score, 4),
        short_score=round(short_score, 4),
        family_scores={k: round(v.net, 4) for k, v in sorted(fams.items())},
        agreeing_strategies=longs if signal == LONG else shorts if signal == SHORT else [],
        warnings=warnings,
    )
