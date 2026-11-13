"""Giriş kalitesi, veri hazır olma ve portföy uygunluğu ölçümleri.

Bu modül tek başına emir üretmez. Shadow Lab, aynı baseline giriş adaylarında
alternatif kararları hesaplamak için kullanır; tek oturumdan otomatik canlı
kural veya parametre optimizasyonu yapılmaz.
"""
from __future__ import annotations

import math
import zlib
from collections.abc import Iterable, Mapping
from statistics import mean


def number(value, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def clip_score(value: float) -> float:
    return max(-100.0, min(100.0, float(value)))


def _confidence_exponential(value: float, reference: float) -> float:
    if value <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - math.exp(-value / max(1e-12, reference))))


def flow_confidence(flow: dict, cfg: dict) -> dict:
    """Oran yerine kanıt miktarını da taşıyan Taker/CVD güvenini hesapla."""
    buy = max(0.0, number(flow.get("buy_usdt")))
    sell = max(0.0, number(flow.get("sell_usdt")))
    total = buy + sell
    trades = max(0, int(number(flow.get("trade_count", flow.get("vpvr_trades", 0)))))
    coverage = max(
        0.0,
        number(flow.get("window_coverage_sec", flow.get("vpvr_coverage_sec", 0.0))),
    )
    window = max(1.0, number(cfg.get("pencere_saniye"), 300.0))
    min_trades = max(1, int(number(cfg.get("min_islem_sayisi"), 5)))
    min_coverage = max(0.0, number(cfg.get("min_kapsama_saniye"), 60.0))
    min_notional = max(0.0, number(cfg.get("min_notional_usdt"), 0.0))
    raw_levels = flow.get("book_levels")
    if (
        raw_levels is None
        and number(flow.get("bid_depth_usdt")) > 0
        and number(flow.get("ask_depth_usdt")) > 0
    ):
        book_levels = 1
    else:
        book_levels = max(0, int(number(raw_levels, 0)))
    raw_book_age = flow.get("book_age_sec")
    book_age = number(raw_book_age, float("inf")) if raw_book_age is not None else float("inf")
    max_book_age = max(0.0, number(cfg.get("max_defter_yasi_saniye"), 10.0))
    reference_notional = max(1e-9, number(cfg.get("referans_notional_usdt"), 1000.0))
    reference_cvd = max(1e-9, number(cfg.get("referans_cvd_usdt"), 100.0))
    coverage_confidence = max(0.0, min(1.0, coverage / window))
    trade_confidence = max(0.0, min(1.0, trades / max(1, min_trades * 4)))
    notional_confidence = _confidence_exponential(total, reference_notional)
    cvd_confidence = _confidence_exponential(abs(number(flow.get("cvd_slope"))), reference_cvd)
    taker_confidence = notional_confidence * trade_confidence * coverage_confidence
    cvd_confidence *= coverage_confidence

    missing = []
    if trades < min_trades:
        missing.append(f"işlem sayısı {trades}<{min_trades}")
    if coverage < min_coverage:
        missing.append(f"kapsama {coverage:.1f}sn<{min_coverage:.1f}sn")
    if min_notional > 0 and total < min_notional:
        missing.append(f"hacim ${total:.0f}<${min_notional:.0f}")
    if book_levels < 1:
        missing.append("emir defteri yok")
    if not math.isfinite(book_age) or book_age > max_book_age:
        age_text = "yok" if not math.isfinite(book_age) else f"{book_age:.1f}sn"
        missing.append(f"defter yaşı {age_text}>{max_book_age:.1f}sn")

    components = dict(flow.get("score_components") or {})
    old_taker = number(components.get("taker_delta"))
    old_cvd = number(components.get("cvd_direction"))
    adjusted_components = dict(components)
    adjusted_components["taker_delta"] = old_taker * taker_confidence
    adjusted_components["cvd_direction"] = old_cvd * cvd_confidence
    unclipped = number(flow.get("score_unclipped"), number(flow.get("score")))
    adjusted_unclipped = unclipped - old_taker - old_cvd + sum(
        adjusted_components.get(name, 0.0) for name in ("taker_delta", "cvd_direction")
    )
    return {
        "data_ready": not missing,
        "data_missing": missing,
        "trade_count": trades,
        "notional_usdt": round(total, 6),
        "coverage_sec": round(coverage, 3),
        "book_levels": book_levels,
        "book_age_sec": round(book_age, 3) if math.isfinite(book_age) else None,
        "coverage_confidence": round(coverage_confidence, 6),
        "trade_confidence": round(trade_confidence, 6),
        "notional_confidence": round(notional_confidence, 6),
        "taker_confidence": round(taker_confidence, 6),
        "cvd_confidence": round(cvd_confidence, 6),
        "original_flow_score": number(flow.get("score")),
        "adjusted_flow_score": round(clip_score(adjusted_unclipped), 4),
        "adjusted_score_unclipped": round(adjusted_unclipped, 6),
        "adjusted_components": adjusted_components,
    }


def pdf_confluence(context: dict, side: str, config: dict) -> dict:
    """PDF v2 aile oyu; yalnız Shadow gözlemi, baseline'a dokunmaz."""
    cfg = config.get("pdf_confluence", {}) if isinstance(config, dict) else {}
    indicators = context.get("indicators") or {}
    research = indicators.get("pdf_v2") or {}
    votes = dict(research.get("family_votes") or {})
    flow = context.get("orderflow") or {}
    trade_count = number(flow.get("trade_count", flow.get("vpvr_trades", 0)))
    raw_levels = flow.get("book_levels")
    levels = (
        1.0
        if (
            raw_levels is None
            and number(flow.get("bid_depth_usdt")) > 0
            and number(flow.get("ask_depth_usdt")) > 0
        )
        else number(raw_levels, 0)
    )
    flow_score = number(flow.get("score"))
    derivative_vote = (1 if flow_score > 0 else -1 if flow_score < 0 else 0) if trade_count > 0 and levels > 0 else 0
    votes["derivatives"] = derivative_vote
    direction = 1 if side == "LONG" else -1
    aligned = sorted(name for name, value in votes.items() if number(value) * direction > 0)
    opposed = sorted(name for name, value in votes.items() if number(value) * direction < 0)
    neutral = sorted(name for name, value in votes.items() if number(value) == 0)
    minimum = max(1, min(6, int(number(cfg.get("min_aligned_families"), 4))))
    maximum_opposed = max(0, min(5, int(number(cfg.get("max_opposed_families"), 2))))
    ready = bool(research.get("data_ready"))
    accepted = bool(ready and len(aligned) >= minimum and len(opposed) <= maximum_opposed)
    return {
        "accepted": accepted,
        "reason": "" if accepted else "PDF v2 aile oyu/veri yetersiz",
        "aligned_families": aligned,
        "opposed_families": opposed,
        "neutral_families": neutral,
        "family_votes": votes,
        "aligned_count": len(aligned),
        "opposed_count": len(opposed),
        "minimum_aligned": minimum,
        "maximum_opposed": maximum_opposed,
        "data_ready": ready,
        "derivatives_vote": derivative_vote,
        "external_data_used": False,
        "baseline_changed": False,
    }


def pdf_v3_confluence(context: dict, side: str, config: dict) -> dict:
    """PDF v3 adaptif MA + istatistiksel rejim + likidasyon mıknatısı + türev kalabalık oyu."""
    cfg = config.get("pdf_v3_confluence", {}) if isinstance(config, dict) else {}
    indicators = context.get("indicators") or {}
    v3 = indicators.get("pdf_v3") or {}
    deriv = context.get("derivatives_intel") or {}
    direction = 1 if str(side).upper() == "LONG" else -1

    ready = bool(v3.get("data_ready"))
    vals = v3.get("values") or {}
    regime_model = v3.get("regime_model") or {}
    liq = v3.get("liq_clusters") or {}
    btc_ctx = v3.get("btc_context") or {}
    crowding = (deriv.get("crowding") or {}) if isinstance(deriv, dict) else {}

    adaptive_vote = int(number(vals.get("adaptive_ma_consensus"), 0))
    ribbon_score = number(vals.get("ema_ribbon_score"), 0.0)
    ribbon_vote = 1 if ribbon_score >= 25 else (-1 if ribbon_score <= -25 else 0)
    stat_vote = int(number(regime_model.get("regime_vote"), 0))
    magnet_vote = int(number(liq.get("magnet_bias"), 0))

    crowd_state = str(crowding.get("crowding_state") or "DENGELI")
    smart_div = str(crowding.get("smart_money_divergence") or "YOK")
    deriv_vote = 0
    if smart_div == "TOP_TRADER_LONG_PERAKENDE_SHORT":
        deriv_vote = 1
    elif smart_div == "TOP_TRADER_SHORT_PERAKENDE_LONG":
        deriv_vote = -1
    elif crowd_state == "SHORT_KALABALIK":
        deriv_vote = 1
    elif crowd_state == "LONG_KALABALIK":
        deriv_vote = -1

    btc_vote = 0
    if bool(btc_ctx.get("available")):
        btc_regime = str(btc_ctx.get("btc_regime") or "")
        corr = number(btc_ctx.get("correlation_60"), 0.0)
        if corr >= 0.45:
            if "BULL" in btc_regime or "UP" in btc_regime:
                btc_vote = 1
            elif "BEAR" in btc_regime or "DOWN" in btc_regime:
                btc_vote = -1

    votes = {
        "adaptive_ma": adaptive_vote,
        "ema_ribbon": ribbon_vote,
        "stat_regime": stat_vote,
        "liq_magnet": magnet_vote,
        "derivatives_crowding": deriv_vote,
        "btc_macro": btc_vote,
    }
    aligned = sorted(k for k, v in votes.items() if v * direction > 0)
    opposed = sorted(k for k, v in votes.items() if v * direction < 0)
    min_aligned = max(1, min(6, int(number(cfg.get("min_aligned_signals"), 2))))
    max_opposed = max(0, min(6, int(number(cfg.get("max_opposed_signals"), 2))))
    accepted = bool(ready and len(aligned) >= min_aligned and len(opposed) <= max_opposed)
    return {
        "accepted": accepted,
        "reason": "" if accepted else "PDF v3 + türev istihbarat uyumu yetersiz",
        "data_ready": ready,
        "votes": votes,
        "aligned_signals": aligned,
        "opposed_signals": opposed,
        "aligned_count": len(aligned),
        "opposed_count": len(opposed),
        "crowding_state": crowd_state,
        "smart_money_divergence": smart_div,
    }


def technical_harmony(context: dict, side: str, max_opposed: int = 1) -> dict:
    indicators = context.get("indicators") or {}
    active = indicators.get("active_components") or {}
    direction = 1.0 if side == "LONG" else -1.0
    aligned = []
    opposed = []
    neutral = []
    for name, raw_value in active.items():
        value = number(raw_value)
        directional = value * direction
        if directional > 1e-12:
            aligned.append(name)
        elif directional < -1e-12:
            opposed.append(name)
        else:
            neutral.append(name)
    directional_score = number(indicators.get("score")) * direction
    accepted = len(opposed) <= max(0, int(max_opposed))
    return {
        "accepted": accepted,
        "reason": "" if accepted else f"karşıt teknik bileşen {len(opposed)}>{max_opposed}",
        "aligned_count": len(aligned),
        "opposed_count": len(opposed),
        "neutral_count": len(neutral),
        "aligned_components": aligned,
        "opposed_components": opposed,
        "directional_score": round(directional_score, 6),
    }


def volatility_quality(indicators: dict, cfg: dict) -> dict:
    """Hareket alanını round-trip maliyet ve runner eşiğiyle karşılaştır."""
    snapshot = indicators.get("snapshot") or {}
    entry = number(indicators.get("close", snapshot.get("price")))
    atr = number(indicators.get("atr", snapshot.get("atr")))
    atr_pct = number(indicators.get("atr_pct", snapshot.get("atr_pct")))
    if atr_pct <= 0 and atr > 0 and entry > 0:
        atr_pct = atr / entry * 100.0
    bb_width = max(
        0.0,
        number(
            indicators.get(
                "bb_width_pct",
                indicators.get("bollinger_bandwidth_pct", snapshot.get("bollinger_bandwidth_pct")),
            )
        ),
    )
    round_trip_cost = max(
        0.0,
        number(cfg.get("komisyon_maker_yuzde"), 0.02)
        + number(cfg.get("komisyon_taker_yuzde"), 0.05),
    )
    min_bb = max(0.0, number(cfg.get("min_bb_genisligi_yuzde"), 0.20))
    min_atr = max(0.0, number(cfg.get("min_atr_yuzde"), 0.0))
    bb_ok = min_bb > 0 and bb_width >= min_bb
    atr_ok = min_atr > 0 and atr_pct >= min_atr
    # İki ölçüm de tanımlıysa biri yeterli hareket alanı gösterebilir; ancak
    # hiç ölçüm yoksa aday güvenli biçimde kabul edilmez.
    has_measurement = bb_width > 0 or atr_pct > 0
    has_threshold = min_bb > 0 or min_atr > 0
    accepted = has_measurement and ((bb_ok or atr_ok) if has_threshold else True)
    runner_min = max(0.0, number(cfg.get("orderflow_min_kar_yuzde"), 0.5))
    return {
        "accepted": accepted,
        "reason": "" if accepted else "volatilite/maliyet hareket alanı yetersiz",
        "atr_pct": round(atr_pct, 6),
        "bb_width_pct": round(bb_width, 6),
        "round_trip_cost_pct": round(round_trip_cost, 6),
        "atr_cost_ratio": round(atr_pct / round_trip_cost, 6) if round_trip_cost > 0 else None,
        "bb_cost_ratio": round(bb_width / round_trip_cost, 6) if round_trip_cost > 0 else None,
        "bb_runner_ratio": round(bb_width / runner_min, 6) if runner_min > 0 else None,
        "min_bb_width_pct": min_bb,
        "min_atr_pct": min_atr,
    }


def range_flow_gate(context: dict, allow_flow_trigger: bool = False) -> dict:
    indicators = context.get("indicators") or {}
    combined = context.get("combined") or {}
    regime = str(indicators.get("market_regime") or indicators.get("regime") or "UNKNOWN").upper()
    raw_signal = str(combined.get("raw_signal") or "BEKLE").upper()
    trigger = str(combined.get("trigger") or "").upper()
    flow_only = raw_signal == "BEKLE" and trigger in {"PARA_GIRISI", "PARA_CIKISI"}
    accepted = allow_flow_trigger or regime != "RANGE" or not flow_only
    return {
        "accepted": accepted,
        "reason": "" if accepted else "RANGE rejiminde yalnız para-akışı tetikli giriş",
        "market_regime": regime,
        "raw_signal": raw_signal,
        "trigger": combined.get("trigger"),
    }


def market_context(context: dict) -> dict:
    indicators = context.get("indicators") or {}
    flow = context.get("orderflow") or {}
    return {
        **indicators,
        "cvd_slope": flow.get("cvd_slope", 0.0),
        "cvd_divergence": flow.get("cvd_divergence", "YOK"),
        "absorption": flow.get("absorption", "YOK"),
        "oi_signal": flow.get("oi_signal", "NOTR"),
        "oi_change_pct": flow.get("oi_change_pct", 0.0),
        "price_change_pct": flow.get("price_change_pct", 0.0),
    }


def adjusted_flow_entry(strategy, context: dict, side: str, confidence: dict) -> dict:
    indicators = context.get("indicators") or {}
    inputs = context.get("decision_inputs") or {}
    combined = strategy.combine(
        number(indicators.get("score")),
        number(confidence.get("adjusted_flow_score")),
        number(inputs.get("news_score")),
        inputs.get("ml_score"),
        market_context=market_context(context),
    )
    decision = strategy.entry_decision(
        combined,
        bool(inputs.get("veto")),
        has_position=False,
        veto_long=bool(inputs.get("veto_long")),
        veto_short=bool(inputs.get("veto_short")),
        mtf_trend=context.get("mtf"),
    )
    accepted = bool(confidence.get("data_ready")) and decision.get("action") == side
    reasons = list(confidence.get("data_missing") or [])
    if decision.get("action") != side:
        reasons.append(f"güven ayarlı karar={decision.get('action')}:{decision.get('reason')}")
    return {
        "accepted": accepted,
        "reason": "; ".join(reasons),
        "action": decision.get("action"),
        "combined": combined,
    }


def pearson_alignment(left: list[float], right: list[float]) -> tuple[float | None, int]:
    """İki getiri serisini sondan hizalayarak Pearson korelasyonu hesapla."""
    n = min(len(left), len(right))
    if n < 2:
        return None, n
    xs = list(left[-n:])
    ys = list(right[-n:])
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denom <= 1e-20:
        return None, n
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(dx, dy)) / denom)), n


def portfolio_guard(
    symbol: str,
    side: str,
    open_entries: list[dict],
    returns: dict[str, list[float]],
    cfg: dict,
) -> dict:
    max_same_side = max(1, int(number(cfg.get("ayni_yon_max_pozisyon"), 50)))
    same_side = [p for p in open_entries if p.get("side") == side]
    if len(same_side) >= max_same_side:
        return {
            "accepted": False,
            "reason": f"aynı yön pozisyon {len(same_side)}>={max_same_side}",
            "same_side_count": len(same_side),
            "correlations": [],
        }
    threshold = number(cfg.get("korelasyon_esik"), 0.80)
    min_common = max(2, int(number(cfg.get("korelasyon_min_ortak_getiri"), 20)))
    max_correlated = max(1, int(number(cfg.get("korelasyon_max_pozisyon"), 3)))
    candidate_returns = returns.get(symbol) or []
    correlations = []
    for other in same_side:
        other_symbol = str(other.get("symbol") or "")
        corr, common = pearson_alignment(candidate_returns, returns.get(other_symbol) or [])
        if corr is not None and common >= min_common:
            correlations.append({"symbol": other_symbol, "correlation": round(corr, 6), "common": common})
    highly = [row for row in correlations if row["correlation"] >= threshold]
    accepted = len(highly) < max_correlated
    return {
        "accepted": accepted,
        "reason": "" if accepted else f"yüksek korelasyonlu aynı yön pozisyon {len(highly)}>={max_correlated}",
        "same_side_count": len(same_side),
        "correlation_data_ready": not same_side or bool(correlations),
        "correlation_coverage_pct": (
            len(correlations) / len(same_side) * 100.0 if same_side else 100.0
        ),
        "highly_correlated_count": len(highly),
        "correlations": sorted(correlations, key=lambda row: row["correlation"], reverse=True)[:10],
    }


def exhaustion_guard(
    indicators: Mapping | None,
    flow: Mapping | None,
    side: str,
    cfg: Mapping | None = None,
) -> dict:
    """Aşırı satım dibinde geç SHORT / aşırı alım tepesinde geç LONG girişlerini engeller."""
    ind = indicators if isinstance(indicators, Mapping) else {}
    flw = flow if isinstance(flow, Mapping) else {}
    conf = cfg if isinstance(cfg, Mapping) else {}
    side_u = str(side or "").upper()

    raw_rsi = ind.get("rsi")
    raw_mfi = ind.get("mfi")
    rsi = number(raw_rsi, -1.0) if raw_rsi is not None else -1.0
    mfi = number(raw_mfi, -1.0) if raw_mfi is not None else -1.0
    v2_vals = ((ind.get("pdf_v2") or {}).get("values") or {}) if isinstance(ind.get("pdf_v2"), Mapping) else {}
    rsi_div = int(number(v2_vals.get("rsi_divergence", ind.get("rsi_divergence", 0)), 0))
    squeeze = str(flw.get("squeeze") or "YOK").upper()

    short_min_rsi = number(conf.get("short_min_rsi"), 27.0)
    short_min_mfi = number(conf.get("short_min_mfi"), 18.0)
    long_max_rsi = number(conf.get("long_max_rsi"), 73.0)
    long_max_mfi = number(conf.get("long_max_mfi"), 82.0)

    reason = ""
    if side_u == "SHORT" and squeeze != "LONG_SQUEEZE":
        if 0.0 < rsi <= short_min_rsi:
            reason = f"aşırı satım dibinde geç SHORT (RSI={rsi:.1f}<={short_min_rsi:.1f})"
        elif 0.0 < rsi <= (short_min_rsi + 3.0) and 0.0 < mfi <= short_min_mfi:
            reason = f"RSI/MFI satış tükenmesi (RSI={rsi:.1f}, MFI={mfi:.1f}<={short_min_mfi:.1f})"
        elif 0.0 < rsi <= (short_min_rsi + 7.0) and rsi_div > 0:
            reason = f"dipte pozitif RSI uyumsuzluğu (RSI={rsi:.1f}, div=+1)"
    elif side_u == "LONG" and squeeze != "SHORT_SQUEEZE":
        if rsi >= long_max_rsi:
            reason = f"aşırı alım tepesinde geç LONG (RSI={rsi:.1f}>={long_max_rsi:.1f})"
        elif rsi >= (long_max_rsi - 3.0) and mfi >= long_max_mfi:
            reason = f"RSI/MFI alış tükenmesi (RSI={rsi:.1f}, MFI={mfi:.1f}>={long_max_mfi:.1f})"
        elif rsi >= (long_max_rsi - 7.0) and rsi_div < 0:
            reason = f"tepede negatif RSI uyumsuzluğu (RSI={rsi:.1f}, div=-1)"

    return {
        "accepted": not reason,
        "reason": reason,
        "rsi": round(rsi, 3) if rsi >= 0 else None,
        "mfi": round(mfi, 3) if mfi >= 0 else None,
        "rsi_divergence": rsi_div,
        "squeeze": squeeze,
    }


def rank_symbols_for_scan(
    symbols: Iterable[str],
    *,
    preferred_symbols: Iterable[str] = (),
    open_positions: Iterable[str] = (),
    flow_snapshots: Mapping[str, Mapping] | None = None,
    live_scores: Mapping[str, Mapping] | None = None,
) -> list[str]:
    """Alfabetik A-B-C önyargısını önleyen likidite ve sinyal öncelikli tarama sırası."""
    all_syms = list(symbols)
    sym_set = set(all_syms)
    open_list = [s for s in open_positions if s in sym_set]
    seen = set(open_list)
    pref_list = [s for s in preferred_symbols if s in sym_set and s not in seen]
    seen.update(pref_list)

    flows_map = flow_snapshots or {}
    scores_map = live_scores or {}

    def _priority_key(sym: str) -> tuple[int, float, int]:
        flw = flows_map.get(sym) or {}
        sc = scores_map.get(sym) or {}
        buy_v = max(0.0, number(flw.get("buy_usdt")))
        sell_v = max(0.0, number(flw.get("sell_usdt")))
        net_flow = abs(buy_v - sell_v)
        vol = buy_v + sell_v
        depth = max(0.0, number(flw.get("bid_depth_usdt")) + number(flw.get("ask_depth_usdt")))
        flow_score_abs = abs(number(flw.get("score")))
        coverage = max(0.0, number(flw.get("window_coverage_sec")))
        trades = max(0, int(number(flw.get("trade_count"))))
        warm = 1 if (coverage >= 60.0 and trades >= 10) else 0
        abs_total = abs(number(sc.get("total")))
        # İlk sırada en sert Net Para Girişi (+$) ve Net Para Çıkışı (-$) olan pariteler taranır.
        score_rank = (
            net_flow * 2.0
            + vol * 0.5
            + depth * 0.20
            + flow_score_abs * 1000.0
            + abs_total * 500.0
        )
        # Eşitlikte A-Z yerine deterministik karma sıra kullan (A-B-C önyargısını kır).
        tie_hash = zlib.crc32(sym.encode("utf-8"))
        return (warm, round(score_rank, 2), tie_hash)

    rest = [s for s in all_syms if s not in seen]
    rest.sort(key=_priority_key, reverse=True)
    return open_list + pref_list + rest

