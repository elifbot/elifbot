#!/usr/bin/env python3
"""GitLab bir saatlik paper job'unun kabul koşullarını doğrular."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_meta(conn: sqlite3.Connection, key: str) -> dict:
    row = conn.execute("SELECT value FROM bot_meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row[0])
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", default="gitlab_artifacts/kabul_ozeti.json")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    checks: dict[str, bool] = {"db_exists": db_path.exists()}
    details: dict[str, object] = {"db": str(db_path), "checked_at": time.time()}
    if not db_path.exists():
        result = {"accepted": False, "checks": checks, "details": details}
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    with sqlite3.connect(db_path) as conn:
        session = load_meta(conn, "paper_24h_session")
        bot_status = load_meta(conn, "bot_status")
        open_positions = int(conn.execute("SELECT COUNT(*) FROM open_positions").fetchone()[0])
        closed_trades = int(conn.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0])

    last_exit_path = ROOT / "reports" / "last_exit.json"
    try:
        last_exit = json.loads(last_exit_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        last_exit = {}

    start_ts = float(session.get("start_ts") or 0.0)
    end_ts = float(session.get("end_ts") or 0.0)
    closed_at = float(session.get("closed_at") or 0.0)
    elapsed = closed_at - start_ts if closed_at and start_ts else 0.0
    report_file = Path(str(session.get("report_file") or ""))
    analysis_file = Path(str(session.get("analysis_file") or ""))
    trades_file = Path(str(session.get("trades_file") or ""))

    checks.update(
        {
            "session_exists": bool(session),
            "configured_one_hour": abs(float(session.get("hours") or 0.0) - 1.0) < 1e-9,
            "scheduled_duration_elapsed": elapsed >= 3590.0,
            "closed_at_or_after_end": closed_at >= end_ts - 5.0 if end_ts else False,
            "closeout_completed": bool(session.get("closeout_completed")),
            "report_saved": bool(session.get("report_sent")),
            "open_positions_zero": open_positions == 0,
            "planned_exit_recorded": last_exit.get("value") == "scheduled_paper_session_complete",
            "report_file_exists": report_file.is_file(),
            "analysis_file_exists": analysis_file.is_file(),
            "trades_file_exists": trades_file.is_file(),
            "paper_mode": str(bot_status.get("mode") or "").upper() == "PAPER",
        }
    )
    details.update(
        {
            "session": session,
            "last_exit": last_exit,
            "open_positions": open_positions,
            "closed_trades": closed_trades,
            "elapsed_seconds": elapsed,
            "notifications_required": False,
        }
    )
    accepted = all(checks.values())
    result = {"accepted": accepted, "checks": checks, "details": details}
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
