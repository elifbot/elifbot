#!/usr/bin/env python3
"""v19 watchdog: ws_durum.json tazeligini izler; bayatsa alarm yazar, cikis kodu 2.
Kullanim: python3 scripts/watchdog.py [durum_json] [max_yas_sn]  (cron/systemd timer ile)"""
import json, sys, time
yol = sys.argv[1] if len(sys.argv) > 1 else "logs/ws_durum.json"
azami = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
try:
    d = json.load(open(yol, encoding="utf-8"))
except Exception as exc:
    print(f"ALARM durum okunamadi: {exc}"); raise SystemExit(2)
yas = time.time() - __import__("os").path.getmtime(yol)
if yas > azami or not d.get("calisiyor", False):
    print(f"ALARM bayat/calisiyor=False yas={yas:.0f}sn"); raise SystemExit(2)
print(f"OK yas={yas:.0f}sn sinyal={d.get('sinyal')} acik={d.get('acik_pozisyon')} pnl={d.get('toplam_pnl')}")
