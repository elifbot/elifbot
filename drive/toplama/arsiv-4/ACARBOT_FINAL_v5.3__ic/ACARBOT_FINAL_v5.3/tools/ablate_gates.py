"""v5.2 — ABLASYON: kapıyı gevşetince sonuç İYİLEŞİYOR mu, KÖTÜLEŞİYOR mu?

NEDEN ABLASYON?
---------------
`dusuk_hacim` gibi filtreler sinyal OLUŞMADAN reddeder — ortada yön ve
stop yoktur, dolayısıyla "bu işlemi açsaydık ne olurdu?" sorusu
tanımsızdır. Tek dürüst yöntem: eşiği değiştirip aynı veride yeniden
koşmak ve sonucu karşılaştırmak.

Karşılaştırma AYNI veri, AYNA motor, AYNI maliyet modeliyle yapılır.
Tek değişken ilgili eşiktir.

KULLANIM
--------
    python3 -m tools.ablate_gates --days 90 --out docs/ablasyon_v5.2.json
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import replace
from pathlib import Path

from backtest.costs import CostModel
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics
from tools.gate_attribution import _load_cached_or_fetch
from tools.validate_strategy import (
    DEFAULT_SYMBOLS, _profile_config, json_safe,
)

logger = logging.getLogger("ablate_gates")


def _variants(config):
    """(ad, açıklama, config) üçlüleri. İlki TEMEL (değişiklik yok)."""
    yield "TEMEL", "v5.2 varsayılanları — tüm kapılar açık", config

    # 1) MALİYET KAPISI: canlıda 13 giriş reddetti
    yield "MALIYET_KAPISI_KAPALI", (
        "Sert maliyet eşiği 0,60 → 0,999; yumuşak 0,35 → 0,99. "
        "Maliyet artık giriş engellemiyor."
    ), replace(config, risk_scaling=replace(
        config.risk_scaling,
        hard_cost_fraction_of_risk=0.999,
        max_cost_fraction_of_risk=0.99,
    ))

    # 2) HACİM KAPISI: barların %81-85'ini reddediyor
    for rvol in (1.0, 0.5):
        yield f"HACIM_RVOL_{rvol}", (
            f"min_rvol_for_entry 1,5 → {rvol}; canlı hacim tabanı "
            f"5,0 → 1,0 USDT/sn. Daha çok sinyal oluşur."
        ), replace(config, signal=replace(
            config.signal,
            min_rvol_for_entry=rvol,
            spike_min_baseline_notional_per_second=1.0,
        ))

    # 3) MAKER DOLUM: emirlerin %83'ü dolmadan süresi doluyor
    yield "MAKER_TTL_300", (
        "order_ttl_seconds 45 → 300 sn. Emir 5 dk bekler."
    ), replace(config, exit=replace(config.exit, order_ttl_seconds=300.0))

    # 4) R:R ASİMETRİSİ: ort kazanç +1,63 / ort kayıp −8,70
    yield "RR_TP1_2R", (
        "tp1_r_multiple 1,0 → 2,0. İlk kâr alma 2R'de."
    ), replace(config, exit=replace(config.exit, tp1_r_multiple=2.0))

    yield "RR_STOP_DAR", (
        "stop_atr_multiple 1,5 → 0,75. Stop yarıya iner; R:R düzelir "
        "ama stop-out sıklığı artar."
    ), replace(config, exit=replace(config.exit, stop_atr_multiple=0.75))

    # R:R kök nedeni: trailing 0,75R'de aktifleşiyor ama 2 ATR (=1,33R)
    # geriden geliyor. TP1 (1,0R) hiç tetiklenmedi.
    yield "RR_TP1_ERKEN", (
        "tp1_r_multiple 1,0 → 0,5. Kazananların hiçbiri 1R'ye ulaşmadı; "
        "yarım pozisyonu daha erken realize et."
    ), replace(config, exit=replace(config.exit, tp1_r_multiple=0.5))

    yield "RR_TRAIL_GEC", (
        "trail_activation_r 0,75 → 1,5. Kazananı erken kesmeyi bırak; "
        "TP1'in tetiklenmesine izin ver."
    ), replace(config, exit=replace(config.exit, trail_activation_r=1.5))

    yield "RR_TRAIL_DAR", (
        "trail_atr_multiple 2,0 → 0,75. Takip mesafesi stopun yarısı; "
        "kârı geri vermek yerine kilitle."
    ), replace(config, exit=replace(config.exit, trail_atr_multiple=0.75))

    yield "RR_BREAKEVEN_ERKEN", (
        "breakeven_activation_r 1,0 → 0,4. Kazananı sıfırın üstünde tut."
    ), replace(config, exit=replace(config.exit, breakeven_activation_r=0.4))

    yield "RR_KOMBINE", (
        "TP1 0,5R + trail aktivasyon 1,5R + trail mesafe 0,75 ATR + "
        "breakeven 0,4R. Kazananı kesme, kaybı sınırla."
    ), replace(config, exit=replace(
        config.exit, tp1_r_multiple=0.5, trail_activation_r=1.5,
        trail_atr_multiple=0.75, breakeven_activation_r=0.4,
    ))

    # 5) DRAWDOWN KORUMASI: 90 günde 1012 giriş reddetti
    yield "DD_KORUMASI_KAPALI", (
        "Portföy drawdown koruması kapatılır. Örneklem kesilmesi "
        "ortadan kalkar; kayıp sınırsız koşabilir."
    ), replace(config, portfolio=replace(
        config.portfolio, portfolio_drawdown_pct=100.0,
    ))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exchange", default="okx")
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--profile", default="apex")
    ap.add_argument("--balance", type=float, default=1_000.0)
    ap.add_argument("--costs", default="docs/maliyet_olcum_v5.2.json")
    ap.add_argument("--data-dir", default="data/validation")
    ap.add_argument("--only", default=None, help="virgülle varyant adları")
    ap.add_argument("--pause", type=float, default=0.15)
    ap.add_argument("--out", default="docs/ablasyon_v5.2.json")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    keys = [f"{args.exchange}:{s.strip()}" for s in args.symbols.split(",") if s.strip()]
    bars = args.days * 24 * 12
    candles = {}
    for key in keys:
        rows = _load_cached_or_fetch(args.exchange, key, bars, data_dir, args.pause)
        if rows:
            candles[key] = rows[-bars:] if len(rows) > bars else rows
    if not candles:
        logger.error("Veri yok")
        return 1

    base = _profile_config(args.profile, None)
    costs = CostModel.load(args.costs) if args.costs else None
    only = set(args.only.split(",")) if args.only else None

    results = []
    baseline_net = None
    for name, desc, cfg in _variants(base):
        if only and name not in only and name != "TEMEL":
            continue
        logger.info(">>> %s", name)
        engine = BacktestEngine(cfg, initial_balance=args.balance)
        res = engine.run(candles, cost_model=costs)
        m = compute_metrics(
            list(res.trades), args.balance, res.final_balance, res.equity_curve,
        ).as_dict()
        net = round(res.net_pnl, 4)
        if name == "TEMEL":
            baseline_net = net
        row = {
            "varyant": name, "aciklama": desc,
            "net_pnl": net,
            "islem": res.trade_count,
            "kazanma_orani": round(m.get("win_rate", 0.0), 4),
            "profit_factor": round(m.get("profit_factor", 0.0), 4),
            "ort_kazanc": round(m.get("avg_win", 0.0), 4),
            "ort_kayip": round(m.get("avg_loss", 0.0), 4),
            "max_dd_usdt": round(m.get("max_drawdown_usdt", 0.0), 4),
            "ucret": round(m.get("total_fees", 0.0), 4),
            "kayma": round(m.get("total_slippage", 0.0), 4),
            "redler": dict(sorted(
                res.rejection_counts.items(), key=lambda kv: -kv[1],
            )[:10]),
        }
        if baseline_net is not None and name != "TEMEL":
            row["temele_gore_fark"] = round(net - baseline_net, 4)
            row["hukum"] = (
                "KAPI ZARARLI — gevşetmek İYİLEŞTİRDİ" if net > baseline_net
                else "KAPI FAYDALI — gevşetmek KÖTÜLEŞTİRDİ"
            )
        results.append(row)
        logger.info("    net=%.4f işlem=%d kazanma=%.3f",
                    net, res.trade_count, m.get("win_rate", 0.0))
        # bellek: her koşudan sonra equity eğrisini atma
        del res, engine

    report = {
        "surum": __import__("app").__version__,
        "veri": {"borsa": args.exchange, "sembol": len(candles),
                 "gun": args.days, "bar": sum(len(v) for v in candles.values())},
        "yontem": (
            "Aynı veri, aynı motor, aynı ölçülmüş maliyet. Tek değişken "
            "ilgili eşik. Mum içi yol 5m (tüm varyantlarda aynı) — "
            "karşılaştırma geçerli, mutlak değer 1m doğrulamasından farklı."
        ),
        "sonuclar": results,
        "acik_sinir": (
            "Drawdown koruması kapatılan varyant örneklem kesilmesini "
            "ortadan kaldırır ama gerçek portföyde bu koruma olmadan "
            "çalışılmaz. Sonuçlar 'kapı ne yapıyor' sorusunu cevaplar, "
            "'bu ayarla çalışalım' önerisi DEĞİLDİR."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print("\n=== ABLASYON ===")
    print(f"{'varyant':26s} {'net':>10s} {'işlem':>6s} {'kazanma':>8s} {'fark':>10s}")
    for r in results:
        print(f"{r['varyant']:26s} {r['net_pnl']:10.2f} {r['islem']:6d} "
              f"{r['kazanma_orani']*100:7.1f}% "
              f"{r.get('temele_gore_fark', 0.0):10.2f}")
    print("\nYazıldı:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
