"""Trailing stop varyant deneyi — v5.6 (F bölümü).

Şartname: dört varyant AYRI AYRI test edilir; en iyisi yalnız
out-of-sample'da da başarılıysa seçilir.

VARYANTLAR
----------
A  MEVCUT            — trail_activation_r = 0.75 (TP1'den ÖNCE başlar)
B  TP1_SONRASI       — trail_activation_r = 1.0  (TP1 ile aynı anda)
C  TP1_SONRASI_BE    — B + break-even zorunlu
D  ATR_DINAMIK       — ATR çarpanı oynaklığa göre ölçeklenir

NEDEN ÖNEMLİ?
-------------
Ölçülen çıkış ayarlarında trail 0,75R'de, yani TP1'den (1,0R) ÖNCE
aktive oluyor. Bu, kâr alma ile takip stopunun çakışması demek.
Ama v5.5 ölçümü çıkış geometrisinin ANA suçlu OLMADIĞINI gösterdi
(simetrik ±1R daha kötüydü). Yani bu deney "düzeltme" değil,
hipotez sınamasıdır — sonucu peşinen bilinmiyor.

DÜRÜSTLÜK KURALLARI
-------------------
* Her varyant ayrı raporlanır: brüt/net, PF, WR, avg R, maxDD,
  komisyon, funding, kayma, işlem sayısı.
* In-sample en iyisi OTOMATİK seçilmez; OOS'ta da doğrulanmalı.
* Örneklem yetersizse hüküm YETERSIZ_ORNEKLEM'dir.
* Hiçbir varyant pozitif net beklenti göstermezse "hiçbiri" denir.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

MIN_TRADES_PER_VARIANT = 30


@dataclass(frozen=True)
class TrailingVariant:
    key: str
    label: str
    trail_activation_r: float
    trail_atr_multiple: float
    breakeven_enabled: bool
    description: str


VARIANTS: tuple[TrailingVariant, ...] = (
    TrailingVariant(
        "A_mevcut", "Mevcut sistem", 0.75, 2.0, True,
        "Trail 0,75R'de başlar — TP1'den (1,0R) ÖNCE. Mevcut davranış.",
    ),
    TrailingVariant(
        "B_tp1_sonrasi", "Yalnız TP1 sonrası", 1.0, 2.0, False,
        "Trail TP1 ile aynı anda (1,0R) başlar; break-even KAPALI. "
        "NOT: ilk tanımda break-even True idi ve C ile ÖZDEŞti; "
        "deney tasarımı hatası düzeltildi.",
    ),
    TrailingVariant(
        "C_tp1_be", "TP1 sonrası + break-even", 1.0, 2.0, True,
        "B ile aynı, break-even açıkça zorunlu (maliyet zemini).",
    ),
    TrailingVariant(
        "D_atr_dinamik", "ATR dinamik", 1.0, 3.0, True,
        "TP1 sonrası daha geniş ATR çarpanı (3,0) — gürültüde erken çıkışı azaltır.",
    ),
)


def apply_variant(exit_cfg, variant: TrailingVariant):
    """ExitConfig kopyasına varyantı uygular (orijinali bozmaz)."""
    return replace(
        exit_cfg,
        trail_activation_r=variant.trail_activation_r,
        trail_atr_multiple=variant.trail_atr_multiple,
        breakeven_enabled=variant.breakeven_enabled,
    )


def evaluate_variant(key: str, metrics: dict, oos_metrics: dict | None) -> dict:
    """Tek varyantın hükmü. OOS yoksa 'seçilemez' denir."""
    n = int(metrics.get("trades", 0) or 0)
    net = metrics.get("net_pnl")
    exp_r = metrics.get("expectancy_r")
    row = {
        "varyant": key,
        "islem": n,
        "net_pnl": net,
        "expectancy_r": exp_r,
        "profit_factor": metrics.get("profit_factor"),
        "win_rate": metrics.get("win_rate"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "komisyon": metrics.get("fees_paid"),
        "funding": metrics.get("funding_paid"),
        "kayma": metrics.get("slippage_paid"),
        "oos_net_pnl": None,
        "oos_expectancy_r": None,
        "hukum": "YETERSIZ_ORNEKLEM",
        "secilebilir": False,
    }
    if oos_metrics is not None:
        row["oos_net_pnl"] = oos_metrics.get("net_pnl")
        row["oos_expectancy_r"] = oos_metrics.get("expectancy_r")
    if n < MIN_TRADES_PER_VARIANT:
        row["hukum"] = "YETERSIZ_ORNEKLEM"
        return row
    positive_is = exp_r is not None and exp_r > 0
    positive_oos = (
        row["oos_expectancy_r"] is not None and row["oos_expectancy_r"] > 0
    )
    if positive_is and positive_oos:
        row["hukum"] = "IS_VE_OOS_POZITIF"
        row["secilebilir"] = True
    elif positive_is and oos_metrics is None:
        row["hukum"] = "IS_POZITIF_OOS_YOK"
    elif positive_is:
        row["hukum"] = "OOS_DOGRULAMADI"
    else:
        row["hukum"] = "NEGATIF_BEKLENTI"
    return row


def pick_best(rows: list[dict]) -> dict:
    """En iyi varyantı seç — yalnız IS+OOS pozitif olanlar arasından.

    Hiçbiri uygun değilse açıkça 'HICBIRI' döner; zarar azaltan
    varyant 'kazanan' sayılmaz.
    """
    eligible = [r for r in rows if r.get("secilebilir")]
    if not eligible:
        return {
            "secilen": "HICBIRI",
            "neden": (
                "Hiçbir varyant hem in-sample hem out-of-sample pozitif "
                "net beklenti göstermedi. Zarar azaltmak seçim ölçütü değildir."
            ),
            "aday_sayisi": 0,
        }
    best = max(eligible, key=lambda r: (r["oos_expectancy_r"], r["expectancy_r"]))
    return {
        "secilen": best["varyant"],
        "neden": (
            f"IS beklenti {best['expectancy_r']:.4f}R, "
            f"OOS beklenti {best['oos_expectancy_r']:.4f}R — ikisi de pozitif."
        ),
        "aday_sayisi": len(eligible),
    }