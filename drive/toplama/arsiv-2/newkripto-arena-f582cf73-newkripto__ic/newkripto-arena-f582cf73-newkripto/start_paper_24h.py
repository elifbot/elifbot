#!/usr/bin/env python3
"""Yerel bilgisayarda 100.000 USDT paper Futures oturumu başlatır.

Örnek:
    python start_paper_24h.py --fresh
    python start_paper_24h.py              # kalan süre ve açık pozisyonlarla devam

Gerçek emir göndermez. Binance/OKX genel piyasa verileri kullanılır.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from src.config import BASE_DIR


def parse_args(
    default_hours: float = 24.0,
    default_db: str = "paper_24h_state.db",
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Süreli yerel paper Futures botu")
    parser.add_argument(
        "--hours", type=float, default=default_hours,
        help=f"Oturum süresi (varsayılan: {default_hours:g})",
    )
    parser.add_argument(
        "--db", default=default_db, help="Kalıcı paper oturum veritabanı"
    )
    parser.add_argument(
        "--fresh", action="store_true", help="Eski oturumu yedekleyip 100.000 USDT ile yeniden başla"
    )
    args = parser.parse_args()
    if args.hours <= 0:
        parser.error("--hours sıfırdan büyük olmalı")
    return args


def archive_previous_session(db_path: Path) -> None:
    """--fresh için eski SQLite dosyalarını silmek yerine zaman damgalı yedekler."""
    candidates = [db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")]
    if not any(path.exists() for path in candidates):
        return
    backup_dir = BASE_DIR / "reports" / "session_backups" / time.strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in candidates:
        if path.exists():
            path.replace(backup_dir / path.name)
    print(f"🗄️ Önceki paper oturumu yedeklendi: {backup_dir}", flush=True)


def main(
    default_hours: float = 24.0,
    default_db: str = "paper_24h_state.db",
) -> None:
    args = parse_args(default_hours=default_hours, default_db=default_db)
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    if args.fresh:
        archive_previous_session(db_path)

    # Bu başlatıcı bilinçli olarak yalnız paper çalışır; canlı anahtarlar olsa bile
    # ExchangeManager create_order çağrıları PaperBroker'a yönlendirilir.
    os.environ["MODE"] = "paper"
    os.environ["PAPER_SESSION_HOURS"] = str(args.hours)
    os.environ["BOT_DB_FILE"] = str(db_path)

    from src.main import main as bot_main

    try:
        asyncio.run(bot_main())
    except KeyboardInterrupt:
        print("\n🛑 Yerel paper oturumu kullanıcı tarafından durduruldu.")


if __name__ == "__main__":
    main()
