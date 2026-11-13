"""Backward-compatible shim. The implementation lives in phoenix.binance_route (V20)."""
from phoenix.binance_route import *  # noqa: F401,F403
from phoenix.binance_route import apply_binance_www_route, patch_phoenix, PUBLIC_KEYS, FAPI_OLD, FAPI_NEW  # noqa: F401
