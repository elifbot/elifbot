"""Kripto Bot v9.0 — Kanonik Üretim Giriş Noktası (`python -m src.main`)."""
from __future__ import annotations

import asyncio
import sys

from src.live_runner import async_main


def main() -> None:
    asyncio.run(async_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
