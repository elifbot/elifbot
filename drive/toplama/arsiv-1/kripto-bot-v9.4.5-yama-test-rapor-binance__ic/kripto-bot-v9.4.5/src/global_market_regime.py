"""src/global_market_regime.py — v9.3 Global BTC+ETH Lider Rejim Çapası, Yönlü Piyasa Genişliği
ve Gerçek Taker Emir-Akışı / Nedensel MTF Motoru.

Temel İlkeler:
  1. Kripto vadeli işlemler evreninde varyansın büyük bölümü BTC/USDT ve ETH/USDT lider faktörü
     ile kesitsel yönlü piyasa genişliğinden (`net_breadth_score`) kaynaklanır.
  2. `BTC + ETH` net ayı rejimindeyken (`GLOBAL_BEARISH`) veya evren geneli satış ağırlıklıyken,
     altcoinlerdeki zayıf tepki yükselişlerine `LONG` açılması (bull-trap) engellenir; yalnızca
     gerçek ayrışma kanıtlayan (`yüksek bağıl güç + RVOL + MTF + güçlü alıcı akışı`) istisnalara izin verilir.
  3. Simetrik olarak `BTC + ETH` güçlü boğa rejimindeyken (`GLOBAL_BULLISH`), tepe hacim tükenmesi
     (`VOLUME_DIVERGENCE_SHORT`) kanıtlanmadıkça trend karşıtı erken `SHORT` sıkışmaları engellenir.
  4. Hem canlı 5m mumlarda hem OOS Walk-Forward doğrulamasında Binance `taker_buy_quote` (agresif alıcı
     USDT hacmi) verisinden gerçek Taker Delta, CVD eğimi, emilim (`absorption`) ve uyumsuzluk üretilir;
     5m serisinden nedensel (lookahead-free) `15m` ve `1h` MTF trendi türetilir.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .indicators import Indicators, compute_htf_trend, multi_timeframe_filter


def compute_candle_orderflow(df: pd.DataFrame) -> dict[str, Any]:
    """5m OHLCV (+ varsa gerçek `taker_buy_quote`) serisinden nedensel emir-akışı özeti üretir."""
    if df is None or len(df) < 5:
        return {
            "score": 0.0,
            "buy_usdt": 0.0,
            "sell_usdt": 0.0,
            "cvd_60s": 0.0,
            "cvd_slope": 0.0,
            "imbalance": 0.0,
            "rvol": 1.0,
            "absorption": "YOK",
            "cvd_divergence": "NONE",
            "has_real_taker": False,
        }

    tail = df.iloc[-24:]
    closes = tail["close"].astype(float).to_numpy()
    opens = tail["open"].astype(float).to_numpy()
    highs = tail["high"].astype(float).to_numpy()
    lows = tail["low"].astype(float).to_numpy()
    vols = np.maximum(0.0, tail["volume"].astype(float).to_numpy())

    has_real_taker = "taker_buy_quote" in tail.columns
    if has_real_taker:
        tb_raw = np.maximum(0.0, tail["taker_buy_quote"].astype(float).to_numpy())
        buy_v = np.minimum(vols, tb_raw)
        # Eğer son mumda taker_buy_quote=0 ama volume>0 ise mum konumuyla tamamla
        zero_mask = (vols > 0) & (buy_v <= 0)
        if np.any(zero_mask):
            rng = np.maximum(highs - lows, 1e-12)
            clv = np.clip((closes - lows) / rng, 0.05, 0.95)
            buy_v = np.where(zero_mask, vols * clv, buy_v)
    else:
        rng = np.maximum(highs - lows, 1e-12)
        clv = np.clip((closes - lows) / rng, 0.08, 0.92)
        body_dir = np.sign(closes - opens)
        buy_frac = np.clip(0.50 + 0.32 * (clv - 0.50) * 2.0 + 0.12 * body_dir, 0.08, 0.92)
        buy_v = vols * buy_frac

    sell_v = np.maximum(0.0, vols - buy_v)
    delta_v = buy_v - sell_v

    prior_vols = vols[:-1] if len(vols) > 4 else vols
    med_vol = float(np.median(prior_vols[prior_vols > 0])) if np.any(prior_vols > 0) else 1.0
    rvol = float(vols[-1] / max(med_vol, 1e-9))

    # Son 2 ve son 6 mumluk hacim ağırlıklı taker dengesi
    w2_tot = float(vols[-2:].sum())
    w2_imb = float(delta_v[-2:].sum() / w2_tot) if w2_tot > 0 else 0.0

    w6_tot = float(vols[-6:].sum()) if len(vols) >= 6 else w2_tot
    w6_imb = float(delta_v[-6:].sum() / w6_tot) if w6_tot > 0 else w2_imb

    # CVD eğimi ve Z-skoru
    delta_std = float(np.std(delta_v[:-1])) if len(delta_v) > 5 else 0.0
    recent_delta_mean = float(delta_v[-3:].mean())
    cvd_z = (recent_delta_mean / max(delta_std, med_vol * 0.04, 1e-9)) if med_vol > 0 else 0.0
    cvd_z = float(np.clip(cvd_z, -3.5, 3.5))

    # Fiyat-Delta uyumu (gövde yönü ile taker delta aynı yönde mi?)
    ret_2 = ((closes[-1] - closes[-3]) / max(closes[-3], 1e-12) * 100.0) if len(closes) >= 3 else 0.0
    rvol_mult = float(np.clip(0.75 + 0.25 * min(rvol, 3.0), 0.70, 1.50))

    raw_score = (w2_imb * 115.0 + w6_imb * 75.0 + cvd_z * 11.5) * rvol_mult
    if ret_2 * raw_score < 0 and abs(ret_2) > 0.25:
        # Fiyat ile delta ters düşüyorsa ham ivmeyi törpüle
        raw_score *= 0.65
    flow_score = float(np.clip(round(raw_score, 2), -100.0, 100.0))

    # Emilim (Absorption) tespiti: yüksek hacim + güçlü tek yönlü delta ama fiyat ters fitil bırakıyor
    absorption = "YOK"
    bar_rng = max(highs[-1] - lows[-1], 1e-12)
    upper_wick = (highs[-1] - max(opens[-1], closes[-1])) / bar_rng
    lower_wick = (min(opens[-1], closes[-1]) - lows[-1]) / bar_rng
    if rvol >= 1.35 and w2_imb >= 0.12 and upper_wick >= 0.52 and closes[-1] <= opens[-1] * 1.0005:
        absorption = "ALIS_EMILIMI"
    elif rvol >= 1.35 and w2_imb <= -0.12 and lower_wick >= 0.52 and closes[-1] >= opens[-1] * 0.9995:
        absorption = "SATIS_EMILIMI"

    # CVD Uyumsuzluğu (son 8 mum)
    cvd_divergence = "NONE"
    if len(closes) >= 10:
        prev_high = float(np.max(highs[-9:-2]))
        prev_low = float(np.min(lows[-9:-2]))
        cvd_recent = float(delta_v[-3:].sum())
        if highs[-1] >= prev_high * 0.9995 and cvd_recent < 0 and w2_imb <= -0.05:
            cvd_divergence = "BEARISH"
        elif lows[-1] <= prev_low * 1.0005 and cvd_recent > 0 and w2_imb >= 0.05:
            cvd_divergence = "BULLISH"

    buy_recent = float(buy_v[-2:].sum())
    sell_recent = float(sell_v[-2:].sum())
    cvd_recent_u = buy_recent - sell_recent
    cvd_prev_u = float(delta_v[-4:-2].sum()) if len(delta_v) >= 4 else 0.0

    return {
        "score": flow_score,
        "buy_usdt": round(buy_recent, 2),
        "sell_usdt": round(sell_recent, 2),
        "cvd_60s": round(cvd_recent_u, 2),
        "cvd_slope": round(cvd_recent_u - cvd_prev_u, 2),
        "imbalance": round(w2_imb, 4),
        "rvol": round(rvol, 3),
        "absorption": absorption,
        "cvd_divergence": cvd_divergence,
        "has_real_taker": has_real_taker,
    }


def resample_5m_to_htf(df_5m: pd.DataFrame) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """5m mum penceresinden gelecek bilgisi sızdırmadan (nedensel) hızlı NumPy ile `15m` ve `1h` OHLCV üretir."""
    if df_5m is None or len(df_5m) < 36:
        return None, None

    # Son 240 mum (20 saat) 15m (80 mum) ve 1h (20 mum) için fazlasıyla yeterlidir
    sub = df_5m.iloc[-240:]
    o = sub["open"].to_numpy(dtype=float)
    h = sub["high"].to_numpy(dtype=float)
    l = sub["low"].to_numpy(dtype=float)
    c = sub["close"].to_numpy(dtype=float)
    v = sub["volume"].to_numpy(dtype=float)

    ts_col = "open_time" if "open_time" in sub.columns else ("ts" if "ts" in sub.columns else None)
    if ts_col is not None:
        ts_vals = sub[ts_col].to_numpy(dtype="int64")
        scale = 1000 if int(ts_vals[-1]) > 10_000_000_000 else 1
        b15 = ts_vals // (900 * scale)
        b1h = ts_vals // (3600 * scale)
    else:
        idx = np.arange(len(sub), dtype="int64")
        b15 = idx // 3
        b1h = idx // 12

    def _fast_agg(buckets: np.ndarray) -> pd.DataFrame:
        change = np.empty(len(buckets), dtype=bool)
        change[0] = True
        change[1:] = buckets[1:] != buckets[:-1]
        starts = np.flatnonzero(change)
        ends = np.empty_like(starts)
        ends[:-1] = starts[1:] - 1
        ends[-1] = len(buckets) - 1
        return pd.DataFrame(
            {
                "open": o[starts],
                "high": np.maximum.reduceat(h, starts),
                "low": np.minimum.reduceat(l, starts),
                "close": c[ends],
                "volume": np.add.reduceat(v, starts),
            }
        )

    df_15m = _fast_agg(b15)
    df_1h = _fast_agg(b1h)
    return (df_15m if len(df_15m) >= 12 else None), (df_1h if len(df_1h) >= 8 else None)


def causal_mtf_from_5m(
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame | None = None,
    df_1h: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Hazır `15m`/`1h` varsa onları, yoksa `5m` üzerinden nedensel türetilmiş MTF filtresini döndürür."""
    use_15m, use_1h = df_15m, df_1h
    if use_15m is None or use_1h is None or len(use_15m) < 10 or len(use_1h) < 8:
        r15, r1h = resample_5m_to_htf(df_5m)
        if use_15m is None or len(use_15m) < 10:
            use_15m = r15
        if use_1h is None or len(use_1h) < 8:
            use_1h = r1h
    if use_15m is None and use_1h is None:
        return {
            "trend": "NEUTRAL",
            "score": 0.0,
            "allow_long": True,
            "allow_short": True,
            "reason": "mtf_yetersiz_veri",
        }
    return multi_timeframe_filter(use_15m, use_1h, bearish_block_th=-15.0, bullish_block_th=15.0)


def _normalize_leader_key(symbol: str) -> str | None:
    s = str(symbol or "").upper().replace("-", "").replace("/", "").strip()
    if s in ("BTCUSDT", "BTC"):
        return "BTC"
    if s in ("ETHUSDT", "ETH"):
        return "ETH"
    return None


class GlobalMarketRegimeAnchor:
    """BTC/USDT + ETH/USDT lider trend çapası ve yönlü piyasa genişliği (`net_breadth_score`) yöneticisi."""

    def __init__(
        self,
        *,
        bearish_leader_th: float = -20.0,
        bullish_leader_th: float = 20.0,
        flash_shock_5m_pct: float = 4.0,
        breadth_move_threshold_pct: float = 0.25,
    ) -> None:
        self.bearish_leader_th = float(bearish_leader_th)
        self.bullish_leader_th = float(bullish_leader_th)
        self.flash_shock_5m_pct = float(flash_shock_5m_pct)
        self.breadth_move_threshold_pct = float(breadth_move_threshold_pct)
        self.leaders: dict[str, dict[str, Any]] = {}
        self.breadth: dict[str, float] = {
            "bull_ratio": 0.0,
            "bear_ratio": 0.0,
            "active_ratio": 0.0,
            "net_score": 0.0,
            "sample_size": 0.0,
        }
        self.stats = {
            "leader_updates": 0,
            "long_blocked_global_bearish": 0,
            "short_blocked_global_bullish": 0,
            "flash_shock_blocks": 0,
            "decoupled_exceptions_allowed": 0,
        }

    def update_leader(self, symbol: str, df_5m: pd.DataFrame, now_ms: int | None = None) -> dict[str, Any] | None:
        """BTC veya ETH 5m mum penceresinden lider rejim durumunu nedensel olarak günceller."""
        key = _normalize_leader_key(symbol)
        if key is None or df_5m is None or len(df_5m) < 25:
            return None
        if now_ms is not None and int(now_ms) > 0:
            prev = self.leaders.get(key)
            if prev is not None and int(prev.get("ts_ms", -1)) == int(now_ms) and prev.get("price") == float(df_5m["close"].iloc[-1]):
                return prev

        closes = df_5m["close"].astype(float)
        highs = df_5m["high"].astype(float)
        lows = df_5m["low"].astype(float)
        px = float(closes.iloc[-1])
        px_5m = float(closes.iloc[-2]) if len(closes) >= 2 else px
        px_1h = float(closes.iloc[-13]) if len(closes) >= 13 else float(closes.iloc[0])

        ret_5m = ((px - px_5m) / px_5m * 100.0) if px_5m > 0 else 0.0
        ret_1h = ((px - px_1h) / px_1h * 100.0) if px_1h > 0 else 0.0

        e20 = float(Indicators.ema(closes, 20).iloc[-1])
        e50 = float(Indicators.ema(closes, min(50, len(closes))).iloc[-1])
        e200 = float(Indicators.ema(closes, min(200, len(closes))).iloc[-1])
        _, st_dir_s = Indicators.supertrend(highs, lows, closes)
        st_dir = 1 if int(st_dir_s.iloc[-1]) >= 0 else -1

        r15, r1h = resample_5m_to_htf(df_5m)
        htf_1h = compute_htf_trend(r1h, "1h") if r1h is not None else {"score": 0.0, "trend": "NEUTRAL"}
        c_flow = compute_candle_orderflow(df_5m)

        score = 0.0
        if px > e20 > e50:
            score += 28.0
        elif px < e20 < e50:
            score -= 28.0
        else:
            score += 10.0 if px > e50 else -10.0

        score += 12.0 if px > e200 else -12.0
        score += 14.0 if st_dir > 0 else -14.0
        score += float(htf_1h.get("score", 0.0)) * 0.30
        score += float(np.clip(ret_1h * 10.0, -18.0, 18.0))
        score += float(c_flow["score"]) * 0.16
        score = float(np.clip(round(score, 2), -100.0, 100.0))

        snap = {
            "leader": key,
            "price": px,
            "score": score,
            "ret_5m_pct": round(ret_5m, 4),
            "ret_1h_pct": round(ret_1h, 4),
            "ema20": round(e20, 4),
            "ema50": round(e50, 4),
            "ema200": round(e200, 4),
            "supertrend_dir": st_dir,
            "flow_score": c_flow["score"],
            "ts_ms": int(now_ms or 0),
        }
        self.leaders[key] = snap
        self.stats["leader_updates"] += 1
        return snap

    def update_directional_breadth_from_returns(self, returns_pct: list[float]) -> dict[str, float]:
        """Kesitsel sembol getiri yüzdelerinden boğa/ayı/net yönlü genişlik hesaplar."""
        valid = [float(r) for r in returns_pct if math.isfinite(float(r))]
        n = len(valid)
        if n == 0:
            return dict(self.breadth)
        th = self.breadth_move_threshold_pct
        bulls = sum(1 for r in valid if r >= th)
        bears = sum(1 for r in valid if r <= -th)
        bull_r = bulls / n
        bear_r = bears / n
        self.breadth = {
            "bull_ratio": round(bull_r, 4),
            "bear_ratio": round(bear_r, 4),
            "active_ratio": round(bull_r + bear_r, 4),
            "net_score": round(bull_r - bear_r, 4),
            "sample_size": float(n),
        }
        return dict(self.breadth)

    def update_directional_breadth_from_detector(self, detector) -> dict[str, float]:
        """Canlı `SpikeDetector` fiyat pencerelerinden (539 saf kripto kontrat) yönlü genişliği günceller."""
        rets: list[float] = []
        win_ms = getattr(detector, "ret_pencere_ms", 180_000)
        for d in getattr(detector, "durumlar", {}).values():
            fiyatlar = getattr(d, "fiyatlar", None)
            if not fiyatlar or len(fiyatlar) < 2:
                continue
            ts_son, f_son = fiyatlar[-1]
            if f_son <= 0:
                continue
            eski = None
            for ts, f in fiyatlar:
                if ts >= ts_son - win_ms:
                    eski = (ts, f)
                    break
            if eski is None or eski[1] <= 0 or (ts_son - eski[0]) < win_ms * 0.6:
                continue
            rets.append((f_son / eski[1] - 1.0) * 100.0)
        return self.update_directional_breadth_from_returns(rets)

    def snapshot(self) -> dict[str, Any]:
        btc = self.leaders.get("BTC")
        eth = self.leaders.get("ETH")
        scores: list[float] = []
        rets_1h: list[float] = []
        max_abs_5m = 0.0
        if btc is not None:
            scores.append(float(btc["score"]) * 0.58)
            rets_1h.append(float(btc["ret_1h_pct"]))
            max_abs_5m = max(max_abs_5m, abs(float(btc["ret_5m_pct"])))
        if eth is not None:
            w = 0.42 if btc is not None else 1.0
            scores.append(float(eth["score"]) * w)
            rets_1h.append(float(eth["ret_1h_pct"]))
            max_abs_5m = max(max_abs_5m, abs(float(eth["ret_5m_pct"])))

        if btc is not None and eth is not None:
            leader_score = round(sum(scores), 2)
        elif btc is not None:
            leader_score = round(float(btc["score"]), 2)
        elif eth is not None:
            leader_score = round(float(eth["score"]), 2)
        else:
            leader_score = 0.0

        leader_ret_1h = sum(rets_1h) / len(rets_1h) if rets_1h else 0.0
        net_b = float(self.breadth["net_score"])
        has_breadth = float(self.breadth["sample_size"]) >= 4.0

        if max_abs_5m >= self.flash_shock_5m_pct:
            bias = "EXTREME_SHOCK"
        elif leader_score <= self.bearish_leader_th or (
            leader_score <= -10.0 and has_breadth and net_b <= -0.18
        ):
            bias = "GLOBAL_BEARISH"
        elif leader_score >= self.bullish_leader_th or (
            leader_score >= 10.0 and has_breadth and net_b >= 0.18
        ):
            bias = "GLOBAL_BULLISH"
        else:
            bias = "GLOBAL_NEUTRAL"

        return {
            "global_bias": bias,
            "leader_score": leader_score,
            "leader_ret_1h_pct": round(leader_ret_1h, 4),
            "btc_score": round(float(btc["score"]), 2) if btc else None,
            "eth_score": round(float(eth["score"]), 2) if eth else None,
            "breadth": dict(self.breadth),
        }

    def evaluate_global_alignment(
        self,
        symbol: str,
        side: str,
        *,
        coin_ret_1h_pct: float = 0.0,
        rvol: float = 1.0,
        mtf_aligned: bool = True,
        flow_score: float = 0.0,
        vwap_atr_z: float = 0.0,
        playbook: str = "MOMENTUM_BREAKOUT",
    ) -> dict[str, Any]:
        """Aday sinyalin Global BTC+ETH Lider Rejimi ve Yönlü Genişlikle uyumunu denetler."""
        snap = self.snapshot()
        u_side = str(side or "BEKLE").upper()
        if u_side not in ("LONG", "SHORT"):
            return {"allowed": True, "leader_aligned": True, "score_bonus": 0.0, "reason": "bekle", **snap}

        bias = snap["global_bias"]
        leader_score = float(snap["leader_score"])
        leader_ret_1h = float(snap["leader_ret_1h_pct"])
        net_b = float(snap["breadth"]["net_score"])
        rel_strength_1h = float(coin_ret_1h_pct) - leader_ret_1h

        if bias == "EXTREME_SHOCK":
            self.stats["flash_shock_blocks"] += 1
            return {
                "allowed": False,
                "leader_aligned": False,
                "score_bonus": 0.0,
                "reason": "global_btc_eth_flash_sok_engeli",
                **snap,
            }

        if bias == "GLOBAL_BEARISH":
            if u_side == "SHORT":
                return {
                    "allowed": True,
                    "leader_aligned": True,
                    "score_bonus": 4.5,
                    "reason": f"global_ayi_onayli_short(lider={leader_score:+.1f},net_genislik={net_b:+.2f})",
                    **snap,
                }
            # u_side == "LONG": Global ayı trendinde yalnızca güçlü bağımsız ayrışma varsa izin ver
            decoupled_bull = (
                rel_strength_1h >= 1.80
                and float(rvol) >= 2.10
                and bool(mtf_aligned)
                and float(flow_score) >= 36.0
                and float(vwap_atr_z) <= 2.15
            )
            if decoupled_bull:
                self.stats["decoupled_exceptions_allowed"] += 1
                return {
                    "allowed": True,
                    "leader_aligned": False,
                    "score_bonus": 0.0,
                    "reason": f"global_ayida_bagimsiz_guc_istisnasi(rs1h={rel_strength_1h:+.2f}%)",
                    **snap,
                }
            self.stats["long_blocked_global_bearish"] += 1
            return {
                "allowed": False,
                "leader_aligned": False,
                "score_bonus": 0.0,
                "reason": (
                    f"global_btc_eth_ayi_long_engeli(lider={leader_score:+.1f},"
                    f"net_genislik={net_b:+.2f},rs1h={rel_strength_1h:+.2f}%)"
                ),
                **snap,
            }

        if bias == "GLOBAL_BULLISH":
            if u_side == "LONG":
                return {
                    "allowed": True,
                    "leader_aligned": True,
                    "score_bonus": 4.5,
                    "reason": f"global_boga_onayli_long(lider={leader_score:+.1f},net_genislik={net_b:+.2f})",
                    **snap,
                }
            # u_side == "SHORT": Global boğada yalnızca teyitli tepe hacim uyumsuzluğu veya sert bağımsız çöküşte izin ver
            confirmed_top_div = (
                playbook == "VOLUME_DIVERGENCE_SHORT"
                and float(flow_score) <= -18.0
                and float(vwap_atr_z) >= 1.30
            )
            decoupled_bear = (
                rel_strength_1h <= -2.00
                and float(rvol) >= 2.10
                and bool(mtf_aligned)
                and float(flow_score) <= -36.0
                and float(vwap_atr_z) >= -2.15
            )
            if confirmed_top_div or decoupled_bear:
                self.stats["decoupled_exceptions_allowed"] += 1
                return {
                    "allowed": True,
                    "leader_aligned": False,
                    "score_bonus": 0.0,
                    "reason": "global_bogada_tepe_uyumsuzluk_veya_ayrisma_short",
                    **snap,
                }
            self.stats["short_blocked_global_bullish"] += 1
            return {
                "allowed": False,
                "leader_aligned": False,
                "score_bonus": 0.0,
                "reason": (
                    f"global_btc_eth_boga_short_engeli(lider={leader_score:+.1f},"
                    f"net_genislik={net_b:+.2f})"
                ),
                **snap,
            }

        # GLOBAL_NEUTRAL: Kesitsel yönlü genişlik aşırı tek taraflıysa karşı yöne dikkat et
        if u_side == "LONG" and net_b <= -0.32 and not (bool(mtf_aligned) and float(flow_score) >= 30.0):
            self.stats["long_blocked_global_bearish"] += 1
            return {
                "allowed": False,
                "leader_aligned": False,
                "score_bonus": 0.0,
                "reason": f"evren_agir_satis_genisligi_long_engeli(net={net_b:+.2f})",
                **snap,
            }
        if u_side == "SHORT" and net_b >= 0.32 and playbook != "VOLUME_DIVERGENCE_SHORT" and not (
            bool(mtf_aligned) and float(flow_score) <= -30.0
        ):
            self.stats["short_blocked_global_bullish"] += 1
            return {
                "allowed": False,
                "leader_aligned": False,
                "score_bonus": 0.0,
                "reason": f"evren_agir_alis_genisligi_short_engeli(net={net_b:+.2f})",
                **snap,
            }

        return {
            "allowed": True,
            "leader_aligned": True,
            "score_bonus": 0.0,
            "reason": "global_rejim_uyumlu",
            **snap,
        }
