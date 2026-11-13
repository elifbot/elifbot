"""ACARBOT v2.0 — Gerçek zamanlı profesyonel kontrol paneli (şartname 8).

9 bölüm:
  Genel bakış       bakiye, equity, günlük PnL, veri kaynağı
  Açık pozisyonlar  LONG/SHORT, giriş, stop, TP, net PnL, skor, rejim
  Sinyal merkezi    son değerlendirme: puan + gerekçe (NEDEN İŞLEM AÇMADI)
  Piyasa tarayıcı   takip edilen tüm semboller: fiyat, 15m değişim, RVOL, rejim
  Risk merkezi      teminat, toplam risk, korelasyon, equity eşiği mesafesi
  Emir merkezi      maker/taker, dolum, iptal, dolmayan sayaçları
  Strateji analizi  motor/rejim bazlı başarılar
  Sistem sağlığı    tick, bayatlık, veri hataları, kapı durumları
  Performans        win rate, PF, MaxDD, Sharpe (oturum)

Panel yalnızca toplanmış GERÇEK durumu yansıtır; uydurma değer içermez.
"""

from __future__ import annotations

from typing import Any

from core.portfolio import Portfolio
from core.risk import KillSwitchState, RiskManager
from exec.paper import PaperBroker


def collect_snapshot(
    executor: Any,
    metrics: Any | None = None,
    session_trades: list[dict] | None = None,
) -> dict:
    """Executor'dan 9 bölümlük panel anlık görüntüsü toplar."""
    broker: PaperBroker = executor.broker
    risk: RiskManager = executor.risk
    portfolio: Portfolio = broker.portfolio
    prices = dict(executor._latest_prices)
    equity = portfolio.equity(prices)
    unrealized = portfolio.unrealized_pnl(prices)

    # --- Genel bakış -----------------------------------------------------
    floor_pct = 0.0
    floor_value = 0.0
    if executor.config.v2.enabled:
        floor_pct = executor.config.v2.gates.equity_floor_pct
        floor_value = portfolio.initial_balance * (1 - floor_pct / 100.0)
    overview = {
        "balance": round(portfolio.balance, 2),
        "equity": round(equity, 2),
        "unrealized": round(unrealized, 2),
        "initial_balance": round(portfolio.initial_balance, 2),
        "equity_floor": round(floor_value, 2),
        "equity_floor_pct": floor_pct,
        "kill_switch": risk.kill_switch_state.value,
        "halt_reason": risk.last_halt_reason,
        "safe_mode": bool(executor.data_integrity.safe_mode),
        "data_source": getattr(executor, "data_source", "perp"),
    }

    # --- Açık pozisyonlar -------------------------------------------------
    positions = []
    for symbol, p in portfolio.positions.items():
        price = prices.get(symbol, p.entry)
        positions.append({
            "symbol": symbol,
            "side": p.side,
            "entry": round(p.entry, 6),
            "quantity": round(p.quantity, 6),
            "stop": round(p.stop_loss, 6),
            "tp": round(p.take_profit, 6) if p.take_profit else None,
            "net_pnl": round(p.net_pnl(price, broker.taker_fee_rate, 0.0), 4),
            "r": round(
                p.net_pnl(price, broker.taker_fee_rate, 0.0)
                / p.initial_net_risk, 2,
            ) if p.initial_net_risk > 0 else 0.0,
            "score": round(p.score, 1),
            "regime": p.regime,
            "motor": p.motor,
            "trailing": p.trailing_active,
        })

    # --- Sinyal merkezi (neden işlem açmadı dâhil) ------------------------
    signals = []
    for symbol, info in getattr(executor, "last_eval", {}).items():
        signals.append({
            "symbol": symbol,
            "ts": info.get("ts", 0),
            "side": info.get("side", "-"),
            "score": round(info.get("score", 0.0), 1),
            "grade": info.get("grade", "-"),
            "regime": info.get("regime", "-"),
            "reason": info.get("reason", "-"),
        })
    signals.sort(key=lambda s: -s["score"])

    # --- Piyasa tarayıcı ---------------------------------------------------
    scanner = []
    for symbol, candles in getattr(executor, "_candles", {}).items():
        if not candles:
            continue
        reading = getattr(executor, "_last_regime", {}).get(symbol)
        scanner.append({
            "symbol": symbol,
            "price": round(candles[-1].close, 6),
            "rvol": round(getattr(executor, "_rvol")(candles), 2),
            "regime": reading.regime.value if reading else "-",
        })

    # --- Risk merkezi -------------------------------------------------------
    total_open_risk = portfolio.total_open_net_risk()
    gross = portfolio.total_notional(prices)
    directional = portfolio.directional_notional(prices)
    used_margin = portfolio.used_margin
    free_margin = portfolio.balance + unrealized - used_margin
    risk_center = {
        "used_margin": round(used_margin, 2),
        "free_margin": round(free_margin, 2),
        "total_open_risk": round(total_open_risk, 2),
        "total_open_risk_cap": executor.config.portfolio.total_open_risk_cap,
        "gross_notional": round(gross, 2),
        "directional_notional": round(directional, 2),
        "margin_mode": executor.config.v2.margin.mode,
        "beta_directional": (
            round(executor.last_beta_directional, 2)
            if getattr(executor, "last_beta_directional", None) is not None
            else None
        ),
        "shock_test": getattr(executor, "last_shock_summary", {}),
        "open_positions": len(portfolio.positions),
        "max_positions": executor.config.portfolio.max_positions,
        "entry_rate": getattr(executor, "rate_limiter", None).stats()
        if getattr(executor, "rate_limiter", None) else {},
    }

    # --- Emir merkezi --------------------------------------------------------
    orders = {
        "new": sum(1 for t in broker.trades if t.get("type") == "ORDER_NEW"),
        "filled": sum(1 for t in broker.trades if t.get("type") == "ORDER_FILL"),
        "expired": sum(1 for t in broker.trades if t.get("type") == "ORDER_EXPIRED"),
        "canceled": sum(1 for t in broker.trades if t.get("type") == "ORDER_CANCELED"),
        "partial_fills": sum(
            1 for t in broker.trades
            if t.get("type") == "ORDER_FILL" and t.get("partial")
        ),
    }

    # --- Strateji analizi ------------------------------------------------------
    trades = session_trades if session_trades is not None else [
        t for t in broker.trades if isinstance(t.get("timestamp"), (int, float))
    ]
    closes = [t for t in trades if t.get("type") == "CLOSE"]
    strategy: dict[str, dict] = {}
    for close in closes:
        key = str(close.get("motor", "?"))
        bucket = strategy.setdefault(
            key, {"trades": 0, "net": 0.0, "wins": 0},
        )
        bucket["trades"] += 1
        bucket["net"] += float(close.get("pnl", 0.0))
        bucket["wins"] += 1 if float(close.get("pnl", 0.0)) > 0 else 0
    regimes: dict[str, dict] = {}
    for close in closes:
        key = str(close.get("regime", "") or "?")
        bucket = regimes.setdefault(
            key, {"trades": 0, "net": 0.0, "wins": 0},
        )
        bucket["trades"] += 1
        bucket["net"] += float(close.get("pnl", 0.0))
        bucket["wins"] += 1 if float(close.get("pnl", 0.0)) > 0 else 0

    # --- Sistem sağlığı ---------------------------------------------------------
    integrity = executor.data_integrity
    health = {
        "safe_mode": bool(integrity.safe_mode),
        "safe_mode_reason": integrity.safe_mode_reason,
        "symbols_tracked": len(getattr(executor, "_candles", {})),
        "last_block_reasons": dict(getattr(executor, "last_block_reason", {})),
        "counters": dict(metrics.counters) if metrics else {},
        "guards": {
            "news": (
                executor.news_guard.status()
                if getattr(executor, "news_guard", None) else "kapalı"
            ),
            "sweep": (
                executor.sweep_guard.status()
                if getattr(executor, "sweep_guard", None) else "kapalı"
            ),
        },
        "shadow": (
            executor.shadow_tracker.summary()
            if getattr(executor, "shadow_tracker", None) else {}
        ),
    }

    # --- Performans ----------------------------------------------------------------
    from backtest.metrics import compute_metrics
    block = compute_metrics(list(trades), portfolio.initial_balance)
    performance = {
        "win_rate": round(block.win_rate, 3),
        "profit_factor": (
            None if block.profit_factor == float("inf")
            else round(block.profit_factor, 3)
        ),
        "max_drawdown_pct": round(block.max_drawdown_pct, 2),
        "sharpe": round(block.sharpe_per_trade, 3),
        "expectancy": round(block.expectancy_usdt, 4),
        "trades": block.trade_count,
        "max_consecutive_losses": block.max_consecutive_losses,
    }

    return {
        "overview": overview,
        "positions": positions,
        "signals": signals,
        "scanner": scanner,
        "risk": risk_center,
        "orders": orders,
        "strategy": {"motors": strategy, "regimes": regimes},
        "health": health,
        "performance": performance,
    }


def render_text(snapshot: dict) -> str:
    """Paneli terminal/log için hizalı metne çevirir (Türkçe başlıklar)."""
    ov = snapshot["overview"]
    lines = ["┌─ ACARBOT v2.0 KONTROL PANELİ " + "─" * 40]
    lines.append(
        f"│ GENEL | bakiye {ov['balance']:.2f} | equity {ov['equity']:.2f} | "
        f"eşik {ov['equity_floor']:.2f} (-%{ov['equity_floor_pct']:.0f}) | "
        f"kill {ov['kill_switch']} | veri: {ov['data_source']}"
    )
    if ov.get("halt_reason"):
        lines.append(f"│ HALT GEREKÇESİ: {ov['halt_reason']}")
    lines.append("├─ AÇIK POZİSYONLAR " + "─" * 42)
    if snapshot["positions"]:
        for p in snapshot["positions"]:
            lines.append(
                f"│ {p['symbol']:<22} {p['side']:<5} giriş {p['entry']:.6g} "
                f"stop {p['stop']:.6g} pnl {p['net_pnl']:+.2f} ({p['r']:+.1f}R) "
                f"skor {p['score']:.0f} {p['motor']}{' [BE]' if p['trailing'] else ''}"
            )
    else:
        lines.append("│ (yok)")
    lines.append("├─ SİNYAL MERKEZİ (en yüksek skorlu 5) " + "─" * 26)
    if snapshot["signals"]:
        for s in snapshot["signals"][:5]:
            lines.append(
                f"│ {s['symbol']:<22} {s['side']:<5} skor {s['score']:.0f} "
                f"{s['grade']:<11} | {s['reason']}"
            )
    else:
        lines.append("│ (henüz değerlendirme yok)")
    lines.append("├─ PİYASA TARAYICI " + "─" * 44)
    for s in snapshot["scanner"][:10]:
        lines.append(
            f"│ {s['symbol']:<22} fiyat {s['price']:.6g} "
            f"rvol {s['rvol']:.2f} rejim {s['regime']}"
        )
    rk = snapshot["risk"]
    lines.append("├─ RİSK MERKEZİ " + "─" * 47)
    lines.append(
        f"│ teminat kullanım {rk['used_margin']:.2f} | serbest {rk['free_margin']:.2f} | "
        f"marj modu {rk['margin_mode']} | açık {rk['open_positions']}"
    )
    lines.append(
        f"│ açık risk {rk['total_open_risk']:.2f}/{rk['total_open_risk_cap']} | "
        f"brüt {rk['gross_notional']:.2f} | yönsel {rk['directional_notional']:.2f}"
    )
    if rk.get("entry_rate"):
        lines.append(f"│ giriş hızı: {rk['entry_rate']}")
    o = snapshot["orders"]
    lines.append("├─ EMİR MERKEZİ " + "─" * 48)
    lines.append(
        f"│ yeni {o['new']} | dolum {o['filled']} (kısmi {o['partial_fills']}) | "
        f"dolmayan {o['expired']} | iptal {o['canceled']}"
    )
    lines.append("├─ STRATEJİ ANALİZİ " + "─" * 45)
    for motor, stats in snapshot["strategy"]["motors"].items():
        wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] else 0.0
        lines.append(
            f"│ {motor:<16} {stats['trades']} işlem | net {stats['net']:+.2f} | "
            f"kazanma %{wr:.0f}"
        )
    for regime, stats in snapshot["strategy"]["regimes"].items():
        wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] else 0.0
        lines.append(
            f"│ rejim {regime:<22} {stats['trades']} işlem | "
            f"net {stats['net']:+.2f} | %{wr:.0f}"
        )
    h = snapshot["health"]
    lines.append("├─ SİSTEM SAĞLIĞI " + "─" * 47)
    lines.append(
        f"│ güvenli mod: {'EVET' if h['safe_mode'] else 'hayır'} "
        f"({h.get('safe_mode_reason') or '-'}) | sembol {h['symbols_tracked']}"
    )
    blocks = h.get("last_block_reasons", {})
    for symbol, reason in list(blocks.items())[:5]:
        lines.append(f"│ engel [{symbol}] {reason}")
    p = snapshot["performance"]
    lines.append("├─ PERFORMANS " + "─" * 51)
    pf = "∞" if p["profit_factor"] is None else f"{p['profit_factor']:.2f}"
    lines.append(
        f"│ kazanma %{p['win_rate']*100:.1f} | PF {pf} | MaxDD "
        f"%{p['max_drawdown_pct']:.1f} | Sharpe {p['sharpe']:.2f} | "
        f"{p['trades']} işlem"
    )
    lines.append("└" + "─" * 72)
    return "\n".join(lines)
