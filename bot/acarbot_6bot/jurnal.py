# -*- coding: utf-8 -*-
"""jurnal.py — her kapanan işlemi CSV'ye yazan basit jurnal (rapor eleştirisi #3).

Runner'ın `Durum.yaz()` döngüsüne takılır: her panel güncellemesinde motorların
kapalı işlem listesini okur, daha önce yazılmamış olanları CSV'ye ekler.
Böylece koşu erken kapatılsa bile işlem dökümü kaybolmaz.

Sütunlar: zaman, bot, sembol, yon, giris, cikis, net_usd, tepe_usd, cikis_nedeni, tetik
"""
from __future__ import annotations

import csv
import os
import time


class IslemJurnali:
    def __init__(self, etiket: str, klasor: str = "logs") -> None:
        os.makedirs(klasor, exist_ok=True)
        self.yol = os.path.join(klasor, f"islem_jurnali_{etiket}.csv")
        self._gorulen: dict[str, set] = {}
        self._ilk = not os.path.exists(self.yol)
        if self._ilk:
            with open(self.yol, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(["zaman", "bot", "sembol", "yon", "giris", "cikis",
                                         "net_usd", "tepe_usd", "cikis_nedeni", "tetik"])

    def _kimlik(self, t: dict) -> str:
        return str(t.get("id") or (str(t.get("symbol")) + str(t.get("closed_ts"))))

    def yaz(self, motorlar, oku) -> int:
        """motorlar: runner'ın (ad, etiket, motor, metod, surum) listesi.
        oku: motor -> snapshot sözlüğü (runner'daki test_4bot.durum_al)."""
        yeni = 0
        with open(self.yol, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for ad, _et, motor, _md, _sv in motorlar:
                try:
                    snap = oku(motor) or {}
                except Exception:
                    continue
                kt = snap.get("closed_trades") or []
                if not kt and hasattr(motor, "kapanan"):
                    kt = list(motor.kapanan)
                gorulen = self._gorulen.setdefault(ad, set())
                for t in kt:
                    kid = self._kimlik(t)
                    if kid in gorulen:
                        continue
                    gorulen.add(kid)
                    yon = str(t.get("side") if t.get("side") is not None else t.get("yon"))
                    yon = "LONG" if yon in ("LONG", "1", "1.0", "BUY") else "SHORT"
                    w.writerow([
                        time.strftime("%H:%M:%S", time.localtime(float(t.get("closed_ts") or time.time()))),
                        ad, t.get("symbol"), yon, t.get("entry_price"), t.get("exit_price"),
                        round(float(t.get("net_pnl_usd") or 0.0), 4),
                        round(float(t.get("peak_pnl_usd") or 0.0), 4),
                        t.get("exit_reason"), str(t.get("trigger_type") or "")[:90],
                    ])
                    yeni += 1
        return yeni
