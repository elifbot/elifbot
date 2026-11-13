"""Pozisyon mutabakatı (reconciliation): bot hafızası/SQLite ile borsadaki GERÇEK pozisyonları karşılaştırır.

Neden gerekli: bot çöküp yeniden başladığında, WS koptuğunda veya emir timeout verdiğinde
yerel kayıt ile borsa durumu ayrışabilir ("hayalet pozisyon" veya sahipsiz pozisyon).
"""
from __future__ import annotations


def norm_symbol(sym: str) -> str:
    """'BTC/USDT:USDT' -> 'BTC/USDT' (vadeli/spot gösterim farkını giderir)."""
    return str(sym).split(":")[0].upper()


def reconcile_positions(local: dict, remote: list[dict], qty_tol_pct: float = 2.0) -> dict:
    """local: {symbol: Position}; remote: [{'symbol','side','qty'}]. Salt-okunur karşılaştırma yapar.

    Dönüş:
      ghosts     — botta var, borsada yok (stop/likidasyonla kapanmış olabilir)
      orphans    — borsada var, botta yok (bot yönetmiyor — KORUMASIZ olabilir)
      mismatches — var ama yön veya miktar farklı
    """
    rem = {}
    for r in remote:
        key = norm_symbol(r["symbol"])
        q = abs(float(r.get("qty") or 0))
        if q <= 0:
            continue
        rem[key] = {"side": str(r.get("side", "")).upper(), "qty": q}

    loc = {norm_symbol(s): p for s, p in local.items()}
    ghosts, orphans, mismatches = [], [], []

    for key, pos in loc.items():
        if key not in rem:
            ghosts.append({"symbol": key, "side": pos.side, "qty": pos.qty})
            continue
        r = rem[key]
        if r["side"] and r["side"] != pos.side:
            mismatches.append({"symbol": key, "neden": f"yön farkı (bot {pos.side}, borsa {r['side']})"})
        elif pos.qty > 0 and abs(r["qty"] - pos.qty) / pos.qty * 100.0 > qty_tol_pct:
            mismatches.append(
                {"symbol": key, "neden": f"miktar farkı (bot {pos.qty:.6f}, borsa {r['qty']:.6f})"}
            )
    for key, r in rem.items():
        if key not in loc:
            orphans.append({"symbol": key, "side": r["side"], "qty": r["qty"]})

    return {
        "ghosts": ghosts,
        "orphans": orphans,
        "mismatches": mismatches,
        "ok": not (ghosts or orphans or mismatches),
    }
