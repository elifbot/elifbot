#!/usr/bin/env python3
"""100.000 USDT ile 15 saatlik yerel paper Futures oturumu.

Başlat:
    python start_paper_15h.py --fresh

Aynı kasa/pozisyonlar ve kalan süreyle devam et:
    python start_paper_15h.py
"""
from start_paper_24h import main


if __name__ == "__main__":
    main(default_hours=15.0, default_db="paper_15h_state.db")
