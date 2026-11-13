"""Aynı baseline girişleri üzerinde izole, emir göndermeyen shadow kohortları.

Giriş filtreleri kabul ettikleri baseline işlemin gerçekleşen aynı kapanış
sonucunu eşler (paired entry-mirror). Net Exit ise aynı fill ile bağımsız
pozisyon açar ve kendi net trailing/order-flow çıkışını uygular. Bu tasarım
yeni piyasa koşulları yerine kural farkını ölçer; tek run canlı kurala taşınmaz.
"""
from __future__ import annotations

import copy
import math
import time
from collections import Counter
from statistics import median

from .attribution import build_session_analysis
from .cohort_report import is_manual_close
from .exit_rules import apply_supertrend_trailing, runner_exit_reason
from .risk import Position, RiskManager
from .trade_quality import (
    adjusted_flow_entry,
    flow_confidence,
    portfolio_guard,
    range_flow_gate,
    pdf_confluence,
    pdf_v3_confluence,
    technical_harmony,
    volatility_quality,
)

VARIANT_SPECS = (
    ("net-exit", "NET EXIT — bağımsız çıkış"),
    ("flow-confidence", "FLOW CONFIDENCE v2 + DATA READINESS"),
    ("volatility-gate", "VOLATİLİTE / MALİYET ALANI"),
    ("range-confirmation", "RANGE AKIŞ GİRİŞİ ONAYI"),
    ("technical-harmony", "TEKNİK ÇELİŞKİ FİLTRESİ"),
    ("portfolio-guard", "PORTFÖY YÖN + KORELASYON GUARD"),
    ("pdf-confluence", "PDF-V2 RESEARCH"),
    ("pdf-v3-confluence", "PDF-V3 + TÜREV İSTİHBARATI"),
)

FORCED_CLOSE_MARKERS = (
    "FLASH CRASH",
    "WS >10 SN",
    "ARD ARDA 3 EMİR",
    "AUTH/PERMISSION",
)


def _finite(value, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _json_safe(value):
    """Rapor yazımını bozan NaN/Inf değerleri null'a indirge."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _top2_share(trades: list[dict]) -> float | None:
    net = sum(_finite(row.get("net_pnl_usdt")) for row in trades)
    if net <= 0 or not trades:
        return None
    top2 = sum(sorted((_finite(row.get("net_pnl_usdt")) for row in trades), reverse=True)[:2])
    return round(top2 / net * 100.0, 4)


def _extended_metrics(trades: list[dict], start_balance: float) -> dict:
    nets = [_finite(row.get("net_pnl_usdt")) for row in trades]
    equity = float(start_balance)
    peak = equity
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    for row in sorted(trades, key=lambda item: _finite(item.get("ts"))):
        equity += _finite(row.get("net_pnl_usdt"))
        peak = max(peak, equity)
        drawdown = max(0.0, peak - equity)
        max_drawdown = max(max_drawdown, drawdown)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, drawdown / peak * 100.0)
    trailing_cost = [
        row for row in trades
        if str(row.get("reason") or "").upper().startswith("TRAILING")
        and _finite(row.get("pnl_usdt")) >= 0
        and _finite(row.get("net_pnl_usdt")) < 0
    ]

    def distribution(key_func) -> dict:
        result: dict[str, dict] = {}
        for row in trades:
            key = str(key_func(row) or "BELİRSİZ")
            bucket = result.setdefault(key, {"trades": 0, "wins": 0, "losses": 0, "net_pnl_usdt": 0.0})
            net = _finite(row.get("net_pnl_usdt"))
            bucket["trades"] += 1
            bucket["wins"] += int(net > 0)
            bucket["losses"] += int(net < 0)
            bucket["net_pnl_usdt"] += net
        return dict(sorted(result.items()))

    return {
        "median_net_usdt": median(nets) if nets else 0.0,
        "closed_equity_max_drawdown_usdt": max_drawdown,
        "closed_equity_max_drawdown_pct": max_drawdown_pct,
        "trailing_gross_nonnegative_net_loss_count": len(trailing_cost),
        "trailing_gross_nonnegative_net_loss_usdt": sum(
            _finite(row.get("net_pnl_usdt")) for row in trailing_cost
        ),
        "exchanges": distribution(lambda row: row.get("exchange")),
        "regimes": distribution(
            lambda row: ((row.get("entry_context") or {}).get("indicators") or {}).get("regime")
        ),
    }


class ShadowLab:
    def __init__(
        self,
        strategy,
        baseline_risk: RiskManager,
        runner_exit_cfg: dict,
        supertrend_trailing: bool,
        fee_cfg: dict,
        config: dict,
    ):
        self.strategy = strategy
        self.runner_exit_cfg = dict(runner_exit_cfg or {})
        self.supertrend_trailing = bool(supertrend_trailing)
        self.fee_cfg = dict(fee_cfg or {})
        self.config = dict(config or {})
        self.start_balance = _finite(self.config.get("sanal_kasa_usdt"), 100000.0)
        self.started_at = time.time()
        self.baseline_entries = 0
        self.baseline_trades: list[dict] = []
        self.last_prices: dict[str, float] = {}
        self.supertrend: dict[str, dict] = {}
        self.returns: dict[str, list[float]] = {}
        self._return_last_ts: dict[str, int] = {}
        self._return_last_close: dict[str, float] = {}
        self.divergent_after_baseline_close = 0
        self.net_risk = RiskManager(
            stop_loss_pct=baseline_risk.stop_loss_pct,
            stop_model=baseline_risk.stop_model,
            margin_stop_fraction=baseline_risk.margin_stop_fraction,
            margin_stop_liq_buffer=baseline_risk.margin_stop_liq_buffer,
            lock_trigger_pct=baseline_risk.lock_trigger_pct,
            lock_level_pct=baseline_risk.lock_level_pct,
            trail_pct=baseline_risk.trail_pct,
            leverage=baseline_risk.leverage,
            unlimited_pyramiding=False,
            pair_rescue_enabled=False,
            state_store=None,
        )
        self.variants: dict[str, dict] = {}
        for name, label in VARIANT_SPECS:
            if name == "pdf-confluence" and not bool(
                self.config.get("pdf_confluence", {}).get("aktif", False)
            ):
                continue
            if name == "pdf-v3-confluence" and not bool(
                self.config.get("pdf_v3_confluence", {}).get("aktif", False)
            ):
                continue
            self.variants[name] = {
                "name": name,
                "label": label,
                "kind": "independent_exit" if name == "net-exit" else "paired_entry_mirror",
                "balance": self.start_balance,
                "accepted_count": 0,
                "rejected_count": 0,
                "rejections": Counter(),
                "decisions": [],
                "trades": [],
                "entries": {},
                "total_fees": 0.0,
                "total_funding": 0.0,
            }
        self._net_contexts: dict[str, dict] = {}
        self._net_ids: dict[str, str] = {}
        self._funding_last: dict[str, float] = {}

    @property
    def _net(self) -> dict:
        return self.variants["net-exit"]

    def _record_decision(self, variant: dict, payload: dict) -> None:
        variant["decisions"].append(payload)
        if payload["accepted"]:
            variant["accepted_count"] += 1
        else:
            variant["rejected_count"] += 1
            reason = str(payload.get("reason") or "belirsiz")
            variant["rejections"][reason] += 1

    def _open_net(self, symbol: str, baseline: Position, position_id: str, context: dict) -> None:
        # Baseline aynı sembolde yeniden giriş yaparsa eski bağımsız shadow
        # pozisyonunu yeni fill'de kapat; tek sembol/tek pozisyon modeli korunur.
        if symbol in self._net["entries"]:
            self._close_net(symbol, baseline.entry, "SHADOW YENİ BASELINE GİRİŞİ")
        pos = Position(
            symbol=symbol,
            side=baseline.side,
            entry=baseline.entry,
            qty=baseline.qty,
            stop=self.net_risk.initial_stop(baseline.side, baseline.entry, baseline.leverage),
            peak=baseline.entry,
            leverage=baseline.leverage,
            margin_usdt=baseline.margin_usdt,
            layers=1,
            last_add_price=baseline.entry,
            exchange=baseline.exchange,
            entry_fee_usdt=baseline.entry_fee_usdt,
            exit_fee_pct=baseline.exit_fee_pct,
            funding_usdt=0.0,
            net_breakeven_enabled=True,
            net_profit_buffer_usdt=max(
                0.0, _finite(self.config.get("net_kar_tamponu_usdt"), 0.0)
            ),
        )
        self._net["entries"][symbol] = pos
        self._net_contexts[symbol] = copy.deepcopy(context)
        self._net_ids[symbol] = position_id
        self._funding_last[symbol] = time.time()
        self._net["balance"] -= pos.entry_fee_usdt
        self._net["total_fees"] += pos.entry_fee_usdt
        self.last_prices[symbol] = baseline.entry

    def on_baseline_open(
        self,
        symbol: str,
        pos: Position,
        position_id: str,
        context: dict,
        fill: dict,
    ) -> None:
        """Gerçekleşmiş baseline fill'ini bütün izole varyantlara aynen dağıt."""
        self.baseline_entries += 1
        self.last_prices[symbol] = float(pos.entry)
        quality_common = {
            "technical": technical_harmony(
                context, pos.side, int(self.config.get("max_karsi_teknik_bilesen", 1))
            ),
            "flow": flow_confidence(
                context.get("orderflow") or {}, self.config.get("flow", {})
            ),
            "volatility": volatility_quality(
                context.get("indicators") or {},
                {**self.fee_cfg, **self.runner_exit_cfg, **self.config.get("volatility", {})},
            ),
        }
        for name, variant in self.variants.items():
            details: dict = {}
            accepted = True
            reason = ""
            if name == "flow-confidence":
                details = adjusted_flow_entry(
                    self.strategy, context, pos.side, quality_common["flow"]
                )
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")
            elif name == "volatility-gate":
                details = dict(quality_common["volatility"])
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")
            elif name == "range-confirmation":
                details = range_flow_gate(
                    context,
                    bool(self.config.get("range_akis_girisine_izin", False)),
                )
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")
            elif name == "technical-harmony":
                details = technical_harmony(
                    context,
                    pos.side,
                    int(self.config.get("max_karsi_teknik_bilesen", 1)),
                )
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")
            elif name == "pdf-confluence":
                details = pdf_confluence(context, pos.side, self.config)
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")
            elif name == "pdf-v3-confluence":
                details = pdf_v3_confluence(context, pos.side, self.config)
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")
            elif name == "portfolio-guard":
                details = portfolio_guard(
                    symbol,
                    pos.side,
                    list(variant["entries"].values()),
                    self.returns,
                    self.config.get("portfolio", {}),
                )
                accepted = bool(details["accepted"])
                reason = str(details.get("reason") or "")

            self._record_decision(
                variant,
                {
                    "ts": time.time(),
                    "position_id": position_id,
                    "symbol": symbol,
                    "side": pos.side,
                    "accepted": accepted,
                    "reason": reason,
                    "details": details,
                    "measurements": copy.deepcopy(quality_common),
                },
            )
            if not accepted:
                continue
            if name == "net-exit":
                self._open_net(symbol, pos, position_id, context)
            else:
                variant["entries"][symbol] = {
                    "symbol": symbol,
                    "side": pos.side,
                    "position_id": position_id,
                    "entry": pos.entry,
                }

    def on_baseline_close(
        self, symbol: str, pos: Position, trade: dict, fully_closed: bool
    ) -> None:
        if not fully_closed:
            return
        baseline_trade = copy.deepcopy(trade)
        self.baseline_trades.append(baseline_trade)
        position_id = str(trade.get("position_id") or "")
        outcome_fields = {
            key: copy.deepcopy(trade.get(key))
            for key in (
                "exit_price", "pnl_pct", "pnl_usdt", "net_pnl_usdt",
                "mfe_usdt", "mae_usdt", "stop_price", "entry_fee_usdt",
                "exit_fee_usdt", "funding_usdt",
            )
        }
        for variant in self.variants.values():
            for decision in variant["decisions"]:
                if (
                    decision.get("position_id") == position_id
                    and not decision.get("accepted")
                    and "baseline_outcome" not in decision
                ):
                    decision["baseline_outcome"] = {
                        **outcome_fields,
                        "reason": trade.get("reason"),
                        "note": "Reddedilen adayın aynı baseline yolundaki karşı-olgusal sonucu; bağımsız shadow exit değildir.",
                    }
        for name, variant in self.variants.items():
            if name == "net-exit":
                continue
            marker = variant["entries"].get(symbol)
            if not marker or marker.get("position_id") != position_id:
                continue
            mirrored = copy.deepcopy(trade)
            mirrored["shadow_variant"] = name
            mirrored["paired_baseline"] = True
            variant["trades"].append(mirrored)
            variant["balance"] += _finite(mirrored.get("net_pnl_usdt"))
            variant["total_fees"] += _finite(mirrored.get("entry_fee_usdt")) + _finite(
                mirrored.get("exit_fee_usdt")
            )
            variant["total_funding"] += _finite(mirrored.get("funding_usdt"))
            variant["entries"].pop(symbol, None)

        current = self._net["entries"].get(symbol)
        if current is None or self._net_ids.get(symbol) != position_id:
            return
        reason = str(trade.get("reason") or "").upper()
        forced = is_manual_close(trade) or any(marker in reason for marker in FORCED_CLOSE_MARKERS)
        if forced:
            self._close_net(
                symbol,
                _finite(trade.get("exit_price"), current.entry),
                str(trade.get("reason") or "BASELINE ZORUNLU KAPAMA"),
            )
        else:
            self.divergent_after_baseline_close += 1

    def set_supertrend(self, symbol: str, direction: int, value: float) -> None:
        value = _finite(value)
        if value <= 0:
            self.supertrend.pop(symbol, None)
            return
        self.supertrend[symbol] = {
            "direction": 1 if int(direction) >= 0 else -1,
            "value": value,
        }

    def update_market_frame(
        self, symbol: str, candle_ts, close: float, candles_count: int = 100
    ) -> None:
        """Kapanmış 5m mum getirilerini korelasyon guard için sakla."""
        try:
            ts = int(candle_ts)
        except (TypeError, ValueError, OverflowError):
            return
        close = _finite(close)
        if close <= 0 or self._return_last_ts.get(symbol) == ts:
            return
        previous = self._return_last_close.get(symbol)
        if previous and previous > 0:
            value = math.log(close / previous)
            series = self.returns.setdefault(symbol, [])
            series.append(value)
            del series[:-max(20, int(candles_count))]
        self._return_last_close[symbol] = close
        self._return_last_ts[symbol] = ts

    def on_price_tick(self, symbol: str, price: float) -> None:
        price = _finite(price)
        if price <= 0:
            return
        self.last_prices[symbol] = price
        pos = self._net["entries"].get(symbol)
        if pos is None:
            return
        if self.supertrend_trailing:
            apply_supertrend_trailing(
                pos, price, self.supertrend.get(symbol), self.net_risk
            )
        action = self.net_risk.update(pos, price)
        if action["action"] == "close":
            self._close_net(symbol, price, str(action["reason"]))

    def on_trade_tick(self, symbol: str, price: float, flow_snapshot: dict) -> None:
        self.on_price_tick(symbol, price)
        pos = self._net["entries"].get(symbol)
        if pos is None:
            return
        reason = runner_exit_reason(
            pos,
            price,
            self.net_risk.profit_pct(pos, price),
            flow_snapshot or {},
            self.runner_exit_cfg,
        )
        if reason:
            self._close_net(symbol, price, f"KÂR KOŞUSU: {reason}")

    def apply_funding(self, symbol: str, rate: float | None, mark_price: float) -> float:
        pos = self._net["entries"].get(symbol)
        now = time.time()
        last = self._funding_last.setdefault(symbol, now)
        if pos is None or rate is None or not math.isfinite(float(rate)) or mark_price <= 0:
            self._funding_last[symbol] = now
            return 0.0
        elapsed = max(0.0, now - last)
        if elapsed < 1.0:
            return 0.0
        direction = 1.0 if pos.side == "LONG" else -1.0
        delta = -direction * pos.qty * mark_price * float(rate) * elapsed / (8 * 3600.0)
        self._funding_last[symbol] = now
        pos.funding_usdt += delta
        self._net["balance"] += delta
        self._net["total_funding"] += delta
        return delta

    def _close_net(self, symbol: str, price: float, reason: str) -> dict | None:
        variant = self._net
        pos = variant["entries"].get(symbol)
        if pos is None or price <= 0:
            return None
        price = float(price)
        direction = 1.0 if pos.side == "LONG" else -1.0
        gross = direction * (price - pos.entry) * pos.qty
        pos.mfe_usdt = max(pos.mfe_usdt, gross)
        pos.mae_usdt = min(pos.mae_usdt, gross)
        pnl_pct = self.net_risk.profit_pct(pos, price)
        exit_fee = price * pos.qty * max(0.0, pos.exit_fee_pct) / 100.0
        net = gross - pos.entry_fee_usdt - exit_fee + pos.funding_usdt
        trade = {
            "ts": time.time(),
            "symbol": symbol,
            "side": pos.side,
            "entry": pos.entry,
            "exit_price": price,
            "qty": pos.qty,
            "leverage": pos.leverage,
            "margin_usdt": pos.margin_usdt,
            "pnl_pct": pnl_pct,
            "roe_pct": pnl_pct * pos.leverage,
            "pnl_usdt": gross,
            "reason": reason,
            "layers": 1,
            "position_id": self._net_ids.get(symbol, ""),
            "entry_context": copy.deepcopy(self._net_contexts.get(symbol) or {}),
            "exchange": pos.exchange,
            "entry_fee_usdt": pos.entry_fee_usdt,
            "exit_fee_usdt": exit_fee,
            "funding_usdt": pos.funding_usdt,
            "net_pnl_usdt": net,
            "mfe_usdt": pos.mfe_usdt,
            "mae_usdt": pos.mae_usdt,
            "stop_price": pos.stop,
            "net_breakeven_price": self.net_risk.net_breakeven_price(pos),
            "shadow_variant": "net-exit",
            "paired_baseline": False,
        }
        variant["trades"].append(trade)
        variant["balance"] += gross - exit_fee
        variant["total_fees"] += exit_fee
        variant["entries"].pop(symbol, None)
        self._net_contexts.pop(symbol, None)
        self._net_ids.pop(symbol, None)
        self._funding_last.pop(symbol, None)
        return trade

    def close_all(self, reason: str) -> None:
        for symbol in list(self._net["entries"]):
            pos = self._net["entries"].get(symbol)
            if pos is None:
                continue
            price = self.last_prices.get(symbol) or pos.entry
            self._close_net(symbol, price, reason)

    def _variant_report(self, variant: dict) -> dict:
        trades = variant["trades"]
        analysis = build_session_analysis(trades)
        net = _finite(analysis["overall"].get("net_pnl_usdt"))
        expected_balance = self.start_balance + net
        rejected_ids = {
            str(row.get("position_id"))
            for row in variant["decisions"] if not row.get("accepted")
        }
        accepted_ids = {
            str(row.get("position_id"))
            for row in variant["decisions"] if row.get("accepted")
        }
        eliminated = [
            row for row in self.baseline_trades
            if str(row.get("position_id") or "") in rejected_ids
        ]
        preserved_baseline = [
            row for row in self.baseline_trades
            if str(row.get("position_id") or "") in accepted_ids
        ]
        baseline_winners = sum(
            _finite(row.get("net_pnl_usdt")) > 0 for row in self.baseline_trades
        )
        eliminated_winners = sum(
            _finite(row.get("net_pnl_usdt")) > 0 for row in eliminated
        )
        baseline_net = sum(
            _finite(row.get("net_pnl_usdt")) for row in self.baseline_trades
        )
        comparison = {
            "preserved_baseline_trades": len(preserved_baseline),
            "eliminated_baseline_trades": len(eliminated),
            "eliminated_baseline_winners": eliminated_winners,
            "eliminated_baseline_losers": sum(
                _finite(row.get("net_pnl_usdt")) < 0 for row in eliminated
            ),
            "missed_baseline_winner_rate_pct": (
                eliminated_winners / baseline_winners * 100.0
                if baseline_winners > 0 else None
            ),
            "eliminated_baseline_net_usdt": sum(
                _finite(row.get("net_pnl_usdt")) for row in eliminated
            ),
            "net_delta_vs_observed_baseline_usdt": net - baseline_net,
        }
        return {
            "name": variant["name"],
            "label": variant["label"],
            "kind": variant["kind"],
            "start_balance_usdt": self.start_balance,
            "balance_usdt": variant["balance"],
            "expected_balance_usdt": expected_balance,
            "balance_reconciliation_error": variant["balance"] - expected_balance,
            "baseline_entries_observed": self.baseline_entries,
            "accepted_entries": variant["accepted_count"],
            "rejected_entries": variant["rejected_count"],
            "open_positions": len(variant["entries"]),
            "open_symbols": sorted(variant["entries"]),
            "rejection_reasons": dict(variant["rejections"].most_common()),
            "top2_share_of_net_pct": _top2_share(trades),
            "extended": _extended_metrics(trades, self.start_balance),
            "baseline_comparison": comparison,
            "analysis": analysis,
            "decisions": variant["decisions"],
            "trades": trades,
        }

    def report(self) -> dict:
        baseline_analysis = build_session_analysis(self.baseline_trades)
        variants = [self._variant_report(variant) for variant in self.variants.values()]
        report = {
            "schema": "shadow-lab-v1",
            "started_at": self.started_at,
            "generated_at": time.time(),
            "method": {
                "baseline": "Ana paper strateji ve eşikler değiştirilmedi.",
                "entry_variants": "Kabul edilen aynı baseline pozisyonunun gerçekleşen kapanış sonucu eşleştirildi; retler işlem açmadı.",
                "net_exit": "Aynı fill/miktar/kaldıraç ile bağımsız net trailing ve order-flow çıkışı; gerçek emir yok.",
                "balance": f"Her varyant için izole {self.start_balance:,.2f} USDT sanal kasa; varyantlar birbirinin state'ini paylaşmaz.",
                "promotion": "Tek run otomatik canlı kural veya parametre optimizasyonu değildir; zararsızlık garanti edilmez.",
            },
            "baseline": {
                "entries_observed": self.baseline_entries,
                "trades_observed": len(self.baseline_trades),
                "trades": copy.deepcopy(self.baseline_trades),
                "analysis": baseline_analysis,
                "top2_share_of_net_pct": _top2_share(self.baseline_trades),
                "extended": _extended_metrics(self.baseline_trades, self.start_balance),
            },
            "divergent_after_baseline_close": self.divergent_after_baseline_close,
            "closeout_completed": all(row["open_positions"] == 0 for row in variants),
            "variants": variants,
        }
        return _json_safe(report)


def _money(value) -> str:
    return f"{_finite(value):+,.2f}"


def _pf(value) -> str:
    return "∞" if value is None else f"{float(value):.2f}"


def _fees(stats: dict) -> float:
    return _finite(stats.get("entry_fee_usdt")) + _finite(stats.get("exit_fee_usdt"))


def render_shadow_report(report: dict) -> str:
    baseline = report["baseline"]["analysis"]["overall"]
    lines = [
        "# Shadow Lab — eşleştirilmiş paper varyant raporu",
        "",
        "> Ana strateji değiştirilmedi. Giriş varyantları aynı baseline kapanışını eşler; `net-exit` kendi çıkışını bağımsız çalıştırır. Gerçek emir yoktur. Tek oturum otomatik canlı kural değildir ve zararsızlık garanti edilmez.",
        "",
        "| Varyant | Kabul / ret | Kapanan | K / Z | Brüt | Ücret | Funding | Net | PF | İlk 2 / net | Açık |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    base_count = report["baseline"]["entries_observed"]
    lines.append(
        f"| BASELINE | {base_count} / 0 | {baseline['count']} | {baseline['wins']} / {baseline['losses']} | "
        f"{_money(baseline['gross_pnl_usdt'])} | {_money(_fees(baseline))} | "
        f"{_money(baseline['funding_usdt'])} | {_money(baseline['net_pnl_usdt'])} | "
        f"{_pf(baseline['profit_factor'])} | {_finite(report['baseline'].get('top2_share_of_net_pct')):.1f}% | 0 |"
    )
    for variant in report["variants"]:
        stats = variant["analysis"]["overall"]
        top2 = variant.get("top2_share_of_net_pct")
        lines.append(
            f"| {variant['name']} | {variant['accepted_entries']} / {variant['rejected_entries']} | "
            f"{stats['count']} | {stats['wins']} / {stats['losses']} | "
            f"{_money(stats['gross_pnl_usdt'])} | {_money(_fees(stats))} | "
            f"{_money(stats['funding_usdt'])} | {_money(stats['net_pnl_usdt'])} | "
            f"{_pf(stats['profit_factor'])} | {f'{top2:.1f}%' if top2 is not None else '—'} | "
            f"{variant['open_positions']} |"
        )
    lines.extend(
        [
            "",
            "## Kalite ve risk karşılaştırması",
            "",
            "Drawdown yalnız kapanan işlemlerin realized-equity eğrisindendir. Elenen/kaçırılan kazanan, giriş varyantının reddettiği baseline işlemidir; net-exit için bu filtre metrikleri uygulanmaz.",
            "",
            "| Varyant | Medyan net | Max DD | Korunan / elenen | Kaçırılan kazanan | Trailing maliyet zararı |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    base_ext = report["baseline"]["extended"]
    base_count = report["baseline"]["analysis"]["overall"]["count"]
    lines.append(
        f"| BASELINE | {_money(base_ext['median_net_usdt'])} | "
        f"{_money(base_ext['closed_equity_max_drawdown_usdt'])} | {base_count} / 0 | 0.0% | "
        f"{base_ext['trailing_gross_nonnegative_net_loss_count']} / {_money(base_ext['trailing_gross_nonnegative_net_loss_usdt'])} |"
    )
    for variant in report["variants"]:
        ext = variant["extended"]
        comp = variant["baseline_comparison"]
        missed = comp["missed_baseline_winner_rate_pct"]
        lines.append(
            f"| {variant['name']} | {_money(ext['median_net_usdt'])} | "
            f"{_money(ext['closed_equity_max_drawdown_usdt'])} | "
            f"{comp['preserved_baseline_trades']} / {comp['eliminated_baseline_trades']} | "
            f"{f'{missed:.1f}%' if missed is not None else '—'} | "
            f"{ext['trailing_gross_nonnegative_net_loss_count']} / {_money(ext['trailing_gross_nonnegative_net_loss_usdt'])} |"
        )
    lines.extend(["", "## Ret nedenleri", ""])
    for variant in report["variants"]:
        if not variant["rejection_reasons"]:
            continue
        lines.append(f"### {variant['name']}")
        for reason, count in variant["rejection_reasons"].items():
            lines.append(f"- {count} × {reason}")
        lines.append("")
    lines.extend(["## Çıkış modülleri", ""])
    for variant in report["variants"]:
        if variant["name"] != "net-exit":
            continue
        lines.append("### net-exit")
        for reason, stats in variant["analysis"]["exit_modules"].items():
            lines.append(
                f"- {reason}: {stats['count']} işlem, net {_money(stats['net_pnl_usdt'])}, "
                f"K/Z {stats['wins']}/{stats['losses']}"
            )
    lines.extend(
        [
            "",
            f"Kapanış mutabakatı: **{'TAMAM' if report['closeout_completed'] else 'EKSİK'}**.",
            "Ayrıntılı karar, MFE/MAE, stop, maliyet ve işlem kayıtları eşlik eden JSON dosyasındadır.",
            "",
        ]
    )
    return "\n".join(lines)
