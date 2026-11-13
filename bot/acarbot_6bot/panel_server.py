# -*- coding: utf-8 -*-
"""panel_server.py - 4 bot canli test paneli icin minik HTTP sunucu.

  /        -> panel/index.html (izleme ekrani)
  /durum   -> logs/durum_<etiket>.json (canli durum)
  /rapor   -> logs/rapor_<etiket>.json (varsa)

Kullanim:
    python panel_server.py --port 8000 --etiket kosu
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KOK = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(KOK, "panel", "index.html")
LOG_DIR = os.path.join(KOK, "logs")
ETIKET = "kosu"


class Isleyici(BaseHTTPRequestHandler):
    server_version = "AcarbotPanel/1.0"

    def log_message(self, *a):  # sessiz
        return

    def _gonder(self, kod, govde: bytes, tip="application/json; charset=utf-8"):
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(govde)

    def do_GET(self):
        yol = self.path.split("?")[0]
        if yol in ("/", "/index.html", "/panel"):
            try:
                with open(PANEL, "rb") as fh:
                    self._gonder(200, fh.read(), "text/html; charset=utf-8")
            except OSError:
                self._gonder(500, b"panel/index.html yok",
                             "text/plain; charset=utf-8")
            return

        if yol in ("/durum", "/rapor"):
            onek = "durum" if yol == "/durum" else "rapor"
            dosya = os.path.join(LOG_DIR, f"{onek}_{ETIKET}.json")
            if not os.path.exists(dosya):
                self._gonder(200, json.dumps(
                    {"hazir": False, "beklenen": dosya}).encode(), "application/json")
                return
            try:
                with open(dosya, "rb") as fh:
                    self._gonder(200, fh.read())
            except OSError as exc:
                self._gonder(500, str(exc).encode(), "text/plain; charset=utf-8")
            return

        if yol == "/saglik":
            self._gonder(200, b'{"ok": true}')
            return

        self._gonder(404, b'{"hata": "yol yok"}')


def main():
    global ETIKET
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--etiket", default="kosu")
    a = ap.parse_args()
    ETIKET = a.etiket
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Isleyici)
    print(f"panel hazir: http://0.0.0.0:{a.port}  (etiket={ETIKET})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
