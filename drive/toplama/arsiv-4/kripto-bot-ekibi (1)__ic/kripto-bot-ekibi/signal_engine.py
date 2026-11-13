"""Sinyal motoru: teknik göstergeler + futures long/short skorlaması.

Skor bileşenleri (maks. ±82):
  EMA trend (±25) + MACD (±15) + RSI (±12) + Funding (±12) + OI (±10) + Hacim (±8)
Karar: |skor|>=45 STRONG, >=20 normal yön, altı NÖTR.
"""
import asyncio

import market_data as md

MAX_SCORE = 82


# ------------------------------------------------------------ göstergeler
def ema(vals: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out, prev = [], vals[0]
    for v in vals:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(closes: list[float], n: int = 14) -> list[float]:
    gains, losses = 0.0, 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out = [50.0] * n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def macd(closes: list[float]) -> list[float]:
    e12, e26 = ema(closes, 12), ema(closes, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = ema(line, 9)
    return [a - b for a, b in zip(line, sig)]


def atr(highs, lows, closes, n: int = 14) -> list[float]:
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    a = sum(trs[:n]) / n
    out = [a] * n
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
        out.append(a)
    return out


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


# ------------------------------------------------------------ sinyal üretimi
async def generate_signal(symbol: str, interval: str = "60") -> dict:
    """Bir sembol için tam long/short sinyal raporu üret (dict)."""
    klines, snap, oi = await asyncio.gather(
        md.fetch_klines(symbol, interval, 200),
        md.fetch_snapshot(symbol),
        md.fetch_oi_series(symbol, 25),
    )
    if len(klines) < 60:
        raise ValueError(f"{symbol}: yeterli mum verisi yok")

    closes = [k["c"] for k in klines]
    highs = [k["h"] for k in klines]
    lows = [k["l"] for k in klines]
    price = closes[-1]

    e9, e21, e50 = ema(closes, 9)[-1], ema(closes, 21)[-1], ema(closes, 50)[-1]
    r_now = rsi(closes)[-1]
    hist = macd(closes)
    h_now, h_prev = hist[-1], hist[-2]
    a_now = atr(highs, lows, closes)[-1]

    score, reasons = 0, []

    # 1) EMA trend (±25)
    if price > e50 and e9 > e21 > e50:
        score += 25
        reasons.append(("✅", "Tam boğa dizilimi: fiyat > EMA50, EMA9>21>50 (+25)"))
    elif price < e50 and e9 < e21 < e50:
        score -= 25
        reasons.append(("❌", "Tam ayı dizilimi: fiyat < EMA50, EMA9<21<50 (−25)"))
    elif e9 > e21:
        score += 12
        reasons.append(("✅", "Kısa vadeli trend yukarı (EMA9>EMA21, +12)"))
    elif e9 < e21:
        score -= 12
        reasons.append(("❌", "Kısa vadeli trend aşağı (EMA9<EMA21, −12)"))

    # 2) MACD (±15)
    if h_now > 0 and h_now > h_prev:
        score += 15
        reasons.append(("✅", "MACD histogram pozitif ve güçleniyor (+15)"))
    elif h_now > 0:
        score += 8
        reasons.append(("🟡", "MACD pozitif ama zayıflıyor (+8)"))
    elif h_now < 0 and h_now < h_prev:
        score -= 15
        reasons.append(("❌", "MACD histogram negatif ve derinleşiyor (−15)"))
    elif h_now < 0:
        score -= 8
        reasons.append(("🟡", "MACD negatif ama toparlanıyor (−8)"))

    # 3) RSI (±12)
    if r_now > 70:
        score -= 12
        reasons.append(("⚠️", f"RSI {r_now:.0f} — aşırı alım, düzeltme riski (−12)"))
    elif r_now >= 55:
        score += 6
        reasons.append(("✅", f"RSI {r_now:.0f} — boğa bölgesi (+6)"))
    elif r_now < 30:
        score += 12
        reasons.append(("✅", f"RSI {r_now:.0f} — aşırı satım, tepki alımı olası (+12)"))
    elif r_now <= 45:
        score -= 6
        reasons.append(("❌", f"RSI {r_now:.0f} — ayı bölgesi (−6)"))

    # 4) Funding (±12) — ters yön sinyali
    f = snap.get("funding", 0.0)
    if f > 0.0005:
        score -= 12
        reasons.append(("⚠️", f"Funding {f*100:.3f}% — longlar kalabalık, sıfırlanma riski (−12)"))
    elif f > 0.0001:
        score -= 4
        reasons.append(("🟡", f"Funding {f*100:.3f}% — longlar ödüyor (−4)"))
    elif f < -0.0005:
        score += 12
        reasons.append(("✅", f"Funding {f*100:.3f}% — shortlar kalabalık, squeeze potansiyeli (+12)"))
    elif f < -0.0001:
        score += 4
        reasons.append(("🟡", f"Funding {f*100:.3f}% — shortlar ödüyor (+4)"))

    # 5) Açık pozisyon (OI) (±10)
    oi_chg = _pct(oi[-1][1], oi[0][1]) if len(oi) >= 2 else 0.0
    deg24 = snap.get("deg24", 0.0)
    if oi and oi_chg > 3 and deg24 > 0:
        score += 10
        reasons.append(("✅", f"OI 24s +{oi_chg:.1f}% ve fiyat artıyor — sağlıklı yükseliş (+10)"))
    elif oi and oi_chg > 3 and deg24 < 0:
        score -= 10
        reasons.append(("❌", f"OI 24s +{oi_chg:.1f}% ama fiyat düşüyor — yeni shortlar (−10)"))
    elif oi and oi_chg < -3 and deg24 > 0:
        score -= 6
        reasons.append(("🟡", f"OI 24s {oi_chg:.1f}% — yükseliş short kapanışından, zayıf taban (−6)"))
    elif oi and oi_chg < -3 and deg24 < 0:
        score += 6
        reasons.append(("🟡", f"OI 24s {oi_chg:.1f}% — long kapanış baskısı azalıyor (+6)"))

    # 6) Hacim patlaması (±8)
    if len(klines) >= 23:
        v_last3 = sum(k["v"] for k in klines[-3:]) / 3
        v_prev20 = sum(k["v"] for k in klines[-23:-3]) / 20
        if v_prev20 and v_last3 / v_prev20 > 1.5:
            up = closes[-1] > klines[-1]["o"]
            score += 8 if up else -8
            reasons.append(("🔥", "Hacim patlaması " + ("alıcı lehine (+8)" if up else "satıcı lehine (−8)")))

    # ---- karar ----
    if score >= 45:
        side, emoji = "STRONG LONG", "🟢🟢"
    elif score >= 20:
        side, emoji = "LONG", "🟢"
    elif score <= -45:
        side, emoji = "STRONG SHORT", "🔴🔴"
    elif score <= -20:
        side, emoji = "SHORT", "🔴"
    else:
        side, emoji = "NÖTR", "⚪"

    is_long = score >= 0
    sl = price - 1.5 * a_now if is_long else price + 1.5 * a_now
    tp1 = price + 1.5 * a_now if is_long else price - 1.5 * a_now
    tp2 = price + 2.5 * a_now if is_long else price - 2.5 * a_now
    atr_pct = a_now / price if price else 0
    leverage = _clamp(int(0.015 / atr_pct) if atr_pct else 1, 1, 5)
    rr = abs(tp2 - price) / abs(price - sl) if price != sl else 0.0

    return {
        "sembol": symbol, "taraf": side, "emoji": emoji,
        "skor": score, "max_skor": MAX_SCORE, "guven": round(abs(score) / MAX_SCORE * 100),
        "fiyat": price, "deg24": deg24, "rsi": r_now,
        "ema9": e9, "ema21": e21, "ema50": e50, "macd_hist": h_now, "atr": a_now,
        "funding": f, "oi_deg": oi_chg, "hacim_usdt": snap.get("hacim_usdt", 0),
        "kaynak": snap.get("kaynak", "-"),
        "giris": price, "stop": sl, "tp1": tp1, "tp2": tp2,
        "kaldirac": leverage, "rr": rr,
        "nedenler": reasons, "interval": interval,
    }


def fmt_num(v: float, nd: int = 2) -> str:
    """Türkçe biçim: 75.907,60"""
    s = f"{v:,.{nd}f}"
    return s.replace(",", "@").replace(".", ",").replace("@", ".")


def format_signal(sig: dict) -> str:
    """Telegram HTML raporu."""
    e = sig["emoji"]
    lines = [
        f"{e} <b>{sig['sembol']} — {sig['taraf']} SİNYALİ</b>",
        f"📊 Skor: <b>{sig['skor']:+d}</b> / ±{sig['max_skor']} • Güven: <b>%{sig['guven']}</b>",
        "",
        f"💰 Fiyat: <b>{fmt_num(sig['fiyat'])}</b> USDT (24s: {sig['deg24']:+.2f}%)",
        f"🕐 Zaman dilimi: {sig['interval']}m • Veri: {sig['kaynak']}",
        "",
        "🎯 <b>İşlem Planı</b>",
        f"• Giriş: <code>{fmt_num(sig['giris'])}</code>",
        f"• 🛑 Stop-Loss: <code>{fmt_num(sig['stop'])}</code>",
        f"• ✅ TP1: <code>{fmt_num(sig['tp1'])}</code> (1R)",
        f"• 🚀 TP2: <code>{fmt_num(sig['tp2'])}</code> (R:R ≈ {sig['rr']:.2f})",
        f"• ⚙️ Önerilen kaldıraç: <b>{sig['kaldirac']}x</b> (maks.)",
        "",
        f"📉 RSI: {sig['rsi']:.0f} • Funding: {sig['funding']*100:+.3f}% • OI 24s: {sig['oi_deg']:+.1f}%",
        f"💼 24s hacim: {fmt_num(sig['hacim_usdt'], 0)} USDT",
        "",
        "🧠 <b>Gerekçeler</b>",
    ]
    for ikon, txt in sig["nedenler"]:
        lines.append(f"  {ikon} {txt}")
    if not sig["nedenler"]:
        lines.append("  — Göze çarpan güçlü sinyal yok, piyasa kararsız —")
    if sig["taraf"] != "NÖTR":
        lines += ["",
                  f"💡 <i>1000 USDT sermayede %1 risk örneği: ~{fmt_num(1000 * 0.01 / max(abs(sig['giris'] - sig['stop']), 1e-9) * sig['giris'], 0)} USDT pozisyon.</i>"]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def format_scan_row(sig: dict) -> str:
    return (f"{sig['emoji']} <b>{sig['sembol']}</b> — {sig['taraf']} "
            f"({sig['skor']:+d}) @ {fmt_num(sig['fiyat'])}")
