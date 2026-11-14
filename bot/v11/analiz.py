"""İndikatör kovası analizi: her sinyal için ileri getiri (maliyet düşülmüş), kovalara göre."""
from __future__ import annotations

from .kurallar import TAKER_ORAN
from .motor import hazirla
from .veri import Seri

MALIYET = 2 * TAKER_ORAN   # gidiş-dönüş, notional oranı (%0.1)


def _kova(deger, sinirlar):
    if deger is None:
        return "yok"
    for ust, ad in sinirlar:
        if deger < ust:
            return ad
    return sinirlar[-1][1] + "+"


KOVALAR = {
    "adx": [(20, "<20"), (25, "20-25"), (30, "25-30"), (35, "30-35"), (1e9, "35")],
    "bbw": [(0.003, "<0.3%"), (0.005, "0.3-0.5%"), (0.01, "0.5-1%"), (0.02, "1-2%"), (1e9, "2%")],
    "rsi_sapma": [(6, "<6"), (12, "6-12"), (18, "12-18"), (1e9, "18")],
}


def kova_tablosu(seriler: list[Seri], strateji, ileri: int = 30) -> list[dict]:
    """Her sinyal için: yön × (close[i+1+ileri]/open[i+1] − 1) − maliyet. Kovalara göre özet."""
    kayit: list[dict] = []
    for s in seriler:
        f = hazirla(s)
        n = len(f["c"])
        for i in range(60, n - ileri - 1):
            side = strateji(f, i)
            if side == 0:
                continue
            giris = f["o"][i + 1]
            cikis = f["c"][i + 1 + ileri]
            net = side * (cikis / giris - 1) - MALIYET
            ozn = {"adx": f["adx"][i], "bbw": f["bbw"][i],
                   "rsi_sapma": None if f["rsi"][i] is None else abs(f["rsi"][i] - 50)}
            if f.get("funding") is not None:
                fu = f["funding"][i]
                ozn["funding"] = None if fu is None else ("+" if fu > 0 else "-" if fu < 0 else "0")
            kayit.append({"sembol": s.sembol, "net": net, **ozn})
    sonuc = []
    for alan, sinirlar in KOVALAR.items():
        gruplar: dict[str, list[float]] = {}
        for k in kayit:
            gruplar.setdefault(_kova(k.get(alan), sinirlar), []).append(k["net"])
        for kova, degerler in sorted(gruplar.items()):
            n_ = len(degerler)
            sonuc.append({"indikator": alan, "kova": kova, "n": n_,
                          "ort_net_yuzde": 100 * sum(degerler) / n_,
                          "isabet_yuzde": 100 * sum(1 for d in degerler if d > 0) / n_})
    if any("funding" in k for k in kayit):
        gruplar = {}
        for k in kayit:
            if "funding" in k:
                gruplar.setdefault(str(k["funding"]), []).append(k["net"])
        for kova, degerler in sorted(gruplar.items()):
            n_ = len(degerler)
            sonuc.append({"indikator": "funding_isareti", "kova": kova, "n": n_,
                          "ort_net_yuzde": 100 * sum(degerler) / n_,
                          "isabet_yuzde": 100 * sum(1 for d in degerler if d > 0) / n_})
    return sonuc
