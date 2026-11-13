"""Kripto Bot v8.0 — 15 Dakikalık Canlı Borsa Verisi (Binance + OKX) Test Başlatıcısı."""
from __future__ import annotations

import asyncio

from src.canli_15dk_runner import main

if __name__ == "__main__":
    asyncio.run(main())
