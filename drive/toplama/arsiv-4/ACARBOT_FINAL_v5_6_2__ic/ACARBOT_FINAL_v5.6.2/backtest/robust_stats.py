"""KÜME-DAYANIKLI İSTATİSTİK — iid varsayımını kaldırır.

v5.4 denetiminde bulunan kusur
------------------------------
`entry_edge` standart hataları iid varsayımıyla hesaplıyordu. Oysa:

  * Aynı sembolde 12 bar içinde birden fazla aday olabiliyor
    (5m'de ÖLÇÜLEN %45,9 — denetimde sanılan %26'dan yüksek).
  * 1h'de 105 aday yalnız 46 ayrı güne yayılıyor.
  * Ufuk pencereleri örtüşüyor (48 bar ileri getiri, 1 bar arayla).
  * 15 ayrı hipotez test ediliyor (5 ufuk x 3 zaman dilimi),
    düzeltme yapılmıyordu.

Bu yüzden raporlanan güven aralıkları GERÇEK belirsizlikten DAR.

Bu modül üç düzeltme sağlar
---------------------------
1. `dedupe_cluster`  : aynı sembolde yakın adaylardan birini tut.
2. `cluster_bootstrap`: GÜN bazlı küme bootstrap'ı — aynı günün
   adayları birlikte yeniden örneklenir, gün içi bağımlılık korunur.
3. `bonferroni` / `verdict`: çoklu test düzeltmesi ve
   "kenar yok" ile "ölçülemedi" ayrımı.

ÖNEMLİ: "kenar yok" ile "yetersiz örneklem" AYNI ŞEY DEĞİLDİR.
GA üst sınırı maliyetin altındaysa kenar ELENMİŞTİR.
GA üst sınırı maliyetin üstündeyse kenar ÖLÇÜLEMEMİŞTİR.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

# Yön/kenar iddiası için asgari bağımsız örneklem.
MIN_INDEPENDENT_N = 300
# Kümeleme penceresi: aynı sembolde bu kadar bar içindeki adaylar
# tek bir gözlem sayılır (varsayılan 12 bar).
DEFAULT_CLUSTER_BARS = 12
DAY_MS = 86_400_000


def dedupe_cluster(
    rows: list[dict], *, cluster_bars: int = DEFAULT_CLUSTER_BARS,
    timeframe_ms: int, score_key: str = "score",
) -> tuple[list[dict], dict]:
    """Aynı sembolde yakın adayları teke indirir.

    Kümede EN YÜKSEK skorlu aday tutulur (sinyal kalitesini
    korumak için); rastgele seçim skor dağılımını bozar.
    """
    gap = cluster_bars * timeframe_ms
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)

    kept: list[dict] = []
    for sym, items in by_sym.items():
        items.sort(key=lambda r: r["ts_ms"])
        cluster: list[dict] = []
        last_ts: int | None = None
        for r in items:
            ts = int(r["ts_ms"])
            if last_ts is None or ts - last_ts <= gap:
                cluster.append(r)
            else:
                kept.append(max(cluster, key=lambda x: x.get(score_key) or 0.0))
                cluster = [r]
            last_ts = ts
        if cluster:
            kept.append(max(cluster, key=lambda x: x.get(score_key) or 0.0))

    kept.sort(key=lambda r: (r["symbol"], r["ts_ms"]))
    info = {
        "girdi_aday": len(rows),
        "bagimsiz_aday": len(kept),
        "elenen": len(rows) - len(kept),
        "kume_penceresi_bar": cluster_bars,
        "kural": "aynı sembolde <=N bar arayla olanlardan en yüksek skorlu tutulur",
    }
    return kept, info


def cluster_bootstrap(
    rows: list[dict], value_key: str, *, iterations: int = 2000,
    seed: int = 42, cluster_key: str = "day",
) -> dict:
    """Gün bazlı küme bootstrap güven aralığı.

    Aynı günün adayları BİRLİKTE yeniden örneklenir. Böylece gün içi
    bağımlılık (aynı rejim, aynı BTC hareketi) GA'ya yansır.
    """
    groups: dict[object, list[float]] = defaultdict(list)
    for r in rows:
        v = r.get(value_key)
        if v is None or not math.isfinite(float(v)):
            continue
        if cluster_key == "day":
            k = int(r["ts_ms"]) // DAY_MS
        elif cluster_key == "symbol_day":
            k = (r["symbol"], int(r["ts_ms"]) // DAY_MS)
        else:
            k = r.get(cluster_key)
        groups[k].append(float(v))

    keys = list(groups)
    if not keys:
        return {"n": 0, "kume": 0, "mean": None, "lo": None, "hi": None}

    all_vals = [v for g in groups.values() for v in g]
    point = sum(all_vals) / len(all_vals)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        tot = 0.0
        cnt = 0
        for _ in range(len(keys)):
            g = groups[keys[rng.randrange(len(keys))]]
            tot += sum(g)
            cnt += len(g)
        if cnt:
            means.append(tot / cnt)
    means.sort()

    def _q(p: float) -> float:
        if not means:
            return float("nan")
        i = min(len(means) - 1, max(0, int(p * len(means))))
        return means[i]

    lo, hi = _q(0.025), _q(0.975)
    naive_se = _naive_se(all_vals)
    cl_se = _sd(means)
    return {
        "n": len(all_vals),
        "kume": len(keys),
        "mean": round(point, 6),
        "lo": round(lo, 6),
        "hi": round(hi, 6),
        "kume_se": round(cl_se, 6) if cl_se is not None else None,
        "iid_se": round(naive_se, 6) if naive_se is not None else None,
        "genisleme_katsayisi": (
            round(cl_se / naive_se, 3)
            if cl_se and naive_se and naive_se > 0 else None
        ),
        "yontem": f"{cluster_key} küme bootstrap, {iterations} tekrar",
    }


def _sd(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _naive_se(xs: list[float]) -> float | None:
    s = _sd(xs)
    return s / math.sqrt(len(xs)) if s is not None and xs else None


def bonferroni(p: float | None, m: int) -> float | None:
    """Çoklu karşılaştırma düzeltmesi (m test)."""
    if p is None or m <= 0:
        return None
    return min(1.0, p * m)


def verdict(
    *, net_lo: float | None, net_hi: float | None,
    n_independent: int, cost_r: float,
    p_adjusted: float | None = None,
    min_n: int = MIN_INDEPENDENT_N,
) -> dict:
    """Üç durumlu hüküm: VAR / YOK / ÖLÇÜLEMEDİ.

    v5.4 yalnız "var mı?" diye bakıyordu; n=105 ve GA üst sınırı
    maliyetin ÜSTÜNDE olan 1h sonucu "KENAR YOK" diye damgalanıyordu.
    Oysa o sonuç kenarı ELEMİYOR, ÖLÇEMİYOR.
    """
    if net_lo is None or net_hi is None:
        return {
            "hukum": "YETERSIZ_ORNEKLEM",
            "neden": "Güven aralığı hesaplanamadı.",
            "bagimsiz_n": n_independent,
        }
    if n_independent < min_n:
        return {
            "hukum": "YETERSIZ_ORNEKLEM",
            "neden": (
                f"Bağımsız örneklem {n_independent} < {min_n}. "
                f"GA [{net_lo:+.4f}, {net_hi:+.4f}] R, maliyet {cost_r:.4f} R. "
                "Kenar elenmiş DEĞİL, ölçülememiş."
            ),
            "bagimsiz_n": n_independent,
            "ga": [net_lo, net_hi],
            "maliyet_r": cost_r,
        }
    if net_hi <= 0:
        return {
            "hukum": "GIRIS_KENARI_YOK",
            "neden": (
                f"Maliyet sonrası GA üst sınırı {net_hi:+.4f} <= 0. "
                "Kenar istatistiksel olarak ELENDİ."
            ),
            "bagimsiz_n": n_independent,
            "ga": [net_lo, net_hi],
            "maliyet_r": cost_r,
        }
    if net_lo > 0 and (p_adjusted is None or p_adjusted < 0.05):
        return {
            "hukum": "GIRIS_KENARI_VAR",
            "neden": (
                f"Maliyet sonrası GA alt sınırı {net_lo:+.4f} > 0"
                + (f", düzeltilmiş p={p_adjusted:.4f}" if p_adjusted is not None else "")
            ),
            "bagimsiz_n": n_independent,
            "ga": [net_lo, net_hi],
            "maliyet_r": cost_r,
        }
    return {
        "hukum": "BELIRSIZ",
        "neden": (
            f"GA [{net_lo:+.4f}, {net_hi:+.4f}] sıfırı kapsıyor; "
            "örneklem yeterli ama yön belirsiz."
        ),
        "bagimsiz_n": n_independent,
        "ga": [net_lo, net_hi],
        "maliyet_r": cost_r,
    }


def clustering_report(
    rows: list[dict], *, timeframe_ms: int,
    cluster_bars: int = DEFAULT_CLUSTER_BARS,
) -> dict:
    """Ham kümeleme teşhisi — düzeltme öncesi durumun ölçüsü."""
    gap = cluster_bars * timeframe_ms
    by_sym: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(int(r["ts_ms"]))
    clustered = 0
    for ts in by_sym.values():
        ts.sort()
        for i, t in enumerate(ts):
            if any(0 < abs(t - u) <= gap for j, u in enumerate(ts) if j != i):
                clustered += 1
    n = len(rows)
    return {
        "aday": n,
        "komsusu_olan": clustered,
        "komsu_orani": round(clustered / n, 4) if n else None,
        "ayri_gun": len({int(r["ts_ms"]) // DAY_MS for r in rows}),
        "pencere_bar": cluster_bars,
    }
