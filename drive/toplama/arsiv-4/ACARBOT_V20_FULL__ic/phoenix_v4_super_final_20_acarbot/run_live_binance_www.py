"""ACARBOT V20 canli testini Binance www public rotasiyla calistirir.

Kullanim (paket kokunde):

    PHOENIX_BINANCE_PUBLIC_WWW=1 python -m run_live_binance_www \
        --duration 600 --poll 15 --detail-per-cycle 0 \
        --report live_10min_report.json

Ek olarak --paper / --live anahtarlari phoenix.live ile aynidir.
Read-only (varsayilan) modda hicbir emir gonderilmez.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("PHOENIX_BINANCE_PUBLIC_WWW", "1")

from binance_www_route import patch_phoenix  # noqa: E402
from phoenix.live import main  # noqa: E402


if __name__ == "__main__":
    n = patch_phoenix()
    print(f"[binance-www-route] PHOENIX_BINANCE_PUBLIC_WWW={os.environ.get('PHOENIX_BINANCE_PUBLIC_WWW')} patch={n}", flush=True)
    sys.argv[0] = "phoenix.live"
    main()
