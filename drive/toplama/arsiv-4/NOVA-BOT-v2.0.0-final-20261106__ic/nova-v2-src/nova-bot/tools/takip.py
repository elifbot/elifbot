#!/usr/bin/env python3
"""NOVA-BOT koşu takibi: koşu klasörünü canlı okur, kısa durum özeti basar.

Kullanım: python3 tools/takip.py /home/user/runs/nova-live-2
Salt-okunur: SQLite'ı "immutable" açar, çalışan koşuya yazmaz.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/nova-live-2")
    db = out / "nova.sqlite"
    ev = out / "events.jsonl"

    started = None
    counts: dict[str, int] = {}
    last_ts = None
    if ev.exists():
        for line in ev.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_ts = d.get("ts")
            if d.get("kind") == "START":
                started = d["ts"]
            counts[d.get("kind", "?")] = counts.get(d.get("kind", "?"), 0) + 1

    print(f"koşu klasörü : {out}")
    print(f"başlangıç    : {started}")
    print(f"son olay     : {last_ts}")
    print(f"olay sayaçları: {dict(sorted(counts.items()))}")

    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            for t in ("bars", "signals", "trades", "equity"):
                try:
                    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    print(f"db {t:9s}: {n}")
                except sqlite3.Error as e:
                    print(f"db {t:9s}: okunamadı ({e})")
            try:
                rows = con.execute(
                    "SELECT market, symbol, side, entry, exit_px, net, reason "
                    "FROM trades ORDER BY closed_ms"
                ).fetchall()
                if rows:
                    print("\nkapanan işlemler (borsa, sembol, yön, giriş, çıkış, net, neden):")
                    for r in rows:
                        print("  ", r)
            except sqlite3.Error:
                pass
            # açık pozisyonlar: OPEN olaylarından CLOSE olaylarını düş
            opened: dict[str, dict] = {}
            if ev.exists():
                for line in ev.read_text(encoding="utf-8").splitlines():
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("kind") == "OPEN":
                        opened[str(d.get("key"))] = d
                    elif d.get("kind") == "CLOSE":
                        opened.pop(str(d.get("key")), None)
            if opened:
                print("\naçık pozisyonlar:")
                for k, d in opened.items():
                    print(f"   {k:32s} {d.get('side'):5s} giriş={d.get('entry')} "
                          f"stop={d.get('stop')} hedef={d.get('tp')} "
                          f"qty={d.get('qty')}")
            try:
                eq = con.execute("SELECT equity FROM equity ORDER BY ts_ms DESC LIMIT 1").fetchone()
                if eq:
                    print(f"\nson sermaye  : {eq[0]}")
            except sqlite3.Error:
                pass
        finally:
            con.close()

    if last_ts:
        try:
            t = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t).total_seconds()
            print(f"son olay yaşı: {age:.0f} sn")
        except ValueError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
