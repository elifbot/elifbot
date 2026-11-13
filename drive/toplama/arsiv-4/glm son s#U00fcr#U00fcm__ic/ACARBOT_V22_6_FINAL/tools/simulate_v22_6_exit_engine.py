"""Offline end-to-end simulation of the V22.6 exit engine (PAPER path, no network).

40 positions with synthetic price paths covering every exit branch, driven exactly like the live
runner drives them: pm.check via PaperBroker.update (STOP/HARD_LOSS/TIME) + indicator TP via
PaperBroker.indicator_exit with a synthetic score (0.6 while trending, 0.0 when the trend fades).

  A) 12 winners: trend up, then the score fades in profit -> INDICATOR_TP (net >= 0.5R = $10)
  B) 6 runners: +1R, then reverse -> trailing stop locks ~+0.5R
  C) 6 breakeven saves: +0.6R, then collapse -> stop armed at entry+costs, exits ~flat
  D) 10 losers: straight to the fixed -$20 stop
  E) 6 shorts that work (symmetry)

Then it re-runs the SAME paths with the V22.5 rules ($0.10 TP floor, no breakeven, no trail)
to quantify what the old rules did to the same signals.
"""
import sys, time, json
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from phoenix.config import Config
from phoenix.models import Signal
from phoenix.paper import PaperBroker
from phoenix.risk import RiskManager

T0 = time.time()


def make_signal(cfg, risk, sym, side="LONG", entry=100.0):
    notional = cfg.entry_notional_usd
    qty = notional / entry
    fee = risk.estimated_entry_fee(notional)
    stop = risk.stop_price(entry, side, qty, 1.0, fee)
    return Signal("BINANCE", sym, side, 0.6, entry, stop, 0.0, notional, notional / cfg.leverage,
                  T0, qty, [], 1.0, 0.0, 0.0)


def run(cfg, paths, equity):
    broker = PaperBroker(cfg, equity=equity, clock=lambda: T0)
    risk = RiskManager(cfg)
    for sym, side, entry, series, scores in paths:
        sig = make_signal(cfg, risk, sym, side, entry)
        res = broker.submit(sig)
        assert res["status"] == "ACCEPTED", (sym, res)
    for step in range(max(len(p[3]) for p in paths)):
        now = T0 + step * 900
        cur = {}
        for sym, side, entry, series, scores in paths:
            if step < len(series):
                cur[("BINANCE", sym)] = series[step]
        for rec in broker.update(cur, now=now):
            print(f"  CLOSED {rec['symbol']:<6} {rec['side']:<5} reason={rec['reason']:<13} "
                  f"net={rec['net_pnl']:7.2f}  peak={rec.get('peak_net', 0):6.2f}  be={int(rec.get('breakeven_armed', False))} trail={int(rec.get('trail_armed', False))}")
        # indicator-exit pass, like the runner's _evaluate_open_positions
        for sym, side, entry, series, scores in paths:
            if step < len(scores) and broker.has_open("BINANCE", sym):
                mark = cur.get(("BINANCE", sym))
                rec = broker.indicator_exit("BINANCE", sym, mark, scores[step], now=now)
                if rec:
                    print(f"  CLOSED {rec['symbol']:<6} {rec['side']:<5} reason={rec['reason']:<13} "
                          f"net={rec['net_pnl']:7.2f}  peak={rec.get('peak_net', 0):6.2f}  score={scores[step]}")
    return broker


def summary(tag, b):
    s = b.summary()
    print(f"\n--- {tag} summary ---")
    print(json.dumps({k: s[k] for k in ("realized_total", "closed_by_reason", "trade_stats", "wins", "losses")}, indent=2, default=str))
    return s


paths = []
# A) 12 winners: +0.4%/step x6 (net ~$11.8 >= 0.5R), then trend fades -> INDICATOR_TP
for i in range(12):
    e = 100.0
    series = [e * (1 + 0.004 * k) for k in range(7)] + [e * 1.0249, e * 1.0248]
    scores = [0.6] * 7 + [0.0, 0.0]
    paths.append((f"W{i}/USDT:USDT", "LONG", e, series, scores))
# B) 6 runners: +0.6%/step to ~+3.6% (net ~$20+ -> trail arms), then reverse to +2.0% -> trail stop
for i in range(6):
    e = 100.0
    series = [e * (1 + 0.006 * k) for k in range(7)] + [e * 1.045, e * 1.020]
    scores = [0.6] * 9
    paths.append((f"R{i}/USDT:USDT", "LONG", e, series, scores))
# C) 6 breakeven saves: +1.3% (net ~$5.8 -> NOT armed)... use +2.2% (net ~$10.3 -> BE armed), then collapse
for i in range(6):
    e = 100.0
    series = [e * 1.008, e * 1.014, e * 1.022, e * 1.021, e * 1.010, e * 1.001, e * 0.9995]
    scores = [0.6] * 7
    paths.append((f"B{i}/USDT:USDT", "LONG", e, series, scores))
# D) 10 losers: slide to the stop; mark crosses stop (96.14) at 96.1 (small gap, like a real fill)
for i in range(10):
    e = 100.0
    series = [e * 0.999, e * 0.995, e * 0.988, e * 0.982, e * 0.976, e * 0.970, e * 0.966, e * 0.963, e * 0.961]
    scores = [0.6] * 9
    paths.append((f"L{i}/USDT:USDT", "LONG", e, series, scores))
# E) 6 shorts that work (symmetry): fade at ~-2.5%
for i in range(6):
    e = 100.0
    series = [e * (1 - 0.004 * k) for k in range(7)] + [e * 0.9755, e * 0.9754]
    scores = [0.6] * 7 + [0.0, 0.0]
    paths.append((f"S{i}/USDT:USDT", "SHORT", e, series, scores))

print("=== V22.6 exit engine (40 paper positions, $50 margin x10 = $500 notional, -$20 stop) ===")
b = run(Config(), paths, equity=100_000)   # count uncapped; equity raised so all 40 fit the margin cap
s = summary("V22.6", b)

cfg_old = Config(tp_min_net_usd=0.10, tp_min_r=0.0, breakeven_r=0.0, trail_arm_r=0.0)
print("\n=== V22.5 rules on the SAME paths (TP floor $0.10, no breakeven, no trail) ===")
b_old = run(cfg_old, paths, equity=100_000)
s_old = summary("V22.5 rules", b_old)

print("\n===================== VERDICT =====================")
print("V22.6 realized : %9.2f USD  (payoff %.2f, expectancy %.2f/trade)"
      % (s["realized_total"], s["trade_stats"]["payoff_ratio"], s["trade_stats"]["expectancy_usd"]))
print("V22.5 realized : %9.2f USD  (payoff %.2f, expectancy %.2f/trade)"
      % (s_old["realized_total"], (s_old["trade_stats"]["payoff_ratio"] or 0), s_old["trade_stats"]["expectancy_usd"]))
print("Same signals, same fees - difference caused ONLY by the exit engine: %+.2f USD" % (s["realized_total"] - s_old["realized_total"]))
