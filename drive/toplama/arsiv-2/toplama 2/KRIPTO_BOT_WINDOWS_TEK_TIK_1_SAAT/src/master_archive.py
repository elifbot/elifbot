"""Kalıcı işlem, oturum ve model arşivi (SQLite + taşınabilir JSON).

GitHub erişimi kesilse bile Arena çalışma alanında tüm geçmiş oturumları,
kapanan işlemleri ve aktif model konfigürasyonunu saklar.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time

BASE_DIR = Path(__file__).resolve().parent.parent


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _parse_gunluk_metrics(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("🕒"):
            out["header"] = s.lstrip("🕒 ").strip()
        elif "Başlangıç kasası:" in s:
            m = re.search(r"\$([\d,]+(?:\.\d+)?)", s)
            if m:
                out["start_balance"] = float(m.group(1).replace(",", ""))
        elif "Bitiş/anlık kasa:" in s:
            m = re.search(r"\$([\d,]+(?:\.\d+)?)", s)
            if m:
                out["end_balance"] = float(m.group(1).replace(",", ""))
        elif "NET OTURUM K/Z:" in s:
            m = re.search(r"\$([+-]?[\d,]+(?:\.\d+)?)", s)
            if m:
                out["net_pnl_usdt"] = float(m.group(1).replace(",", ""))
        elif "Açılan işlem:" in s:
            m_open = re.search(r"Açılan işlem:\s*(\d+)", s)
            m_close = re.search(r"Kapanan işlem:\s*(\d+)", s)
            m_wl = re.search(r"(\d+)\s*kâr\s*/\s*(\d+)\s*zarar", s)
            if m_open:
                out["opened_count"] = int(m_open.group(1))
            if m_close:
                out["closed_count"] = int(m_close.group(1))
            if m_wl:
                out["wins"] = int(m_wl.group(1))
                out["losses"] = int(m_wl.group(2))
        elif "Kazanma oranı:" in s:
            m = re.search(r"%([\d.]+)", s)
            if m:
                out["win_rate_pct"] = float(m.group(1))
    return out


def sync_master_archive(
    db_path: Path | None = None,
    json_path: Path | None = None,
) -> dict:
    analysis_dir = BASE_DIR / "analysis"
    backups_dir = BASE_DIR / "backups"
    paper_lab_dir = BASE_DIR / "paper-lab"
    backups_dir.mkdir(parents=True, exist_ok=True)
    paper_lab_dir.mkdir(parents=True, exist_ok=True)

    db_file = db_path or (backups_dir / "kriptobot_kalici_hafiza.db")
    json_file = json_path or (paper_lab_dir / "tum_islemler_ve_oturumlar.json")

    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            run_id TEXT PRIMARY KEY,
            header TEXT,
            start_balance REAL,
            end_balance REAL,
            net_pnl_usdt REAL,
            opened_count INTEGER,
            closed_count INTEGER,
            wins INTEGER,
            losses INTEGER,
            win_rate_pct REAL,
            has_full_report INTEGER,
            updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS trades (
            trade_uid TEXT PRIMARY KEY,
            run_id TEXT,
            position_id TEXT,
            symbol TEXT,
            side TEXT,
            exchange TEXT,
            entry_price REAL,
            exit_price REAL,
            qty REAL,
            leverage INTEGER,
            margin_usdt REAL,
            gross_pnl_usdt REAL,
            entry_fee_usdt REAL,
            exit_fee_usdt REAL,
            funding_usdt REAL,
            net_pnl_usdt REAL,
            mfe_usdt REAL,
            mae_usdt REAL,
            regime TEXT,
            tech_score REAL,
            flow_score REAL,
            combined_score REAL,
            rsi REAL,
            close_reason TEXT,
            cohort_type TEXT
        );
        CREATE TABLE IF NOT EXISTS model_snapshots (
            version TEXT PRIMARY KEY,
            saved_at REAL,
            config_yaml TEXT,
            control_json TEXT,
            notes TEXT
        );
        """
    )

    sessions_export: list[dict] = []
    trades_export: list[dict] = []

    run_dirs = sorted(
        analysis_dir.glob("run_*"),
        key=lambda p: int(p.name.split("_")[1]) if p.name.split("_")[1].isdigit() else 0,
    )
    now_ts = time.time()

    for rdir in run_dirs:
        run_id = rdir.name.replace("run_", "")
        gunluk_path = rdir / "gunluk.txt"
        partial_path = rdir / "partial-gunluk.txt"
        metrics: dict = {}
        has_full = 0
        if gunluk_path.exists():
            metrics = _parse_gunluk_metrics(
                gunluk_path.read_text(encoding="utf-8", errors="replace")
            )
            has_full = 1
        elif partial_path.exists():
            metrics = _parse_gunluk_metrics(
                partial_path.read_text(encoding="utf-8", errors="replace")
            )

        session_row = {
            "run_id": run_id,
            "header": metrics.get("header", ""),
            "start_balance": _safe_float(metrics.get("start_balance")),
            "end_balance": _safe_float(metrics.get("end_balance")),
            "net_pnl_usdt": _safe_float(metrics.get("net_pnl_usdt")),
            "opened_count": int(metrics.get("opened_count") or 0),
            "closed_count": int(metrics.get("closed_count") or 0),
            "wins": int(metrics.get("wins") or 0),
            "losses": int(metrics.get("losses") or 0),
            "win_rate_pct": _safe_float(metrics.get("win_rate_pct")),
            "has_full_report": has_full,
        }
        if has_full or session_row["closed_count"] > 0:
            sessions_export.append(session_row)
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    run_id, header, start_balance, end_balance, net_pnl_usdt,
                    opened_count, closed_count, wins, losses, win_rate_pct,
                    has_full_report, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_row["header"],
                    session_row["start_balance"],
                    session_row["end_balance"],
                    session_row["net_pnl_usdt"],
                    session_row["opened_count"],
                    session_row["closed_count"],
                    session_row["wins"],
                    session_row["losses"],
                    session_row["win_rate_pct"],
                    has_full,
                    now_ts,
                ),
            )

        islem_path = rdir / "islem_gecmisi.json"
        cohort_path = rdir / "cohort-report.json"
        raw_trades: list[tuple[dict, str]] = []
        if islem_path.exists():
            loaded = json.loads(islem_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded = loaded.get("trades") or loaded.get("closed_trades") or []
            raw_trades = [(t, "full_history") for t in loaded]
        elif cohort_path.exists():
            cd = json.loads(cohort_path.read_text(encoding="utf-8"))
            for t in cd.get("bot_closed_trades") or []:
                raw_trades.append((t, "bot_closed"))
            for t in cd.get("manual_entries") or []:
                raw_trades.append((t, "session_end_entry"))

        for idx, (t, ctype) in enumerate(raw_trades, 1):
            ctx = t.get("entry_context")
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except Exception:
                    ctx = {}
            ctx = ctx or {}
            ind = ctx.get("indicators") or {}
            comb = ctx.get("combined") or {}
            of = ctx.get("orderflow") or {}
            pos_id = str(t.get("position_id") or f"{run_id}-{idx}")
            trade_uid = f"{run_id}:{pos_id}:{idx}"
            t_row = {
                "trade_uid": trade_uid,
                "run_id": run_id,
                "position_id": pos_id,
                "symbol": str(t.get("symbol") or ""),
                "side": str(t.get("side") or ""),
                "exchange": str(t.get("exchange") or ""),
                "entry_price": _safe_float(t.get("entry") or t.get("entry_price")),
                "exit_price": _safe_float(t.get("exit_price")),
                "qty": _safe_float(t.get("qty")),
                "leverage": int(_safe_float(t.get("leverage"), 10)),
                "margin_usdt": _safe_float(t.get("margin_usdt"), 50.0),
                "gross_pnl_usdt": _safe_float(t.get("pnl_usdt") or t.get("gross_pnl_usdt")),
                "entry_fee_usdt": _safe_float(t.get("entry_fee_usdt")),
                "exit_fee_usdt": _safe_float(t.get("exit_fee_usdt")),
                "funding_usdt": _safe_float(t.get("funding_usdt")),
                "net_pnl_usdt": _safe_float(t.get("net_pnl_usdt")),
                "mfe_usdt": _safe_float(t.get("mfe_usdt")),
                "mae_usdt": _safe_float(t.get("mae_usdt")),
                "regime": str(ind.get("regime") or t.get("regime") or ""),
                "tech_score": _safe_float(ind.get("score")),
                "flow_score": _safe_float(of.get("score")),
                "combined_score": _safe_float(comb.get("total") or t.get("score")),
                "rsi": _safe_float(ind.get("rsi")),
                "close_reason": str(t.get("reason") or t.get("close_reason") or ""),
                "cohort_type": ctype,
            }
            trades_export.append(t_row)
            conn.execute(
                """
                INSERT OR REPLACE INTO trades (
                    trade_uid, run_id, position_id, symbol, side, exchange,
                    entry_price, exit_price, qty, leverage, margin_usdt,
                    gross_pnl_usdt, entry_fee_usdt, exit_fee_usdt, funding_usdt,
                    net_pnl_usdt, mfe_usdt, mae_usdt, regime, tech_score,
                    flow_score, combined_score, rsi, close_reason, cohort_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(t_row.values()),
            )

    cfg_yaml = (BASE_DIR / "config.yaml").read_text(encoding="utf-8")
    ctrl_json = (BASE_DIR / "configs" / "paper-60-v2-control.json").read_text(
        encoding="utf-8"
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO model_snapshots (
            version, saved_at, config_yaml, control_json, notes
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "v7.6",
            now_ts,
            cfg_yaml,
            ctrl_json,
            "KRIPTO-BOT v7.6: %100 Saf Kripto + Capraz Ortak Kasa + Anlik WS Para Akisi + Canli Technical-Harmony & Range Kalkani + 2 Kademeli Net Kar Kilidi (+0.50%->+0.12%) + Erken Panik Cikisi KAPALI",
        ),
    )
    conn.commit()
    conn.close()

    payload = {
        "model_version": "KRIPTO-BOT v7.6",
        "exported_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts)),
        "session_count": len(sessions_export),
        "trade_count": len(trades_export),
        "sessions": sessions_export,
        "trades": trades_export,
    }
    json_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "db_path": str(db_file),
        "json_path": str(json_file),
        "sessions": len(sessions_export),
        "trades": len(trades_export),
    }


if __name__ == "__main__":
    summary = sync_master_archive()
    print(json.dumps(summary, ensure_ascii=False))
