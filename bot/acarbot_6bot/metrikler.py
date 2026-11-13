# -*- coding: utf-8 -*-
"""metrikler.py — jurnal CSV'sinden ADİL metrikler (WR tek başına yanıltıcı).

  python metrikler.py logs/islem_jurnali_adil.csv

Ürettiği metrikler (bot başına):
  işlem, net, ortalama, WR, ortalama kazanç, ortalama kayıp, kazanç/kayıp oranı,
  BAŞABAŞ WR (komisyon dahil), kâr faktörü, en büyük düşüş (işlem sırasına göre),
  en iyi/en kötü işlem, ortalama tepe kâr.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from collections import defaultdict


def main(yol: str) -> int:
    if not yol:
        print("kullanim: python metrikler.py logs/islem_jurnali_<etiket>.csv")
        return 1
    kova: dict[str, list] = defaultdict(list)
    with open(yol, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            kova[r["bot"]].append((float(r["net_usd"]), float(r["tepe_usd"]), r["sembol"], r["cikis_nedeni"]))

    print(f"{'BOT':<12}{'işlem':>6}{'net$':>9}{'ort$':>8}{'WR%':>6}{'ort.kaz':>9}{'ort.kay':>9}"
          f"{'K/K':>6}{'başabaş WR':>11}{'PF':>7}{'maksDD':>9}{'en kötü':>9}")
    print("-" * 108)
    for bot, lst in sorted(kova.items()):
        net = [x[0] for x in lst]
        kaz = [x for x in net if x > 0]
        kay = [x for x in net if x <= 0]
        kk = (st.mean(kaz) / abs(st.mean(kay))) if kaz and kay else float("inf")
        basabas = 100.0 / (1.0 + kk) if kk not in (0, float("inf")) else 0.0
        pf = (sum(kaz) / abs(sum(kay))) if kay and sum(kay) != 0 else float("inf")
        k = 0.0
        tepe = 0.0
        mdd = 0.0
        for x in net:
            k += x
            tepe = max(tepe, k)
            mdd = min(mdd, k - tepe)
        print(f"{bot:<12}{len(lst):>6}{sum(net):>+9.2f}{st.mean(net):>+8.2f}"
              f"{100*len(kaz)/len(net):>6.0f}{(st.mean(kaz) if kaz else 0):>+9.2f}"
              f"{(st.mean(kay) if kay else 0):>+9.2f}{kk:>6.2f}{basabas:>11.0f}"
              f"{pf:>7.2f}{mdd:>+9.2f}{min(net):>+9.2f}")
    print()
    print("Not: 'başabaş WR' = bu kazanç/kayıp oranıyla kâra geçmek için gereken isabet oranı.")
    print("     Gerçek WR bunun altındaysa bot uzun vadede kaybeder, kasa artı görünse bile.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
