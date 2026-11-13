#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""server.py — ACARBOT canlı panel (sadece standart kütüphane, bağımlılık yok).

    python3 panel/server.py --port 8000 --host 0.0.0.0

`runs/<etiket>/` altındaki durum.json / rapor.json / islem_jurnali.csv dosyalarını
okur, tarayıcıya JSON olarak verir. Koşu sürerken de açılır (dosya yarım olabilir,
okuyucu toleranslıdır).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(KOK, "runs")


def _oku(yol: str) -> dict | None:
    try:
        with open(yol, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _jurnal(yol: str, limit: int = 400) -> list[dict]:
    try:
        with open(yol, encoding="utf-8") as fh:
            satirlar = list(csv.DictReader(fh))
        return satirlar[-limit:]
    except Exception:
        return []


def kosular() -> list[dict]:
    if not os.path.isdir(RUNS):
        return []
    cikti = []
    for ad in sorted(os.listdir(RUNS)):
        d = os.path.join(RUNS, ad)
        if not os.path.isdir(d):
            continue
        durum = _oku(os.path.join(d, "durum.json"))
        rapor = _oku(os.path.join(d, "rapor.json"))
        if durum is None and rapor is None:
            continue
        cikti.append({
            "etiket": ad,
            "durum": durum,
            "rapor": rapor,
            "jurnal": _jurnal(os.path.join(d, "islem_jurnali.csv")),
            "guncelleme": os.path.getmtime(os.path.join(d, "durum.json"))
            if os.path.exists(os.path.join(d, "durum.json")) else 0,
            "bitti": bool(rapor),
        })
    return cikti


class Isleyici(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/durum"):
            veri = json.dumps({"kosular": kosular(), "sunucu_ts": time.time()},
                              ensure_ascii=False, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(veri)))
            self.end_headers()
            self.wfile.write(veri)
            return
        if self.path in ("/", "/index.html"):
            yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
            try:
                govde = open(yol, "rb").read()
            except OSError:
                govde = b"index.html bulunamadi"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(govde)))
            self.end_headers()
            self.wfile.write(govde)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, kalip, *args) -> None:  # sessiz
        return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    print(f"panel: http://{a.host}:{a.port}  (runs: {RUNS})", flush=True)
    ThreadingHTTPServer((a.host, a.port), Isleyici).serve_forever()
