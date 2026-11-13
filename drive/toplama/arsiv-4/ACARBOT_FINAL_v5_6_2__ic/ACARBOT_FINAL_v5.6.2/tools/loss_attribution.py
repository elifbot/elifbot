"""ZARAR ATFI — para tam olarak nereye gidiyor?

Sorulan soru
------------
"Zarar var" demek yetmez. Zararın KAÇI maliyet, KAÇI ters fiyat
hareketi, KAÇI çıkış asimetrisi? Üçü farklı iş gerektirir:

  * Maliyet baskınsa  → zaman dilimi / stop genişliği / maker oranı
  * Ters hareket      → giriş kenarı yok
  * Çıkış asimetrisi  → çıkış geometrisi (kazananı erken kesiyor)

Yöntem
------
1. Aynı veriyle İKİ koşu: gerçek çıkış geometrisi ve MALİYETSİZ
   karşılaştırma. Fark = doğrudan maliyet.
2. İşlem kayıtlarından brüt/net ayrıştırması: komisyon, kayma, funding.
3. Kazanç/kayıp asimetrisi: ortalama kazanç R vs ortalama kayıp R.
   Simetrik ±1R çıkışta beklenti ne olurdu? (kazanma oranı aynı kalsın)
4. Motor / sembol / yön / rejim kırılımı.
5. Yapısal oran: maliyet / stop mesafesi.

DÜRÜSTLÜK
---------- funding oranları iletilmezse funding ~0 çıkar; bu
"funding önemsiz" demek DEĞİL, ÖLÇÜLMEDİ demektir ve raporda yazılır.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Zarar bileşenlerine ayrıştırma")
    p.add_argument("--exchange", default="okx")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--symbols", default="BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP,"
                                       "XRP-USDT-SWAP,DOGE-USDT-SWAP,ADA-USDT-SWAP")
    p.add_argument("--profile", default="apex")
    p.add_argument("--balance", type=float, default=1_000.0)
    p.add_argument("--costs", default="docs/maliyet_olcum_v5.2.json")
    p.add_argument("--data-dir", default="data/validation")
    p.add_argument("--drawdown-peak-mode", default="rolling",
                   choices=["all_time", "rolling", "daily"])
    p.add_argument("--drawdown-peak-days", type=int, default=7)
    p.add_argument("--out", default="docs/zarar_atfi.json")
    return p


def _decompose(trades: list[dict], r_base: float) -> dict:
    """Kapanan işlemlerden brüt/net bileşenleri."""
    closes = [t for t in trades if t.get("type") == "CLOSE"]
    if not closes:
        return {"islem": 0}
    # Gerçek CLOSE şeması: entry_fee + fee, funding_paid, gross_pnl
    fees = sum(float(t.get("entry_fee") or 0.0) + float(t.get("fee") or 0.0)
               for t in closes)
    slip = sum(float(t.get("slippage") or 0.0) for t in closes)
    fund = sum(float(t.get("funding_paid") or 0.0) for t in closes)
    net = sum(float(t.get("pnl") or 0.0) for t in closes)
    gross_rec = sum(float(t.get("gross_pnl") or 0.0) for t in closes)
    wins = [t for t in closes if float(t.get("pnl") or 0) > 0]
    losses = [t for t in closes if float(t.get("pnl") or 0) <= 0]
    avg_win = sum(float(t["pnl"]) for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(float(t["pnl"]) for t in losses) / len(losses) if losses else 0.0
    wr = len(wins) / len(closes)
    # MUHASEBE DÜZELTMESİ (v5.5):
    #   net = gross_realized + tp1_realized - entry_fee - exit_fee - funding
    #   * `gross_pnl` alanı YALNIZ kalan miktarın brütü; TP1 kârını
    #     İÇERMEZ. Bu yüzden brüt olarak KULLANILMAZ.
    #   * `slippage` ayrı bir kesinti DEĞİL; kötü dolum fiyatı zaten
    #     gross_realized'in içindedir. Net'ten ayrıca düşmek ÇİFT SAYIM
    #     olurdu. Burada "tetik fiyatındaki hareket"e geri eklenir.
    #   * funding_paid pozitifse pozisyon ÖDER; net'ten düşülmüştür,
    #     brüte GERİ EKLENİR (+fund).
    gross = net + fees + slip + fund
    return {
        "islem": len(closes),
        "net_pnl": round(net, 4),
        "brut_pnl": round(gross, 4),
        "brut_kaynagi": "net + komisyon + kayma + funding (yeniden kurulum)",
        "gross_pnl_alani_toplami": round(gross_rec, 4),
        "gross_pnl_alani_uyarisi": (
            "Bu alan TP1 kısmi kârını İÇERMEZ; brüt olarak kullanılmaz."
        ),
        "komisyon": round(fees, 4),
        "kayma": round(slip, 4),
        "funding": round(fund, 4),
        "dogrudan_maliyet": round(fees + slip, 4),
        "kazanma_orani": round(wr, 4),
        "ort_kazanc": round(avg_win, 4),
        "ort_kayip": round(avg_loss, 4),
        "odeme_orani": round(abs(avg_win / avg_loss), 4) if avg_loss else None,
        "r_taban_usdt": round(r_base, 4),
        "net_r": round(net / len(closes) / r_base, 4) if r_base else None,
        "brut_r": round(gross / len(closes) / r_base, 4) if r_base else None,
        "maliyet_r": round((fees + slip) / len(closes) / r_base, 4) if r_base else None,
    }


def _counterfactual(d: dict) -> dict:
    """Aynı kazanma oranıyla SİMETRİK ±1R çıkış ne verirdi?

    Gerçek çıkış kazananı küçük R'de kesiyor, kaybedeni tam stopa
    bırakıyorsa ödeme oranı 1'in çok altında olur. Simetrik çıkışta
    ödeme oranı 1'dir. Fark = çıkış geometrisinin katkısı.
    """
    wr = d.get("kazanma_orani")
    if wr is None or not d.get("r_taban_usdt"):
        return {}
    sym_gross_r = wr * 1.0 + (1 - wr) * (-1.0)
    cost_r = d.get("maliyet_r") or 0.0
    return {
        "gercek_brut_r": d.get("brut_r"),
        "simetrik_brut_r": round(sym_gross_r, 4),
        "cikis_geometrisi_katkisi_r": round(
            (d.get("brut_r") or 0.0) - sym_gross_r, 4),
        "simetrik_net_r": round(sym_gross_r - cost_r, 4),
        "gercek_net_r": d.get("net_r"),
        "yorum": (
            "Çıkış geometrisi katkisi NEGATİFSE, gerçek çıkış simetrik "
            "±1R'den daha kötüdür: kazananı erken kesiyor veya kaybedeni "
            "fazla bekletiyor. POZİTİFSE çıkış işe yarıyor."
        ),
        "uyari": (
            "Bu karşılaştırma kazanma oranını SABİT tutar. Gerçekte "
            "çıkış değişince kazanma oranı da değişir; bu yüzden bu bir "
            "ÜST/ALT sınır değil, TEŞHİS amaçlı kaba karşılaştırmadır."
        ),
    }


def _resimulate_symmetric(trades, candles, horizon_bars: int = 48) -> dict:
    """GERÇEK dolan girişleri simetrik ±1R çıkışla yeniden simüle eder.

    `_counterfactual` kazanma oranını sabit tutar — yanıltıcı olabilir.
    Bu fonksiyon doğru soruyu sorar: AYNI girişler, AYNI stop mesafesi,
    ama çıkış -1R/+1R simetrik olsaydı brüt beklenti ne olurdu?

    Fark = çıkış geometrisinin brüt beklentiye katkısı.
    """
    from tools.entry_edge import symmetric_path

    idx = {s: {c.timestamp: i for i, c in enumerate(rows)}
           for s, rows in candles.items()}
    rows_out = []
    for t in trades:
        if t.get("type") != "CLOSE":
            continue
        sym = t.get("symbol")
        entry = float(t.get("entry") or t.get("entry_price") or 0.0)
        # İLK stop kullanılmalı: stop_loss trailing/breakeven ile
        # değişmiştir. Sıfıra çekilmiş stop (breakeven) r_price=0 verir
        # ve simülasyon dışı kalır — bu, örneklemi sessizce bozar.
        stop_px = t.get("initial_stop_loss") or t.get("stop_loss")
        stop_frac = abs(entry - float(stop_px)) / entry if stop_px else None
        ts = (int(t.get("timestamp") or 0) - int(t.get("hold_ms") or 0)) or None
        side = t.get("side")
        if not (sym and entry and stop_frac and ts and side):
            continue
        series = candles.get(sym)
        pos = idx.get(sym, {}).get(int(ts))
        if series is None or pos is None:
            continue
        fwd = series[pos + 1:]
        if len(fwd) < 2:
            continue
        sim = symmetric_path(side, entry, entry * float(stop_frac), fwd,
                             horizon_bars)
        if sim is None:
            continue
        # Karşılaştırma BRÜT olmalı: simetrik taraf maliyet içermiyor.
        # r_multiple NET'tir; maliyeti geri ekleyerek brütleştiriyoruz.
        risk = float(t.get("target_net_risk") or 0.0)
        cost = (float(t.get("entry_fee") or 0.0) + float(t.get("fee") or 0.0)
                + float(t.get("slippage") or 0.0)
                + float(t.get("funding_paid") or 0.0))
        net_pnl = float(t.get("pnl") or 0.0)
        realized_r = (net_pnl + cost) / risk if risk > 0 else 0.0
        rows_out.append({
            "gercek_r": realized_r,
            "sim_kotumser": sim["kotumser"]["r"],
            "sim_iyimser": sim["iyimser"]["r"],
        })
    if not rows_out:
        return {"eslesen_islem": 0,
                "not": "İşlem kayıtlarında giriş/stop alanları eşleşmedi."}
    n = len(rows_out)
    def _mean(k):
        return round(sum(r[k] for r in rows_out) / n, 4)
    g = _mean("gercek_r")
    k = _mean("sim_kotumser")
    i = _mean("sim_iyimser")
    return {
        "eslesen_islem": n,
        "gercek_brut_r_ortalama": g,
        "simetrik_kotumser_r": k,
        "simetrik_iyimser_r": i,
        "cikis_katkisi_kotumser_r": round(g - k, 4),
        "cikis_katkisi_iyimser_r": round(g - i, 4),
        "simetrik_kazanma_orani": round(
            sum(1 for r in rows_out if r["sim_kotumser"] > 0) / n, 4),
        "yorum": (
            "Çıkış katkisi NEGATİFSE gerçek çıkış geometrisi, aynı "
            "girişlerde simetrik ±1R'den DAHA KÖTÜ sonuç veriyor. "
            "Bu, çıkışın kazananı erken kestiğinin doğrudan kanıtıdır."
        ),
    }


def _exit_reasons(trades, r_base: float) -> dict:
    """Çıkış nedeni bazında R dağılımı — kazanan NEREDE kesiliyor?"""
    closes = [t for t in trades if t.get("type") == "CLOSE"]
    agg = {}
    for t in closes:
        k = str(t.get("reason") or "bilinmiyor")
        a = agg.setdefault(k, {"n": 0, "net": 0.0, "r": 0.0, "tp1": 0})
        a["n"] += 1
        a["net"] += float(t.get("pnl") or 0.0)
        a["r"] += float(t.get("r_multiple") or 0.0)
        if t.get("tp1_done"):
            a["tp1"] += 1
    out = {}
    for k, a in sorted(agg.items(), key=lambda kv: kv[1]["net"]):
        out[k] = {
            "islem": a["n"],
            "net_pnl": round(a["net"], 4),
            "ort_r": round(a["r"] / a["n"], 4),
            "tp1_yapilmis": a["tp1"],
            "ort_sure_dk": None,
        }
    holds = {}
    for t in closes:
        k = str(t.get("reason") or "bilinmiyor")
        holds.setdefault(k, []).append(float(t.get("hold_ms") or 0) / 60000.0)
    for k, v in holds.items():
        if k in out:
            out[k]["ort_sure_dk"] = round(sum(v) / len(v), 2)
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    from dataclasses import replace

    from backtest.costs import CostModel
    from backtest.engine import BacktestEngine
    from tools.validate_strategy import (
        _load_or_fetch, _profile_config, load_targeted_cache,
    )

    config = _profile_config(args.profile, None)
    config = replace(config, portfolio=replace(
        config.portfolio,
        drawdown_peak_mode=args.drawdown_peak_mode,
        drawdown_peak_window_days=args.drawdown_peak_days,
    ))
    bars = args.days * 288
    keys = [f"{args.exchange}:{s.strip()}"
            for s in args.symbols.split(",") if s.strip()]
    data_dir = Path(args.data_dir)
    candles = {}
    for k, bare in zip(keys, [s.strip() for s in args.symbols.split(",") if s.strip()]):
        rows = _load_or_fetch(args.exchange, bare, bars, "5m", data_dir, 0.2)
        if rows:
            candles[k] = rows[-bars:] if len(rows) > bars else rows
    if not candles:
        logger.error("Veri yok")
        return 2

    fine = load_targeted_cache(data_dir, keys)
    costs = CostModel.load(args.costs) if args.costs else CostModel()
    logger.info("%s", costs.summary_text(keys))

    runs = {}
    for label, cm in (("gercek", costs), ("maliyetsiz", CostModel.disabled())):
        eng = BacktestEngine(config, initial_balance=args.balance)
        res = eng.run(candles, cost_model=cm, fine_candles_by_symbol=fine)
        runs[label] = res
        logger.info("%s: %d işlem, net %.4f", label, res.trade_count, res.net_pnl)

    real = runs["gercek"]
    nocost = runs["maliyetsiz"]
    from dataclasses import asdict

    from backtest.metrics import compute_metrics
    m = asdict(compute_metrics(
        list(real.trades), args.balance, real.final_balance,
        real.equity_curve,
    ))

    exp_usdt = float(m.get("expectancy_usdt") or 0.0)
    exp_r = float(m.get("expectancy_r") or 0.0)
    r_base = abs(exp_usdt / exp_r) if exp_r else float(
        m.get("avg_loss") or 1.0) * -1 or 1.0

    d = _decompose(list(real.trades), r_base)
    cf = _counterfactual(d)

    total_loss = -d.get("net_pnl", 0.0)
    direct = d.get("dogrudan_maliyet", 0.0)
    attribution = {}
    if total_loss > 0:
        attribution = {
            "dogrudan_maliyet_payi": round(direct / total_loss, 4),
            "ters_fiyat_hareketi_payi": round(
                (total_loss - direct) / total_loss, 4),
            "olcum_kontrolu": round(
                real.net_pnl - nocost.net_pnl, 4),
            "aciklama": (
                "Maliyet payı = (komisyon+kayma) / toplam zarar. "
                "Kalan pay ters fiyat hareketi + çıkış asimetrisidir."
            ),
        }

    report = {
        "arac": "tools.loss_attribution",
        "exchange": args.exchange,
        "symbols": list(candles),
        "days": args.days,
        "drawdown_peak_mode": args.drawdown_peak_mode,
        "bilesenler": d,
        "cikis_karsilastirmasi": cf,
        "ayni_giris_simetrik": _resimulate_symmetric(list(real.trades), candles),
        "zarar_atfi": attribution,
        "maliyetsiz_net": round(nocost.net_pnl, 4),
        "maliyetli_net": round(real.net_pnl, 4),
        "cikis_nedenleri": _exit_reasons(list(real.trades), r_base),
        "motor": m.get("by_engine", {}),
        "sembol": m.get("by_symbol", {}),
        "yon": m.get("by_side", {}),
        "rejim": m.get("by_regime", {}),
        "risk_olcek": real.risk_scaling,
        "drawdown_tepe": real.drawdown_peak,
        "red_dagilimi": dict(sorted(
            real.rejection_counts.items(), key=lambda kv: -kv[1])[:12]),
        "sinirlar": [
            "Funding oranları iletilmediyse funding ~0 çıkar; bu "
            "ÖLÇÜLMEDİ demektir, 'önemsiz' demektir DEĞİL.",
            "Simetrik karşılaştırma kazanma oranını sabit tutar; "
            "teşhis amaçlıdır, kesin sınır değildir.",
            f"Evren {len(candles)} sembol, {args.days} gün, tek rejim.",
        ],
    }
    out = Path(args.out)
    tp = Path(str(out).replace(".json", "_trades.json"))
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(json.dumps(
        [t for t in real.trades
         if t.get("type") in ("CLOSE", "PARTIAL_CLOSE", "ORDER_NEW")],
        ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1,
                              allow_nan=False), encoding="utf-8")
    logger.info("Rapor: %s", out)

    print("\n=== ZARAR BİLEŞENLERİ ===")
    for k in ("islem", "net_pnl", "brut_pnl", "komisyon", "kayma",
              "funding", "kazanma_orani", "ort_kazanc", "ort_kayip",
              "odeme_orani", "net_r", "brut_r", "maliyet_r"):
        print(f"  {k:20s}: {d.get(k)}")
    print("\n=== ZARAR ATFI ===")
    for k, v in attribution.items():
        print(f"  {k:26s}: {v}")
    print("\n=== ÇIKIŞ NEDENLERİ ===")
    for k, v in report["cikis_nedenleri"].items():
        print(f"  {k:26s} n={v['islem']:3d} net={v['net_pnl']:9.2f} "
              f"ortR={v['ort_r']:+.3f} tp1={v['tp1_yapilmis']:2d} "
              f"süre={v['ort_sure_dk']}dk")
    print("\n=== AYNI GİRİŞ, SİMETRİK ÇIKIŞ ===")
    for k, v in report["ayni_giris_simetrik"].items():
        if k != "yorum":
            print(f"  {k:30s}: {v}")
    print("\n=== ÇIKIŞ KARŞILAŞTIRMASI ===")
    for k in ("gercek_brut_r", "simetrik_brut_r",
              "cikis_geometrisi_katkisi_r", "simetrik_net_r", "gercek_net_r"):
        print(f"  {k:28s}: {cf.get(k)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
