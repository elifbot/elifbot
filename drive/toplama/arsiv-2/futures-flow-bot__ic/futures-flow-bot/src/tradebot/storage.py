from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Storage:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        create table if not exists trades(
            id integer primary key, opened_ts real, closed_ts real, exchange text, symbol text,
            side text, entry real, exit real, notional real, pnl_gross real, fees real, pnl_net real,
            reason text, entry_reasons text, exit_reasons text, score int, mode text);
        create table if not exists signals(
            id integer primary key, ts real, exchange text, symbol text, side text, score int,
            price real, reasons text, decision text);
        create table if not exists events(id integer primary key, ts real, kind text, detail text);
        """)

    def trade(self, r: dict, mode: str) -> None:
        self.db.execute(
            "insert into trades(opened_ts,closed_ts,exchange,symbol,side,entry,exit,notional,pnl_gross,"
            "fees,pnl_net,reason,entry_reasons,exit_reasons,score,mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["opened_ts"], r["closed_ts"], r["exchange"], r["symbol"], r["side"], r["entry"], r["exit"],
             r["notional"], r["pnl_gross"], r["fees"], r["pnl_net"], r["reason"],
             json.dumps(r.get("entry_reasons", []), ensure_ascii=False),
             json.dumps(r.get("exit_reasons", []), ensure_ascii=False), r.get("score", 0), mode))
        self.db.commit()

    def signal(self, ts, exchange, symbol, side, score, price, reasons, decision) -> None:
        self.db.execute("insert into signals(ts,exchange,symbol,side,score,price,reasons,decision) "
                        "values(?,?,?,?,?,?,?,?)",
                        (ts, exchange, symbol, side, score, price, json.dumps(reasons, ensure_ascii=False),
                         decision))
        self.db.commit()

    def event(self, kind: str, detail: str, ts: float | None = None) -> None:
        self.db.execute("insert into events(ts,kind,detail) values(?,?,?)", (ts or time.time(), kind, detail))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
