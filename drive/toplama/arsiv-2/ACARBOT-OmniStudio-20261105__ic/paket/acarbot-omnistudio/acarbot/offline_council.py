"""OLCUM_DOGRULAMA.md'nin ürettiği sayıları okuyup OmniStudio konseyini
gerçek kamu verisiyle çalıştırır (anahtar yok → RULE_BASED_QUANT).

Amaç: maildeki botun "akış/genişlik/15dk bilinmiyor, varsayılan sıfır nötr"
bıraktığı üç boyutu ÖLÇÜLMÜŞ değerlerle değiştirip aynı konseyden geçirmek ve
kararın bu üç boyuta ne kadar duyarlı olduğunu göstermek.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp

from omnistudio.ai.council import AICouncil
from omnistudio.core.types import Side, Signal


def build_signal(row: dict, side: str, now_ms: int) -> Signal:
    return Signal(
        exchange=row["market"], symbol=row["symbol"], side=Side(side),
        price=float(row["price"]), ts_ms=now_ms,
        ret_pct=float(row.get("ctx_ret_pct") or 0.0),
        rvol=float(row.get("volume_ratio") or 1.0),
        volume_usd=float(row.get("quote_volume") or 0.0),
        window_ms=300_000,
        ctx_ret=float(row.get("ctx_ret_pct") or 0.0),
        ctx_vratio3=float(row.get("volume_ratio") or 1.0),
        signal_id=f"offline-{row['market']}-{row['symbol']}-{now_ms}",
        tag="offline-ölçüm",
    )


def metrics_from_measure(row: dict, side: str, funding_rate: float | None,
                         flow_pressure: float | None) -> dict:
    spread = float(row["spread_bps"])
    cost = row["cost"]
    metrics = {
        "entry_side": side,
        "spread_bps": spread,
        "roundtrip_cost_bps": cost["total"],
        "expected_move_bps": float(row["expected_move_bps"]),
        "atr_pct": float(row["atr_pct"]),
        "choppiness": float(row["choppiness"]),
        "funding_rate": funding_rate if funding_rate is not None else 0.0,
        "minutes_to_funding": float(row["minutes_to_funding"]),
        "extension_atr": float(row["extension_atr"]),
        # --- maildeki botun ÖLÇMEDİĞİ üç boyut ---
        "mtf_aligned": bool(row["mtf"]["aligned"]) if row["mtf"].get("available") else True,
        "breadth_ratio": float(row["breadth"].get("ratio") or 0.5),
        # flow_score, -1..1 baskı; LONG için pozitif iyi
        "flow_score": float(flow_pressure or 0.0),
    }
    return metrics


async def run(measure_dir: Path, out_dir: Path, top: int) -> dict:
    data = json.loads((measure_dir / "measure.json").read_text(encoding="utf-8"))
    rows = [r for r in data["results"] if r.get("signal_at_close")]
    rows.sort(key=lambda r: -float(r.get("expected_move_bps") or 0))
    picked = rows[:top]
    council = AICouncil()
    out_dir.mkdir(parents=True, exist_ok=True)
    now = int(time.time() * 1000)
    results = []
    async with aiohttp.ClientSession() as session:
        for row in picked:
            side = row["signal_at_close"]
            for label, measured in (("ÖLÇÜLMÜŞ", True), ("MAİLDEKİ-VARSAYIM", False)):
                if measured:
                    metrics = metrics_from_measure(
                        row, side, row.get("funding_rate"), row.get("flow_pressure"))
                else:
                    # Maildeki davranış: akış=0, genişlik=0, mtf=False
                    metrics = metrics_from_measure(row, side, None, None)
                    metrics.update({"flow_score": 0.0, "breadth_ratio": 0.0,
                                    "mtf_aligned": False})
                sig = build_signal(row, side, now)
                verdict = await council.evaluate(sig, metrics, session)
                results.append({
                    "market": row["market"], "symbol": row["symbol"], "side": side,
                    "mode": label, "approved": verdict.approved,
                    "score": round(verdict.score, 2),
                    "reject_code": verdict.reject_code,
                    "reason": verdict.reason,
                    "flaws": verdict.flaws[:6],
                    "metrics": {k: metrics[k] for k in
                                ("mtf_aligned", "breadth_ratio", "flow_score",
                                 "roundtrip_cost_bps", "expected_move_bps",
                                 "spread_bps", "choppiness")},
                })
    summary = {
        "council_mode": council.mode,
        "evaluated": len(picked),
        "measured_approved": sum(1 for r in results if r["mode"] == "ÖLÇÜLMÜŞ" and r["approved"]),
        "assumed_approved": sum(1 for r in results if r["mode"] == "MAİLDEKİ-VARSAYIM" and r["approved"]),
        "decisions_differ": sum(
            1 for a, b in zip(results[0::2], results[1::2]) if a["approved"] != b["approved"]),
        "note": ("Adaylar `signal_at_close` ile üretildi: strateji kararı mumun "
                 "kapanış anındaki veriyle verilmiş gibi hesaplandı (geçmiş karar), "
                 "akış/funding/makas bağlamı ise ölçüm anındaki gerçek değerlerdir. "
                 "Konsey anahtarsız RULE_BASED_QUANT modunda çalıştı; bu bir YZ "
                 "onayı değildir. Karşılaştırma yalnız, maildeki botun ÖLÇMEDİĞİ üç "
                 "boyutun kararı değiştirip değiştirmediğini gösterir."),
        "results": results,
    }
    (out_dir / "konsey.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    s = asyncio.run(run(Path(a.measure), Path(a.out), a.top))
    print(json.dumps({k: v for k, v in s.items() if k != "results"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
