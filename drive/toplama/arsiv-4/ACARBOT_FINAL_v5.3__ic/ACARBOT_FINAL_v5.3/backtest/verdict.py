"""v5.2 — HÜKÜM MOTORU (walk-forward öncelikli).

SORUN (kullanıcı tespiti, v5.1)
------------------------------
v5.1'in `_verdict()` fonksiyonu ÖNCE birincil koşunun işlem sayısına
bakıyordu:

    if count < min_trades:  return "örneklem yetersiz"

Bu, negatif kaniti GİZLİYORDU. Aynı raporun walk-forward bölümünde
61 işlem, 0/6 kârlı pencere ve -433,64 USDT vardı; ama hüküm yalnızca
birincil koşudaki 5 işlemi görüp "örneklem yetersiz" diyordu.

Birincil koşudaki 5 işlem zaten YAPAY olarak küçüktü: ilk zararlardan
sonra portföy drawdown koruması devreye girip 1.117 girişi reddetmişti.
Yani "az işlem" bir belirsizlik değil, sistemin kendi kaybının sonucu.

ÇÖZÜM
-----
Hüküm, kanıtın TAMAMINA bakar ve şu sırayla değerlendirir:

  0. Maliyetler kapalıysa           → GEÇERSİZ (iyimser koşu kanıt sayılmaz)
  1. WF yeterince işlem + net <= 0
     + 0/N pencere kârlı            → KENAR YOK  (örneklem bahanesi YOK)
  2. Toplam kanıt < min_trades      → ÖRNEKLEM YETERSİZ
  3. Net <= 0 veya MC kayıp > %50   → KENAR YOK
  4. Risk hedefi sapması            → KENAR VAR AMA RİSK SAPKIYOR
  5. aksi                           → KENAR ADAYI

Hüküm artık düz metin değil, YAPILANDIRILMIŞ bir nesnedir: kod, önem
derecesi, gerekçeler ve kanıt sözlüğü. Böylece test edilebilir ve
regresyon kapısı tarafından makine okunabilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Hüküm kodları
INVALID_OPTIMISTIC = "INVALID_OPTIMISTIC"
NO_EDGE = "NO_EDGE"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
EDGE_RISK_DRIFT = "EDGE_RISK_DRIFT"
EDGE_CANDIDATE = "EDGE_CANDIDATE"

_SEVERITY = {
    INVALID_OPTIMISTIC: "invalid",
    NO_EDGE: "red",
    INSUFFICIENT_SAMPLE: "red",
    EDGE_RISK_DRIFT: "yellow",
    EDGE_CANDIDATE: "green",
}
_ICON = {"invalid": "⛔", "red": "🔴", "yellow": "🟡", "green": "🟢"}

# Walk-forward'da "kenar yok" demek için gereken asgari işlem.
# Birincil koşunun eşiğinden (200) düşük tutulur: WF pencereleri bağımsız
# başlangıç bakiyesiyle koşar, bu yüzden toplam işlem daha hızlı birikir.
DEFAULT_MIN_WF_TRADES = 30

# Drawdown koruması, açılan işlem sayısının bu katından fazla girişi
# kestiyse birincil koşunun örneklemi "kesilmiş" sayılır.
# NOT: oran TÜM redlere göre hesaplanamaz — dusuk_hacim gibi bar
# düzeyi redler (126.652) payı boğar ve gerçek kesilmeyi gizler.
TRUNCATION_TRADE_MULTIPLE = 2.0
TRUNCATION_MIN_REJECTIONS = 10


@dataclass(frozen=True)
class Verdict:
    code: str
    severity: str
    headline: str
    text: str
    reasons: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "headline": self.headline,
            "text": self.text,
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
        }

    def render(self) -> str:
        lines = [f"{_ICON[self.severity]} **{self.headline}**", ""]
        lines += [f"- {r}" for r in self.reasons]
        return "\n".join(lines)


def _as_int(value, default: int = 0) -> int:
    """Bozuk tipte int alanı güvenli okur (rapor doğrulaması için)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _wf_evidence(runs: list[dict]) -> dict:
    """Tüm koşuların walk-forward kanıtını toplar (birincil öncelikli)."""
    for block in runs:
        wf = block.get("walk_forward") or {}
        windows = wf.get("windows")
        # v5.2: bozuk tipe karşı savunmalı — kapı bu veriyi zaten reddeder,
        # ama hüküm motoru çökmemeli (AttributeErrormaskelemesi  gerçek sorunu).
        if not isinstance(windows, list) or not windows:
            continue
        rows = [w for w in windows if isinstance(w, dict)]
        if not rows:
            continue
        trades = sum(_as_int(w.get("trades", 0)) for w in rows)
        total_windows = _as_int(wf.get("total_windows"), len(rows))
        return {
            "label": block.get("label", ""),
            "total_windows": total_windows,
            "profitable_windows": _as_int(wf.get("profitable_windows", 0)),
            "total_trades": trades,
            "total_net_pnl": _as_float(wf.get("total_net_pnl", 0.0)),
            "worst_window_net_pnl": _as_float(wf.get("worst_window_net_pnl", 0.0)),
        }
    return {
        "label": "", "total_windows": 0, "profitable_windows": 0,
        "total_trades": 0, "total_net_pnl": 0.0, "worst_window_net_pnl": 0.0,
    }


def _truncation(runs: list[dict]) -> dict:
    """Birincil koşuda drawdown korumasının kestiği girişler.

    Ölçüt, açılan işlem sayısına göredir: 5 işlem açılmış ama 1.117
    giriş drawdown korumasıyla kesilmişse örneklem kesilmiştir.
    """
    primary = runs[0] if runs else {}
    counts = primary.get("rejection_counts") or {}
    dd = _as_int(counts.get("PORTFOLIO_DRAWDOWN_PROTECTION", 0))
    total = sum(_as_int(v) for v in counts.values())
    trades = _as_int(primary.get("trade_count", 0))
    bar_ratio = dd / total if total else 0.0
    per_trade = dd / trades if trades else float(dd)
    truncated = (
        dd >= TRUNCATION_MIN_REJECTIONS
        and per_trade >= TRUNCATION_TRADE_MULTIPLE
    )
    return {
        "drawdown_rejections": dd,
        "total_rejections": total,
        "ratio_of_all_rejections": round(bar_ratio, 6),
        "rejections_per_opened_trade": round(per_trade, 4),
        "truncated": truncated,
    }


def decide(
    runs: list[dict],
    min_trades: int = 200,
    min_wf_trades: int = DEFAULT_MIN_WF_TRADES,
    cost_model: dict | None = None,
    min_trades_source: str = "primary",
) -> Verdict:
    """Koşu bloklarından yapılandırılmış hüküm üretir.

    min_trades_source: "primary" (geriye uyum) | "all" — örneklem
        eşiğinin birincil koşuya mı yoksa birincil + WF toplamına mı
        uygulanacağı. v5.2 varsayılanı "all".
    """
    if not runs:
        return Verdict(
            code=INSUFFICIENT_SAMPLE, severity="red",
            headline="HÜKÜM YOK — koşu bulunamadı",
            text="Hiç koşu bloğu yok.",
            reasons=["Rapor boş; doğrulama koşulmamış."],
        )

    primary = runs[0]
    count = _as_int(primary.get("trade_count", 0))
    pnl = _as_float(primary.get("net_pnl", 0.0))
    mc = primary.get("monte_carlo") or {}
    prob_loss = _as_float(mc.get("prob_loss", 0.0))
    audit = primary.get("risk_audit") or {}
    breaches = _as_int(audit.get("breach_count", 0))
    max_ratio = _as_float(audit.get("max_realized_over_target", 0.0))
    threshold = _as_float(audit.get("breach_ratio_threshold", 1.3), 1.3)
    wf = _wf_evidence(runs)
    trunc = _truncation(runs)
    intrabar = primary.get("intrabar") or {}
    coverage = _as_float(intrabar.get("real_coverage_ratio", 0.0))

    evidence = {
        "primary_trades": count,
        "primary_net_pnl": round(pnl, 4),
        "mc_prob_loss": prob_loss,
        "risk_breaches": breaches,
        "max_realized_over_target": max_ratio,
        "breach_ratio_threshold": threshold,
        "walk_forward": wf,
        "sample_truncation": trunc,
        "real_1m_coverage_ratio": coverage,
        "min_trades": min_trades,
        "min_wf_trades": min_wf_trades,
        "min_trades_source": min_trades_source,
    }

    # --- 0) Maliyetsiz koşu kanıt sayılmaz -----------------------------
    costs = cost_model or {}
    if costs.get("optimistic_warning") or costs.get("enabled") is False:
        return Verdict(
            code=INVALID_OPTIMISTIC, severity="invalid",
            headline="GEÇERSİZ KOŞU — MALİYETLER KAPALI",
            text="Maliyetler kapalı; bu sonuç kanıt sayılamaz.",
            reasons=[
                "Spread/kayma/gecikme uygulanmadı. Sonuç yapısal olarak iyimser.",
                "`--no-costs` yalnızca karşılaştırma içindir; hüküm üretmez.",
            ],
            evidence=evidence,
        )

    # --- 1) Walk-forward: negatif + hiç kârlı pencere yok → KENAR YOK --
    wf_decisive = (
        wf["total_trades"] >= min_wf_trades
        and wf["total_net_pnl"] <= 0
        and wf["profitable_windows"] == 0
        and wf["total_windows"] > 0
    )
    if wf_decisive:
        reasons = [
            f"Walk-forward: {wf['total_trades']} işlem, "
            f"{wf['profitable_windows']}/{wf['total_windows']} pencere kârlı, "
            f"toplam {wf['total_net_pnl']:.2f} USDT.",
            f"En kötü pencere {wf['worst_window_net_pnl']:.2f} USDT. "
            f"Hiçbir alt dönemde kâr yok — tek dönemlik şans açıklaması geçersiz.",
            f"Birincil koşu: {count} işlem, net {pnl:.2f} USDT, "
            f"Monte Carlo kayıp olasılığı %{prob_loss * 100:.1f}.",
        ]
        if trunc["truncated"]:
            reasons.append(
                f"Birincil koşunun örneklemi KESİLMİŞ: "
                f"{trunc['drawdown_rejections']} giriş drawdown korumasıyla "
                f"reddedildi (açılan işlem başına "
                f"{trunc['rejections_per_opened_trade']:.1f} red). "
                f"Az işlem bir belirsizlik değil, kaybın sonucu.",
            )
        if breaches:
            reasons.append(
                f"Ayrıca {breaches} işlemde gerçekleşen kayıp hedefin "
                f"{threshold} katını aştı (maks {max_ratio:.3f}x).",
            )
        if coverage <= 0:
            reasons.append(
                "Mum içi yol gerçek 1m verisiyle DOĞRULANMADI "
                f"(kapsama %{coverage * 100:.1f}); sonuç sentetik yola dayanıyor.",
            )
        reasons.append(
            "Gerçek paraya ölçekleme YAPILMAMALIDIR. "
            "`max_loss_per_position` 2,5–5 USDT'de tutulmalı.",
        )
        return Verdict(
            code=NO_EDGE, severity="red",
            headline="KENAR YOK — walk-forward tüm pencerelerde zararlı",
            text=" ".join(reasons), reasons=reasons, evidence=evidence,
        )

    # --- 2) Örneklem eşiği ---------------------------------------------
    total_evidence = count + wf["total_trades"]
    measured_count = total_evidence if min_trades_source == "all" else count
    if measured_count < min_trades:
        reasons = [
            f"Toplam kanıt {measured_count} işlem "
            f"(birincil {count} + walk-forward {wf['total_trades']}); "
            f"istatistiksel hüküm için en az {min_trades} gerekir.",
            f"Walk-forward: {wf['profitable_windows']}/{wf['total_windows']} "
            f"pencere kârlı, toplam {wf['total_net_pnl']:.2f} USDT.",
        ]
        if wf["total_net_pnl"] < 0:
            reasons.append(
                f"DİKKAT: örneklem yetersiz olsa da walk-forward toplamı "
                f"NEGATİF ({wf['total_net_pnl']:.2f} USDT). Bu, kenar "
                f"lehine bir işaret DEĞİLDİR.",
            )
        if trunc["truncated"]:
            reasons.append(
                f"Örneklem drawdown korumasıyla kesilmiş "
                f"({trunc['drawdown_rejections']} red). Daha çok veri "
                f"tek başına çözmez; risk ölçekleme gerekir.",
            )
        reasons.append(
            "Daha uzun veri veya daha çok sembol ile tekrar koşun. "
            "Bu sonuçla gerçek paraya ölçekleme YAPILMAMALIDIR.",
        )
        return Verdict(
            code=INSUFFICIENT_SAMPLE, severity="red",
            headline="KENAR KANITLANMADI — örneklem yetersiz",
            text=" ".join(reasons), reasons=reasons, evidence=evidence,
        )

    # --- 3) Yeterli örneklem ama negatif -------------------------------
    if pnl <= 0 or prob_loss > 0.5:
        reasons = [
            f"{count} işlemde net {pnl:.2f} USDT, "
            f"Monte Carlo kayıp olasılığı %{prob_loss * 100:.1f}.",
            f"Walk-forward: {wf['profitable_windows']}/{wf['total_windows']} "
            f"pencere kârlı, toplam {wf['total_net_pnl']:.2f} USDT.",
            "Strateji maliyetler altında kâr üretmiyor.",
            "`max_loss_per_position` 2,5–5 USDT'de tutulmalı.",
        ]
        return Verdict(
            code=NO_EDGE, severity="red", headline="KENAR YOK",
            text=" ".join(reasons), reasons=reasons, evidence=evidence,
        )

    # --- 4) Kârlı ama risk hedefi sapıyor ------------------------------
    if breaches:
        reasons = [
            f"Net {pnl:.2f} USDT, kayıp olasılığı %{prob_loss * 100:.1f}.",
            f"Fakat {breaches} işlemde gerçekleşen kayıp hedefin "
            f"{threshold} katını aştı (maks {max_ratio:.3f}x).",
            "Ölçeklemeden önce stop/mum içi yol kalibrasyonu gerekir.",
        ]
        return Verdict(
            code=EDGE_RISK_DRIFT, severity="yellow",
            headline="KENAR VAR AMA RİSK HEDEFİ SAPKIYOR",
            text=" ".join(reasons), reasons=reasons, evidence=evidence,
        )

    # --- 5) Aday -------------------------------------------------------
    reasons = [
        f"{count} işlemde net {pnl:.2f} USDT, "
        f"kayıp olasılığı %{prob_loss * 100:.1f}, risk aşımı yok.",
        f"Walk-forward: {wf['profitable_windows']}/{wf['total_windows']} "
        f"pencere kârlı, toplam {wf['total_net_pnl']:.2f} USDT.",
    ]
    if coverage < 0.8:
        reasons.append(
            f"Mum içi yol kapsaması %{coverage * 100:.1f} — gerçek 1m "
            f"doğrulaması tamamlanmadan ölçeklenmemeli.",
        )
    reasons.append(
        "Yine de gerçek/testnet oturumuyla doğrulanmadan ölçeklenmemeli.",
    )
    return Verdict(
        code=EDGE_CANDIDATE, severity="green", headline="KENAR ADAYI",
        text=" ".join(reasons), reasons=reasons, evidence=evidence,
    )
