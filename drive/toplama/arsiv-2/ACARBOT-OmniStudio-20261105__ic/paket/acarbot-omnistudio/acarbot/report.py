"""SONUC.json → insan okunur Markdown rapor. Kârlılık iddiası üretmez."""
from __future__ import annotations

from typing import Any


def _pct(x: Any, digits: int = 2) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def build_report(r: dict[str, Any]) -> str:
    c = r.get("counters", {})
    cov = r.get("coverage", {})
    tot = cov.get("_totals", {})
    ex = r.get("execution", {})
    cmp_ = r.get("council_comparison", {})
    lines: list[str] = []
    a = lines.append

    a(f"# ACARBOT × OmniStudio — PAPER koşu raporu\n")
    a(f"**Durum:** `{r.get('status')}` · **Mod:** `{r.get('mode')}` · "
      f"**Strateji:** `{r.get('strategy')}` · **Konsey:** `{r.get('council_mode')}`  ")
    a(f"**Ölçülen süre:** {r.get('active_sec')} sn (hedef {r.get('requested_sec')} sn)  ")
    a(f"**Gerçek emir:** {r.get('real_orders')} · **Gerçek para onayı:** "
      f"`{r.get('real_money_approved')}`\n")
    a("> Bu rapor PAPER (sanal defter) araştırmasıdır. Kârlılık, gerçek dolum veya "
      "gerçek paraya uygunluk **kanıtı değildir**.\n")

    a("## 1. Sözleşme kapsamı (gerçek exchangeInfo)\n")
    a("| Pazar | Toplam | PAPER uygun | Reddedilen | Ana ret nedeni |")
    a("|---|--:|--:|--:|---|")
    for m, d in cov.items():
        if m.startswith("_"):
            continue
        top = next(iter(d.get("reasons", {})), "—")
        a(f"| {m} | {d['total']} | {d['executable']} | {d['rejected']} | {top} |")
    a(f"| **toplam** | **{tot.get('total')}** | **{tot.get('executable')}** | "
      f"**{tot.get('rejected')}** | kapsam **%{_pct(tot.get('coverage_pct'))}** |\n")
    a("Reddedilenler rastgele değil: X-PERP, vadeli/teslimat, USDC/USD marj, "
      "inverse, tokenize hisse/emtia (TRADIFI) ve durumu TRADING/live olmayanlar. "
      "Her birinin gerekçesi `OLCUM.json` ve `SONUC.json → coverage` içinde tek tek yazılı.\n")

    a("## 2. Ölçülen piyasa bağlamı\n")
    meas = r.get("measure", {})
    b = meas.get("breadth", {})
    a(f"- **Piyasa genişliği:** %{_pct((b.get('ratio') or 0) * 100, 1)} yukarı "
      f"({b.get('up')}↑ / {b.get('down')}↓, örnek {b.get('sample')}) — "
      f"{'ölçüldü' if b.get('available') else 'örneklem yetersiz'}")
    a(f"- **Akış (CVD) ölçülen sembol:** {meas.get('flow_symbols')} "
      f"(gerçek agresif alış/satış işlemleri)")
    a(f"- **Funding ölçülen sembol:** {meas.get('funding_symbols')}")
    a(f"- **Isınma:** {c.get('warmup_symbols')} sembol mum, "
      f"{c.get('warmup_ready')} tanesi ≥250 kapanmış mum\n")

    top = r.get("top_volume") or []
    if top:
        a("**Hacme göre ilk sözleşmeler (24s quote hacmi):**\n")
        a("| Pazar | Sembol | Hacim | ATR% | Makas bps | Akış baskısı | Funding |")
        a("|---|---|--:|--:|--:|--:|--:|")
        for t in top:
            a(f"| {t['market']} | {t['symbol']} | {t['quote_volume']:.0f} | "
              f"{_pct(t['atr_pct'], 3)} | {_pct(t.get('spread_bps'))} | "
              f"{_pct(t.get('flow_pressure'), 3)} | {_pct(t.get('funding_rate'), 5)} |")
        a("")

    a("## 3. PAPER defteri\n")
    a(f"- Başlangıç: **{ex.get('equity_start')}** → şimdi: **{ex.get('equity_now')}** "
      f"(gerçekleşen: {ex.get('realized_net')})")
    a(f"- Kapanan işlem: **{ex.get('closed_trades')}** · açık: {ex.get('open_positions')} · "
      f"kazanma: %{_pct(ex.get('win_rate_pct'), 1)} · ort. R: {ex.get('avg_r')}")
    a(f"- Ücretler: {ex.get('fees_paid')} · **funding: {ex.get('funding_net')}** "
      f"({ex.get('funding_events')} olay) · maks. düşüş: {ex.get('max_drawdown')}")
    a(f"- Devre kesici: `{ex.get('breaker')}` {ex.get('breaker_reason') or ''}\n")
    rej = ex.get("rejects") or {}
    if rej:
        a("**Defter ret nedenleri:** " + ", ".join(f"`{k}`×{v}" for k, v in rej.items()) + "\n")
    pm = ex.get("per_market") or {}
    if pm:
        a("| Pazar | İşlem | Net | Kazanan |")
        a("|---|--:|--:|--:|")
        for m, d in pm.items():
            a(f"| {m} | {d['trades']} | {d['net']} | {d['wins']} |")
        a("")

    a("## 4. Konsey: ölçüm var / yok karşılaştırması\n")
    if "error" in cmp_:
        a(f"Konsey karşılaştırması çalışmadı: `{cmp_['error']}`\n")
    else:
        a(f"- Değerlendirilen aday: {cmp_.get('evaluated')}")
        a(f"- **Ölçülmüş bağlamla onaylanan:** {cmp_.get('measured_approved')}")
        a(f"- **Maildeki varsayımla (akış=0, genişlik=0, 15dk=uyumsuz) onaylanan:** "
          f"{cmp_.get('assumed_approved')}")
        a(f"- **Kararı değişen aday:** {cmp_.get('decisions_differ')}\n")
        a(f"> {cmp_.get('note', '')}\n")

    a("## 5. Sayaçlar\n")
    keep = ("bars_evaluated", "signals", "opened", "council_calls", "warmup_ready",
            "candle_cycles", "flow_ok", "funding_ok", "quote_refresh_ok")
    a("| Sayaç | Değer |")
    a("|---|--:|")
    for k in keep:
        if k in c:
            a(f"| {k} | {c[k]} |")
    rej = {k: v for k, v in c.items() if k.startswith("reject_")}
    if rej:
        a("\n**Ret sayaçları:**\n")
        a("| Neden | Adet |")
        a("|---|--:|")
        for k, v in sorted(rej.items(), key=lambda kv: -kv[1]):
            a(f"| {k[7:]} | {v} |")
    a("")

    ws = r.get("ws_stats") or {}
    if ws:
        a("## 6. WebSocket akışı\n")
        a("| Pazar | Bağlantı | Güncelleme | Kapanmış mum | Medyan gecikme | En uzun |")
        a("|---|--:|--:|--:|--:|--:|")
        for m, s in ws.items():
            closed = s.get("closed", 0)
            med = (s.get("latency_sum_ms", 0) / closed) if closed else 0
            a(f"| {m} | {s.get('connections', 0)} | {s.get('updates', 0)} | {closed} | "
              f"{med:.0f} ms | {s.get('latency_max_ms', 0)} ms |")
        a("")

    a("## 7. Pazar sağlığı\n")
    a("| Pazar | Erişim | REST ok | REST hata | Son hata |")
    a("|---|---|--:|--:|---|")
    for m, h in (r.get("market_health") or {}).items():
        a(f"| {m} | {'✅' if h['reachable'] else '❌ UNREACHABLE'} | {h['rest_ok']} | "
          f"{h['rest_fail']} | {h['last_error'][:60]} |")
    a("")

    a("## 8. Dürüstlük sınırları\n")
    for s in [
        "Gerçek emir yolu yoktur; `real_orders = 0`.",
        "PAPER dolumu taker fiyatı + varsayımsal kayma ile modellenir; emir defteri "
        "derinliği ve kuyruk önceliği bilinmez.",
        "Likidasyon fiyatı `1/kaldıraç − bakım marjı` yaklaşımıdır; borsanın gerçek "
        "tasfiye motoru ve kısmi tasfiye kuralları modellenmedi.",
        "Funding, koşu sırasında borsanın bildirdiği oranla işlenir; gelecekteki "
        "oranlar değişebilir. Oran alınamayan sembollerde funding 0 varsayılmaz, "
        "giriş reddedilir (`FUNDING_UNKNOWN`).",
        "COIN-M hacmi USD'ye yaklaşık çevrilir (etiketli tahmin); ters sözleşme "
        "PAPER hesabı bu sürümde bağlı değildir.",
        "Kısa örneklem ve tek koşu kârlılık kanıtı değildir.",
        "Konsey anahtarsız modda RULE_BASED_QUANT'tır; YZ çağrısı yapılmadı "
        "(`ai_generated=false`).",
    ]:
        a(f"- {s}")
    a("")
    if r.get("errors"):
        a("## 9. Hatalar (ilk 25)\n")
        for e in r["errors"]:
            a(f"- `{e}`")
        a("")
    return "\n".join(lines)
