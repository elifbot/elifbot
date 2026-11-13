# -*- coding: utf-8 -*-
"""ledger.py — append-only jurnal + yeniden başlatma uzlaştırması.

Neden gerekli: bir bot çöktüğünde "hangi emir gitti, hangi pozisyon açık" sorusunun
cevabı sadece bellekte olursa, yeniden başlatmada çift pozisyon veya sahipsiz stop
emri kalır. Bu defter her olayı JSONL olarak diske yazar (idempotent `olay_id`),
borsadan gelen pozisyonlarla karşılaştırılır ve fark varsa **yeni işlem açmaz**,
önce uzlaştırır.
"""
from __future__ import annotations

import json
import os
import time
import uuid


class Defter:
    def __init__(self, yol: str) -> None:
        self.yol = yol
        os.makedirs(os.path.dirname(os.path.abspath(yol)), exist_ok=True)
        self._gorulen: set[str] = set()
        self._yukle()

    def _yukle(self) -> None:
        if not os.path.exists(self.yol):
            return
        with open(self.yol, encoding="utf-8") as fh:
            for satir in fh:
                try:
                    kayit = json.loads(satir)
                    self._gorulen.add(kayit.get("olay_id", ""))
                except Exception:
                    continue

    def yaz(self, tur: str, veri: dict, olay_id: str | None = None) -> str:
        oid = olay_id or str(uuid.uuid4())
        if oid in self._gorulen:
            return oid
        self._gorulen.add(oid)
        kayit = {"olay_id": oid, "ts": time.time(), "tur": tur, **veri}
        with open(self.yol, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(kayit, ensure_ascii=False, default=str) + "\n")
        return oid

    def olaylar(self) -> list[dict]:
        if not os.path.exists(self.yol):
            return []
        with open(self.yol, encoding="utf-8") as fh:
            return [json.loads(s) for s in fh if s.strip()]

    def acik_pozisyonlar(self) -> dict[str, dict]:
        acik: dict[str, dict] = {}
        for e in self.olaylar():
            if e.get("tur") == "GIRIS":
                acik[e["sembol"]] = e
            elif e.get("tur") in ("CIKIS", "STOP"):
                acik.pop(e.get("sembol", ""), None)
        return acik

    def uzlastir(self, borsa_pozisyonlari: dict[str, dict]) -> dict:
        """Bellekteki defter ile borsanın gerçeğini karşılaştırır.

        Dönen sözlük: {"defterde_var_borsada_yok": [...], "borsada_var_defterde_yok": [...]}
        İkinci liste boş değilse canlı modda işlem DURDURULUR, elle müdahale gerekir.
        """
        defter = set(self.acik_pozisyonlar())
        borsa = set(borsa_pozisyonlari)
        return {
            "defterde_var_borsada_yok": sorted(defter - borsa),
            "borsada_var_defterde_yok": sorted(borsa - defter),
            "uzlasik": defter == borsa,
        }
