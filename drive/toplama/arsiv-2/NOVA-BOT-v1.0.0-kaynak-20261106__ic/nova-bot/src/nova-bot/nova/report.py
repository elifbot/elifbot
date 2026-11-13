"""NOVA-BOT rapor üreticisi — SONUC.json → Markdown. Kârlılık iddiası üretmez."""
from __future__ import annotations

from typing import Any


def _f(v: Any, d: int = 2) -> str:
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def yaz_rapor(r: dict[str, Any]) -> str:
    b = r.get("book", {})
    s = r.get("stats", {})
    L: list[str] = []
    a = L.append
    a("# NOVA-BOT — canlı PAPER test raporu\n")
    a(f"**Durum:** `{r.get('status')}` · **Mod:** `{r.get('mode')}` · "
      f"**Sürüm:** {r.get('version')}  ")
    a(f"**Ölçülen süre:** {r.get('active_sec')} sn (hedef {r.get('requested_sec')} sn) · "
      f"**Sembol:** {r.get('symbols')}  ")
    a(f"**Gerçek emir:** {r.get('real_orders')} · **Dış model/YZ çağrısı:** yok\n")
    a("> PAPER: borsaya emir gönderilmedi, özel API anahtarı kullanılmadı. "
      "Bu rapor kârlılık kanıtı değildir.\n")

    a("## 1. Veri akışı\n")
    a("| Ölçüm | Değer |")
    a("|---|--:|")
    for k, label in (("bars", "Değerlendirilen kapanmış 1m mum"),
                     ("ws_closed", "WS'ten gelen kapanmış mum"),
                     ("ws_updates", "WS mum güncellemesi"),
                     ("ws_closed_5s", "Kapanıştan 5 sn içinde alınan"),
                     ("ws_reconnects", "Yeniden bağlanma"),
                     ("ws_errors", "WS hatası"),
                     ("warm_ok", "Isınması tamamlanan sembol"),
                     ("skip_stale", "Eski mum nedeniyle atlanan"),
                     ("funding_ok", "Funding oranı alınan"),
                     ("funding_missing", "Funding oranı alınamayan")):
        if k in s:
            a(f"| {label} | {s[k]} |")
    if s.get("ws_closed"):
        med = s.get("ws_latency_sum", 0) / max(1, s["ws_closed"])
        a(f"| Kapanış→kayıt medyan gecikme | {med:.0f} ms |")
        a(f"| En uzun gecikme | {s.get('ws_latency_max', 0)} ms |")
    a("")

    a("## 2. PAPER defteri\n")
    a(f"- Sermaye: **{b.get('equity_start')}** → **{b.get('equity_now')}** "
      f"(gerçekleşen: {b.get('realized_net')})")
    a(f"- İşlem: **{b.get('trades')}** · açık: {b.get('open')} · "
      f"kazanma: %{_f(b.get('win_rate'), 1)} · PF: {b.get('profit_factor')} · "
      f"ort. R: {b.get('avg_r')}")
    a(f"- Ücretler: {b.get('fees')} · funding: {b.get('funding')} · "
      f"maks. düşüş: {b.get('max_dd')}")
    a(f"- Devre kesici: `{b.get('halt') or 'yok'}`\n")
    if b.get("rejects"):
        a("**Defter ret nedenleri:** " +
          ", ".join(f"`{k}`×{v}" for k, v in b["rejects"].items()) + "\n")

    trades = r.get("trades") or []
    if trades:
        a("## 3. İşlemler\n")
        a("| # | Borsa | Sembol | Yön | Giriş | Çıkış | Net | R | Neden |")
        a("|--:|---|---|---|---|--:|--:|--:|---|")
        for i, t in enumerate(trades, 1):
            a(f"| {i} | {t['market']} | {t['symbol']} | {t['side']} | "
              f"{_f(t['entry'], 6)} | {_f(t['exit'], 6)} | {_f(t['net'], 4)} | "
              f"{_f(t['r'], 2)} | {t['reason']} |")
        a("")
    else:
        a("## 3. İşlemler\n\nBu koşuda pozisyon açılmadı. "
          "Sebep aşağıdaki ret dağılımındadır; **sinyal yokluğu ile kapı reddi "
          "aynı şey değildir.**\n")

    if s.get("signals") or s.get("no_signal"):
        a("## 4. Sinyal ve ret dağılımı\n")
        a("| Sayaç | Adet |")
        a("|---|--:|")
        for k, v in sorted(s.items(), key=lambda kv: -kv[1]):
            if k.startswith("reject_") or k in ("signals", "no_signal", "opened",
                                                "dup_bar"):
                a(f"| {k} | {v} |")
        a("")

    a("## 5. Borsa sağlığı\n")
    a("| Borsa | İstek OK | Hata | Durum | Son hata |")
    a("|---|---|--:|---|---|")
    for m, h in (r.get("venue_health") or {}).items():
        a(f"| {m} | {h.get('ok')} | {h.get('err')} | "
          f"{'❌ UNREACHABLE' if h.get('down') else '✅'} | "
          f"{(h.get('last_error') or '')[:50]} |")
    a("")

    a("## 6. Ayarlar\n")
    cfg = r.get("config") or {}
    a("| Ayar | Değer |")
    a("|---|--:|")
    for k in ("equity", "risk_pct", "max_positions", "stop_atr", "tp_atr",
              "max_hold_sec", "taker_bps", "slip_bps", "max_spread_bps",
              "min_liq_dist_pct", "daily_loss_pct"):
        if k in cfg:
            a(f"| {k} | {cfg[k]} |")
    a(f"| min_score | {(r.get('params') or {}).get('min_score')} |")
    a(f"| max_chop | {(r.get('params') or {}).get('max_chop')} |")
    a("")

    a("## 7. Dürüstlük sınırları\n")
    for s_ in (
        "Gerçek emir yolu yoktur; kamu verisi okunur, sanal deftere yazılır.",
        "Dolum modeli taker + makas + varsayımsal kayma; emir defteri derinliği yok.",
        "Likidasyon fiyatı `1/kaldıraç − bakım marjı` yaklaşımıdır; borsanın gerçek "
        "tasfiye motoru ve kademeli marjı modellenmedi.",
        "Funding yalnız oran bilinen sembollerde işlenir; funding anına 3 dakikadan "
        "az kaldıysa giriş reddedilir.",
        "15 dakikalık pencere kârlılık kanıtı değildir; işlem sayısı çoğu zaman "
        "istatistiksel olarak anlamsızdır.",
        "Bu bot hiçbir dil modeli/YZ servisi çağırmaz; 'model onayı' iddiası yoktur.",
    ):
        a(f"- {s_}")
    a("")
    if r.get("error"):
        a(f"## Hata\n\n`{r['error']}`\n")
    return "\n".join(L)


def yaz_backtest(p: dict[str, Any]) -> str:
    r = p["result"]
    L: list[str] = []
    a = L.append
    a("# NOVA-BOT — geriye dönük test\n")
    a(f"**Sembol:** {p.get('symbols')} · **Sembol başına mum:** {p.get('bars_per_symbol')} "
      f"(~{p.get('span_hours')} saat) · **Parametre:** skor≥{p['params']['min_score']}, "
      f"chop<{p['params']['max_chop']}\n")
    a("> Gerçek kamu mumlarıyla PAPER simülasyonu. Kârlılık kanıtı değildir.\n")
    a("| Ölçüm | Değer |")
    a("|---|--:|")
    for k, label in (("trades", "İşlem"), ("net", "Net"), ("win_rate", "Kazanma %"),
                     ("profit_factor", "Profit factor"), ("avg_r", "Ort. R"),
                     ("max_dd", "Maks. düşüş"), ("equity_start", "Başlangıç"),
                     ("equity_end", "Bitiş")):
        a(f"| {label} | {r.get(k)} |")
    a("")
    a("**Çıkış dağılımı:** " + ", ".join(f"`{k}`×{v}" for k, v in (r.get("exits") or {}).items()))
    a("")
    a("## Sınırlar\n")
    for s in p.get("limits", []):
        a(f"- {s}")
    a("")
    return "\n".join(L)
