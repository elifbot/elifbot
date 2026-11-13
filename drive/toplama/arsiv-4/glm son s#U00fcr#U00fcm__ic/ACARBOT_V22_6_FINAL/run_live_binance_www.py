"""Compatibility launcher (V15 name). In V22 the Binance public WWW route is built into the adapter
(PHOENIX_BINANCE_PUBLIC_WWW = auto | 1 | 0), so this simply forces mode `1` and runs phoenix.live."""
import os
import sys

os.environ.setdefault("PHOENIX_BINANCE_PUBLIC_WWW", "1")

from phoenix.live import main  # noqa: E402

if __name__ == "__main__":
    sys.argv[0] = "phoenix.live"
    main()
