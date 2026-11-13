"""Executor ve Shadow Lab tarafından paylaşılan saf çıkış kuralları."""
from __future__ import annotations

import time
from datetime import datetime, timezone


def position_age_seconds(
    pos,
    now_ts: float | None = None,
    opened_ts: float | None = None,
) -> float:
    """Pozisyonun açık kalma süresini (saniye) güvenli biçimde hesaplar."""
    now = float(now_ts if now_ts is not None else time.time())
    if opened_ts is not None and float(opened_ts) > 0:
        return max(0.0, now - float(opened_ts))
    raw = str(getattr(pos, "opened_at", "") or "").strip()
    if not raw:
        return 0.0
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return max(0.0, now - dt.timestamp())
    except ValueError:
        return 0.0


def trailing_floor(risk, pos) -> float:
    """Aktif modda gerçek net başabaş, aksi halde eski brüt giriş tabanı."""
    if getattr(pos, "net_breakeven_enabled", False):
        return float(risk.net_breakeven_price(pos))
    return float(pos.entry)


def apply_supertrend_trailing(pos, price: float, info: dict | None, risk) -> bool:
    """Supertrend stopunu yalnız kâr ve geçerli başabaş tabanı yönünde sıkılaştır."""
    if not info or risk.profit_pct(pos, price) <= 0:
        return False
    direction = 1 if pos.side == "LONG" else -1
    try:
        trend_direction = int(info.get("direction", 0))
        value = float(info.get("value", 0.0))
    except (TypeError, ValueError, AttributeError):
        return False
    if trend_direction != direction or value <= 0:
        return False
    old_stop = float(pos.stop)
    floor = trailing_floor(risk, pos)
    if pos.side == "LONG":
        candidate = max(old_stop, value)
        if candidate < floor:
            return False
        pos.stop = candidate
    else:
        candidate = min(old_stop, value)
        if candidate > floor:
            return False
        pos.stop = candidate
    return pos.stop != old_stop


def runner_exit_reason(pos, price: float, pnl_pct: float, snap: dict, cfg: dict) -> str | None:
    """Kâr koşusunda LONG satış / SHORT alış baskısı çıkışını doğrula."""
    if not cfg.get("kosan_kar", False) or price <= 0:
        return None
    min_profit = float(cfg.get("orderflow_min_kar_yuzde", 0.20))
    if pnl_pct < min_profit:
        return None
    peak = float(pos.peak or pos.entry)
    if peak <= 0:
        return None
    direction = 1.0 if pos.side == "LONG" else -1.0
    pullback_pct = (
        (peak - price) / peak * 100.0
        if pos.side == "LONG"
        else (price - peak) / peak * 100.0
    )
    min_pullback = float(cfg.get("orderflow_min_geri_cekilme_yuzde", 0.05))
    if pullback_pct < min_pullback:
        return None

    def number(key: str, default: float = 0.0) -> float:
        try:
            return float(snap.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    buy = number("absorption_buy_usdt", number("buy_usdt"))
    sell = number("absorption_sell_usdt", number("sell_usdt"))
    cvd = number("cvd_60s", number("cvd_slope"))
    aggressive = sell if pos.side == "LONG" else buy
    other = buy if pos.side == "LONG" else sell
    ratio = float(cfg.get("orderflow_orani", 1.5))
    min_usdt = float(cfg.get("orderflow_min_usdt", 1000.0))
    pressure = aggressive >= min_usdt and aggressive >= other * ratio
    pressure_name = "SATIŞ" if pos.side == "LONG" else "ALIŞ"
    absorption = str(snap.get("absorption", "YOK")).upper()
    pressure_absorbed = "SATIS_EMILIMI" if pos.side == "LONG" else "ALIS_EMILIMI"
    if absorption == pressure_absorbed:
        return None

    divergence = str(snap.get("cvd_divergence", "YOK")).upper()
    expected_divergence = "BEARISH" if pos.side == "LONG" else "BULLISH"
    if pressure and cvd * direction < 0:
        suffix = (
            f" + {expected_divergence} divergence"
            if divergence == expected_divergence
            else ""
        )
        return (
            f"{pos.side} {pressure_name} BASKISI + CVD dönüşü{suffix} "
            f"(${aggressive:,.0f}, zirve/dip %{pullback_pct:.2f})"
        )
    return None


def stagnant_adverse_exit_reason(
    pos,
    price: float,
    pnl_pct: float,
    hold_sec: float,
    snap: dict | None,
    supertrend_info: dict | None,
    combined: dict | None,
    cfg: dict | None,
) -> str | None:
    """Terste kilitli kalıp marjı rehin tutan pozisyonlar için yapısal bozulma çıkışı.

    Yalnız kâr kilidi almamış, belirlenen minimum süreyi doldurmuş ve ekside
    olan pozisyonlarda devreye girer; kârdaki runner pozisyonlarına dokunmaz.
    """
    conf = cfg if isinstance(cfg, dict) else {}
    if not conf.get("erken_bozulma_cikisi_aktif", False) or price <= 0:
        return None
    if getattr(pos, "locked_profit", False) or pnl_pct >= 0:
        return None

    min_age_sec = max(60.0, float(conf.get("erken_bozulma_min_dakika", 18.0)) * 60.0)
    if hold_sec < min_age_sec:
        return None

    min_loss_pct = abs(float(conf.get("erken_bozulma_min_zarar_yuzde", 0.25)))
    if pnl_pct > -min_loss_pct:
        return None

    direction = 1.0 if str(getattr(pos, "side", "")).upper() == "LONG" else -1.0
    hold_min = hold_sec / 60.0

    # 1) Birleşik sinyal skoru net biçimde pozisyonun tersine döndüyse
    comb = combined if isinstance(combined, dict) else {}
    try:
        total_score = float(comb.get("total", 0.0) or 0.0)
    except (TypeError, ValueError):
        total_score = 0.0
    reverse_th = abs(float(conf.get("erken_bozulma_ters_skor", 12.0)))
    if total_score * direction <= -reverse_th:
        return (
            f"ERKEN TREND BOZULMA ÇIKIŞI ({hold_min:.0f}dk, %{pnl_pct:+.2f}): "
            f"birleşik skor ters yöne döndü ({total_score:+.1f})"
        )

    flw = snap if isinstance(snap, dict) else {}

    def _num(key: str, default: float = 0.0) -> float:
        try:
            return float(flw.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    flow_score = _num("score", 0.0)

    # 2) 5m Supertrend ters yöne kırıldı VE canlı para akışı pozisyon aleyhine çalışıyorsa
    st = supertrend_info if isinstance(supertrend_info, dict) else {}
    try:
        st_dir = int(st.get("direction", 0) or 0)
    except (TypeError, ValueError):
        st_dir = 0
    if st_dir != 0 and st_dir != int(direction) and flow_score * direction <= -12.0:
        return (
            f"ERKEN TREND BOZULMA ÇIKIŞI ({hold_min:.0f}dk, %{pnl_pct:+.2f}): "
            f"Supertrend ters kırıldı + karşı akış ({flow_score:+.0f})"
        )

    # 3) Uzatılmış süre (ör. >=25dk) terste asılı kalıp karşı agresif order-flow + CVD yiyorsa
    ext_age_sec = max(min_age_sec, float(conf.get("erken_bozulma_uzatilan_dakika", 25.0)) * 60.0)
    if hold_sec >= ext_age_sec and pnl_pct <= -max(min_loss_pct, 0.40):
        buy = _num("absorption_buy_usdt", _num("buy_usdt"))
        sell = _num("absorption_sell_usdt", _num("sell_usdt"))
        cvd = _num("cvd_60s", _num("cvd_slope"))
        aggressive = sell if direction > 0 else buy
        other = buy if direction > 0 else sell
        if aggressive >= 500.0 and aggressive >= other * 1.35 and cvd * direction < 0:
            pressure_lbl = "SATIŞ" if direction > 0 else "ALIŞ"
            return (
                f"ERKEN TREND BOZULMA ÇIKIŞI ({hold_min:.0f}dk, %{pnl_pct:+.2f}): "
                f"rehin marj kurtarma — karşı {pressure_lbl} baskısı (${aggressive:,.0f})"
            )

    return None

