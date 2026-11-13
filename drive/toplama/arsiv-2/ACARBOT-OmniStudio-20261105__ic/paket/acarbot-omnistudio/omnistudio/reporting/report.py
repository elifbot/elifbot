"""Koşu raporları — SONUC.json'dan Markdown + HTML dashboard üretimi."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def markdown_report(result: dict[str, Any]) -> str:
    r = result
    ex = r.get("execution", {})
    eq = ex.get("equity", {})
    risk = ex.get("risk", {})
    co = r.get("ai_council", {})
    md = r.get("market_data", {})
    ti = r.get("timing", {})
    cnt = r.get("counters", {})
    L: list[str] = []
    A = L.append
    A(f"# AI OmniStudio — Koşu Raporu `{r.get('run_id')}`\n")
    A(f"**Sürüm:** {r.get('version')} · **Mod:** {r.get('mode')} · "
      f"**Durum:** `{r.get('run_status')}`\n")
    A("> **Gerçek borsa emri gönderilmedi.** Veri gerçek piyasa verisidir; "
      "defter sanaldır. Bu rapor kârlılık kanıtı değildir.\n")
    if r.get("filters_relaxed"):
        A("> ⚠️ **TANI KOŞUSU — DOĞAL KANIT DEĞİL.** Profil: "
          f"`{r.get('profile')}`. Eşikler, yalnız pozisyon aç/kapat yaşam "
          "döngüsünü gerçek veri üzerinde doğrulamak için gevşetildi. "
          "Bu koşunun işlem sayısı, PnL'i veya isabet oranı strateji "
          "değerlendirmesinde KULLANILAMAZ. Doğal üretim eşikleri için "
          "`configs/default.json` ile koşun.\n")
    else:
        A("> **Profil:** `natural` — üretim eşikleri, filtre gevşetmesi yok.\n")

    A("## 1. Süre protokolü\n")
    A("| Ölçüm | Değer |")
    A("|---|---:|")
    A(f"| Toplam monotonic (s) | {ti.get('total_monotonic_sec')} |")
    A(f"| Aktif pencere (s) | {ti.get('active_sec_estimated')} |")
    A(f"| Drenaj (s) | {ti.get('drain_sec')} |")
    A(f"| Aktif pencere tamamlandı | {ti.get('active_window_completed')} |")
    A(f"\n{ti.get('note','')}\n")

    A("## 2. Karar hattı\n")
    A("| Sayaç | Değer |")
    A("|---|---:|")
    for k in ("ticks", "signals", "decisions", "accepted", "rejected",
              "council_vetoes", "risk_blocks", "quote_ok", "quote_fail"):
        A(f"| {k} | {cnt.get(k, 0)} |")
    A("")
    gates = r.get("policy", {}).get("gate_counts", {})
    if gates:
        A("### Kapı ret dağılımı\n")
        A("| Kapı | Ret |")
        A("|---|---:|")
        for k, v in list(gates.items())[:20]:
            A(f"| `{k}` | {v} |")
        A("")

    A("## 3. PAPER icra ve finansal fotoğraf\n")
    A("| Ölçüm | Değer |")
    A("|---|---:|")
    A(f"| Kapanan işlem | {ex.get('closed_trades', 0)} |")
    A(f"| Kapanmış net (USDT) | {ex.get('closed_net_total', 0)} |")
    A(f"| Gerçekleşen net | {risk.get('realized_net', 0)} |")
    A(f"| Ödenen ücret | {risk.get('fees_paid', 0)} |")
    A(f"| Açık unrealized | {eq.get('unrealized', 0)} |")
    A(f"| Toplam equity | {eq.get('total_equity', 0)} |")
    A(f"| Kazanma oranı (%) | {risk.get('win_rate_pct', 0)} |")
    A(f"| Maks drawdown | {risk.get('max_drawdown', 0)} |")
    A(f"| Ortalama tutma (s) | {ex.get('mean_hold_sec', 0)} |")
    A(f"\n{eq.get('note','')}\n")
    reasons = ex.get("exit_reasons", {})
    if reasons:
        A("### Çıkış nedenleri\n")
        for k, v in reasons.items():
            A(f"- `{k}`: {v}")
        A("")

    A("## 4. 20 YZ konseyi\n")
    A(f"**Mod:** `{co.get('mode')}` · **Üye:** {co.get('members')} · "
      f"**Anahtarlı:** {co.get('live_members')}\n")
    A(f"{co.get('honesty_note','')}\n")
    st = co.get("stats", {})
    if st:
        A("| Sayaç | Değer |")
        A("|---|---:|")
        for k, v in st.items():
            A(f"| {k} | {v} |")
        A("")

    A("## 5. Gerçek veri kaynakları\n")
    A(f"Erişilebilir: {', '.join(md.get('reachable', [])) or 'YOK'}\n")
    if md.get("unreachable"):
        A(f"Erişilemeyen: {', '.join(md['unreachable'])}\n")
    A("| Uç | Erişim | HTTP | WS mesaj | Reconnect | REST ok/fail |")
    A("|---|---|---:|---:|---:|---|")
    for v, h in (md.get("venues") or {}).items():
        A(f"| {v} | {'OK' if h.get('reachable') else 'YOK'} | {h.get('http_status')} | "
          f"{h.get('ws_messages',0)} | {h.get('ws_reconnects',0)} | "
          f"{h.get('rest_ok',0)}/{h.get('rest_fail',0)} |")
    A("")

    A("## 6. Süreklilik ve görev denetimi\n")
    cn = r.get("continuity", {})
    A(f"- Boşluk sayısı: **{cn.get('gap_count',0)}**")
    A(f"- Maks poll gecikmesi: {cn.get('max_poll_delay_sec',0)}s")
    A(f"- Maks saat sapması: {cn.get('max_clock_skew_sec',0)}s")
    sup = r.get("supervision", {})
    A(f"- Görev hataları: `{sup.get('task_failures') or {}}`")
    A(f"- Alarm sayısı: {sup.get('alarm_count',0)}\n")

    A("## 7. Ölçülen süreler\n")
    A("| İşlem | Çağrı | Toplam s | Maks ms |")
    A("|---|---:|---:|---:|")
    for k, t in (r.get("timers") or {}).items():
        A(f"| {k} | {t.get('calls',0)} | {t.get('total_sec',0)} | {t.get('max_ms',0)} |")
    A("\nBu süreler kapsayıcı duvar süresidir; CPU profili değildir. "
      "İç içe ölçümler TOPLANMAZ.\n")

    A("## 8. Dürüstlük beyanı\n")
    h = r.get("honesty", {})
    A(f"- Veri: `{h.get('data')}`")
    A(f"- Emir: `{h.get('orders')}`")
    A(f"- YZ modu: `{h.get('ai_mode')}`")
    A(f"- Kârlılık iddiası: **{h.get('profitability_claim')}**")
    A(f"\n{h.get('note','')}\n")
    return "\n".join(L)


def write_reports(run_dir: Path | str, result: dict[str, Any]) -> dict[str, str]:
    d = Path(run_dir)
    d.mkdir(parents=True, exist_ok=True)
    md = markdown_report(result)
    (d / "RAPOR.md").write_text(md, encoding="utf-8")
    (d / "SONUC.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": str(d / "RAPOR.md"), "json": str(d / "SONUC.json")}
