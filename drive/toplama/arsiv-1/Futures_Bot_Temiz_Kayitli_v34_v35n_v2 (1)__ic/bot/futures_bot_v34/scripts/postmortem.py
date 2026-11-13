#!/usr/bin/env python3
"""
scripts/postmortem.py — Oturum sonrası analiz ("neleri yanlış yapmışız").

Girdi:
  --diag       logs/diagnostics.csv   (tur bazında gösterge kaydı)
  --trades     live_trades.csv        (kapanan işlemler)
  --log        logs/live_run.log      (tur/heartbeat logu)
  --report     live_report.txt        (botun yazdığı PnL raporu)

Çıktı: konsola + `--out` dosyasına yapılandırılmış bir metin raporu.

Bu araç hiçbir şeyi "kârlı" diye yorumlamaz; yalnızca ÖLÇER ve
TESPİT + ÖNERİ olarak listeler.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import statistics
from collections import Counter, defaultdict


# ---------------------------------------------------------------------------
# Okuma yardımcıları
# ---------------------------------------------------------------------------
def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _f(v: str | None) -> float | None:
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Analiz bölümleri
# ---------------------------------------------------------------------------
def section_cycles(log_text: str) -> list[str]:
    """Kaç tur atıldı, log sağlıklı mı?"""
    lines = [ln for ln in log_text.splitlines() if "tur |" in ln]
    out = [f"## 1. Oturum sağlığı", ""]
    if not lines:
        out.append("⚠️ Log'da hiç tur satırı yok — oturum hiç dönmemiş olabilir.")
        return out

    per_symbol: Counter = Counter()
    times = []
    for ln in lines:
        m = re.search(r"tur \| ([\w-]+):([\w-]+) \| mum=(\d+) \| fiyat=([\d.]+) \| açık=(\d+) \| bakiye=([\d.]+)", ln)
        if not m:
            continue
        per_symbol[f"{m.group(1)}:{m.group(2)}"] += 1
        ts = ln.split(" ")[0:2]
        times.append(" ".join(ts))

    out.append(f"- Toplam tur satırı: **{len(lines)}**")
    for sym, n in per_symbol.most_common():
        out.append(f"  - `{sym}`: {n} tur")
    if times:
        out.append(f"- İlk tur: `{times[0]}` · Son tur: `{times[-1]}`")
    if len(per_symbol) and min(per_symbol.values()) < max(per_symbol.values()) * 0.8:
        out.append(
            "  ⚠️ Semboller arasında tur sayısı dengesiz — bir sembol veri hatası "
            "verip atlanmış olabilir (log'da `veri alınamadı` ara)."
        )
    return out


def section_trades(trades: list[dict]) -> list[str]:
    out = ["", "## 2. İşlemler", ""]
    if not trades:
        out.append("Hiç kapanmış işlem yok.")
        return out

    pnls = [_f(t.get("realized_pnl")) or 0.0 for t in trades]
    fees = [(_f(t.get("entry_fee")) or 0.0) + (_f(t.get("exit_fee")) or 0.0) for t in trades]
    reasons = Counter(t.get("reason", "?") for t in trades)
    sides = Counter(t.get("side", "?") for t in trades)

    wins = [p for p in pnls if p > 0]
    out.append(f"- Kapanan işlem: **{len(trades)}**")
    out.append(f"- Net PnL: **{sum(pnls):+.4f} USDT**")
    out.append(f"- Toplam komisyon: **{sum(fees):.4f} USDT** "
               f"(PnL'in %{abs(sum(fees) / sum(pnls) * 100) if sum(pnls) else 0:.0f}'i)")
    out.append(f"- Kazanma oranı: **{len(wins) / len(trades) * 100:.1f}%** "
               f"({len(wins)}/{len(trades)})")
    out.append(f"- Yön dağılımı: " + ", ".join(f"{k}={v}" for k, v in sides.items()))
    out.append(f"- Çıkış sebepleri: " + ", ".join(f"{k}={v}" for k, v in reasons.most_common()))

    # Komisyon işlem başına marja oranı
    margins = [_f(t.get("margin")) or 0.0 for t in trades]
    if margins and sum(margins) > 0:
        avg_fee_pct = sum(fees) / sum(margins) * 100
        out.append(f"- Ortalama komisyon / marj: **%{avg_fee_pct:.3f}**")
        if avg_fee_pct > 0.15:
            out.append(
                "  ⚠️ Komisyon marja göre yüksek: kaldıraç düşük ya da marj küçük. "
                "Komisyonu aşacak minimum fiyat hareketi = "
                f"~%{avg_fee_pct:.3f} × kaldıraç."
            )

    # kötü işlemler
    worst = sorted(zip(pnls, trades), key=lambda x: x[0])[:3]
    if worst and worst[0][0] < 0:
        out.append("- En kötü 3 işlem:")
        for p, t in worst:
            out.append(
                f"  - {t.get('symbol')} {t.get('side')} {p:+.4f} USDT · "
                f"giriş {t.get('entry_price')} → çıkış {t.get('exit_price')} · {t.get('reason')}"
            )
    return out


def section_diagnostics(diag: list[dict]) -> list[str]:
    out = ["", "## 3. Sinyal tanılaması (hangi koşul bloke etti)", ""]
    if not diag:
        out.append("Tanılama kaydı yok (`scripts/diag_watch.py` çalışmamış).")
        return out

    blockers = Counter(r.get("blocker", "?") for r in diag)
    total = len(diag)
    out.append(f"- Kayıt sayısı: **{total}** satır (sembol × tur)")
    out.append("")
    out.append("| Engel | Satır | Pay |")
    out.append("|---|---:|---:|")
    for k, v in blockers.most_common():
        out.append(f"| `{k}` | {v} | %{v / total * 100:.0f} |")

    # Sinyal üretilme oranı
    for col, label in (
        ("trend_signal", "Aday A (trend)"),
        ("meanrev_signal", "Aday B (ortalamaya dönüş)"),
        ("squeeze_signal", "Aday C (sıkışma)"),
    ):
        vals = Counter(r.get(col, "?") for r in diag)
        ready = vals.get("LONG", 0) + vals.get("SHORT", 0)
        out.append("")
        out.append(f"**{label}**: {ready}/{total} turda sinyal (%{ready / total * 100:.0f}) "
                   f"— {dict(vals)}")

    # ADX dağılımı
    adx_vals = [v for v in (_f(r.get("adx")) for r in diag) if v is not None]
    if adx_vals:
        out.append("")
        out.append(
            f"**ADX**: ort {statistics.mean(adx_vals):.1f} · "
            f"min {min(adx_vals):.1f} · maks {max(adx_vals):.1f} · "
            f"eşik(20) üstünde %{sum(1 for a in adx_vals if a >= 20) / len(adx_vals) * 100:.0f}"
        )

    # Ribbon dağılımı
    rib = Counter(r.get("ema_ribbon", "?") for r in diag)
    out.append(f"**EMA şeridi**: {dict(rib)}")

    # hacim z
    vz = [v for v in (_f(r.get("volume_z")) for r in diag) if v is not None]
    if vz:
        out.append(
            f"**Hacim z-skoru**: ort {statistics.mean(vz):.2f} · maks {max(vz):.2f} · "
            f"eşik(1.5) üstünde %{sum(1 for v in vz if v >= 1.5) / len(vz) * 100:.0f}"
        )
    return out


def section_findings(trades: list[dict], diag: list[dict], log_text: str) -> list[str]:
    out = ["", "## 4. Tespitler ve öneriler", ""]
    findings: list[tuple[str, str]] = []

    # 1) Hiç işlem açılmadı mı?
    if not trades:
        if diag:
            blockers = Counter(r.get("blocker", "?") for r in diag)
            top, _ = blockers.most_common(1)[0]
            findings.append((
                "İşlem açılmadı",
                f"Tek neden `{top}`. Eşik bu piyasa rejiminde fazla sıkı olabilir; "
                "eşiği düşürmeden önce aynı pencerede eşik duyarlılık tablosu çıkarılmalı.",
            ))
        else:
            findings.append(("İşlem açılmadı", "Neden bilinmiyor: tanılama kaydı yok."))

    # 2) Ters sinyal çıkışları
    reasons = Counter(t.get("reason", "?") for t in trades)
    ters = reasons.get("TERS_SINYAL", 0)
    if ters and ters >= max(1, len(trades) // 2):
        findings.append((
            "İşlemlerin çoğu TERS_SINYAL ile kapanmış",
            "Aday stratejiler aynı mumda birbirine zıt sinyal üretiyor olabilir "
            "(ör. A LONG iken B SHORT). Composite katmanında aynı anda zıt sinyal "
            "geldiğinde pozisyon açılmaması kuralı zaten var; ancak AÇIK pozisyon "
            "zıt sinyalle kapatılıyor. Öneri: ters sinyalin kaç mum ısrarla "
            "sürdüğünü şart koş (debounce).",
        ))

    # 3) Komisyon baskısı
    pnls = [_f(t.get("realized_pnl")) or 0.0 for t in trades]
    fees = [(_f(t.get("entry_fee")) or 0.0) + (_f(t.get("exit_fee")) or 0.0) for t in trades]
    if fees and pnls and sum(pnls) < 0 and sum(fees) > abs(sum(pnls)):
        findings.append((
            "Komisyon, zararın kaynağından büyük",
            f"Net {sum(pnls):+.4f} USDT, komisyon {sum(fees):.4f} USDT. "
            "Yani strateji brütte ~başabaş; kaybı komisyon yaratıyor. Öneri: "
            "daha az işlem (daha sıkı giriş) veya daha uzun tutma süresi.",
        ))

    # 4) session_end zorunlu kapanış
    if reasons.get("session_end"):
        findings.append((
            "Açık pozisyon session_end'de zorla kapatıldı",
            f"{reasons['session_end']} işlem süre dolduğu için kapatıldı; bunlar "
            "sinyalle değil zamanla çıktı. Öneri: oturum sonu kapanışını ayrı "
            "metrik olarak raporla, strateji performansına KATMA.",
        ))

    # 5) veri hatası var mı
    if "veri alınamadı" in log_text or "451" in log_text:
        n = log_text.count("veri alınamadı")
        findings.append((
            "Veri çekme hatası",
            f"Log'da {n} kez veri hatası var (bölgesel engel olabilir). "
            "Etkilenen sembol o turda değerlendirilmedi; bu, sinyal sayısını "
            "olduğundan az gösterir.",
        ))

    # 6) ADX eşiği
    adx_vals = [v for v in (_f(r.get("adx")) for r in diag) if v is not None]
    if adx_vals:
        pct_ok = sum(1 for a in adx_vals if a >= 20) / len(adx_vals) * 100
        if pct_ok < 40:
            findings.append((
                f"ADX eşiği (20) çoğu turda aşılamıyor (%{pct_ok:.0f})",
                "Bu piyasa rejimi yatay. Öneri: eşiği düşürmek yerine rejim "
                "filtresi ekle (ADX<20 iken aday B/C'ye ağırlık ver).",
            ))

    if not findings:
        findings.append(("Belirgin bir hata deseni yok", "Örneklem küçük olabilir."))

    for i, (title, detail) in enumerate(findings, 1):
        out.append(f"**{i}. {title}**")
        out.append(f"   {detail}")
        out.append("")
    return out


def section_verdict(trades: list[dict]) -> list[str]:
    out = ["", "## 5. Hüküm", ""]
    n = len(trades)
    if n == 0:
        out.append("Örneklem yok — strateji hakkında hiçbir yorum yapılamaz.")
    elif n < 30:
        out.append(
            f"Örneklem **{n} işlem**: istatistiksel olarak anlamsız. "
            f"Sharpe bilinçli olarak bastırıldı (eşik 30). "
            f"Elde edilen PnL bir performans göstergesi DEĞİLDİR."
        )
    else:
        out.append(f"Örneklem **{n} işlem** — hâlâ tek oturum; gün/hafta ölçeğinde tekrar gerekir.")
    out.append("")
    out.append("Bu rapor paper simülasyonudur; yatırım tavsiyesi değildir.")
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Oturum sonrası analiz")
    ap.add_argument("--diag", default="logs/diagnostics.csv")
    ap.add_argument("--trades", default="live_trades.csv")
    ap.add_argument("--log", default="logs/live_run.log")
    ap.add_argument("--report", default="live_report.txt")
    ap.add_argument("--out", default="logs/postmortem.md")
    args = ap.parse_args()

    diag = read_csv(args.diag)
    trades = read_csv(args.trades)
    log_text = read_text(args.log)

    parts = [
        "# Oturum Sonrası Analiz (post-mortem)",
        "",
        f"- Tanılama dosyası: `{args.diag}` ({len(diag)} satır)",
        f"- İşlem dosyası: `{args.trades}` ({len(trades)} işlem)",
        f"- Log: `{args.log}`",
        "",
    ]
    parts += section_cycles(log_text)
    parts += section_trades(trades)
    parts += section_diagnostics(diag)
    parts += section_findings(trades, diag, log_text)
    parts += section_verdict(trades)

    if os.path.exists(args.report):
        parts += ["", "## 6. Botun kendi raporu (özet)", "", "```",
                  read_text(args.report).strip()[:2000], "```"]

    text = "\n".join(parts)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"\n[yazıldı] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
