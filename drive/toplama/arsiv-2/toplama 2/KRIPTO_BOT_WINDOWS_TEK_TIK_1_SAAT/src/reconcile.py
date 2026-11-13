"""Yerel pozisyonlar ile borsadaki gerçek pozisyonların güvenli mutabakatı."""
from __future__ import annotations


def norm_symbol(sym: str) -> str:
    """``BTC/USDT:USDT`` → ``BTC/USDT`` gösterimini normalleştirir."""
    return str(sym).split(":")[0].upper()


def reconcile_positions(local: dict, remote: list[dict], qty_tol_pct: float = 2.0) -> dict:
    """Pozisyonları sembol ve (biliniyorsa) borsa bazında karşılaştırır.

    Borsa bilgisi hem yerelde hem uzak kayıtlarda varsa sembol-only eşleştirme
    yapılmaz. Böylece Binance→OKX failover sonrasında Binance pozisyonu yanlışlıkla
    "hayalet" sanılıp silinmez. Eski/test kayıtlarındaki borsasız biçim desteklenir.
    """
    use_exchange = any(getattr(p, "exchange", "") for p in local.values()) and any(
        r.get("exchange") for r in remote
    )

    def local_key(symbol: str, pos) -> tuple[str, str]:
        exchange = str(getattr(pos, "exchange", "") or "").lower() if use_exchange else ""
        return exchange, norm_symbol(symbol)

    def remote_key(row: dict) -> tuple[str, str]:
        exchange = str(row.get("exchange", "") or "").lower() if use_exchange else ""
        return exchange, norm_symbol(row["symbol"])

    rem = {}
    for row in remote:
        qty = abs(float(row.get("qty") or 0))
        if qty <= 0:
            continue
        key = remote_key(row)
        rem[key] = {
            "side": str(row.get("side", "")).upper(),
            "qty": qty,
            "exchange": key[0],
        }

    loc = {local_key(symbol, pos): (symbol, pos) for symbol, pos in local.items()}
    ghosts, orphans, mismatches = [], [], []

    for key, (original_symbol, pos) in loc.items():
        if key not in rem:
            ghosts.append(
                {
                    "symbol": key[1],
                    "local_symbol": original_symbol,
                    "exchange": key[0],
                    "side": pos.side,
                    "qty": pos.qty,
                }
            )
            continue
        row = rem[key]
        if row["side"] and row["side"] != pos.side:
            mismatches.append(
                {
                    "symbol": key[1],
                    "local_symbol": original_symbol,
                    "exchange": key[0],
                    "neden": f"yön farkı (bot {pos.side}, borsa {row['side']})",
                }
            )
        elif pos.qty > 0 and abs(row["qty"] - pos.qty) / pos.qty * 100.0 > qty_tol_pct:
            mismatches.append(
                {
                    "symbol": key[1],
                    "local_symbol": original_symbol,
                    "exchange": key[0],
                    "neden": f"miktar farkı (bot {pos.qty:.6f}, borsa {row['qty']:.6f})",
                }
            )

    for key, row in rem.items():
        if key not in loc:
            orphans.append(
                {"symbol": key[1], "exchange": key[0], "side": row["side"], "qty": row["qty"]}
            )

    return {
        "ghosts": ghosts,
        "orphans": orphans,
        "mismatches": mismatches,
        "ok": not (ghosts or orphans or mismatches),
    }
