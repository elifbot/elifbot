"""strategies/v92_flow_strategy.py — v9.2 Kanonik Strateji & 10-Ajan Çapraz Teftiş Backtest Adaptörü.

`walk_forward.py`, `ablation.py` ve `stress.py` motorlarının doğrudan canlı `v9.2`
sinyal + rejim + 10-ajan çapraz teftiş mantığını (lookahead olmadan, dondurulmuş
parametrelerle) test edebilmesini sağlar.
"""
from __future__ import annotations

import pandas as pd

from src.indicators import indicator_score
from src.pdf_core_confluence import compute_pdf_core_confluence
from src.ten_agent_debate import TenAgentMutualAuditCouncil
from strategies.base import (
    HOLD,
    LONG,
    SHORT,
    Contributor,
    SignalResult,
    StrategyBase,
)


class V92CanonicalFlowStrategy(StrategyBase):
    """v9.2 İndikatör + Hacim Akışı + Choppiness/Rejim + 10-Ajan Çapraz Teftiş Stratejisi."""

    STATUS = "CANONICAL_V92"
    NAME = "v92_canonical_flow_10agent"
    MIN_ROWS = 45

    def __init__(
        self,
        *,
        entry_score_th: float = 20.0,
        max_choppiness: float = 61.8,
        min_consensus_votes: int = 7,
        min_gross_fee_mult: float = 3.2,
    ) -> None:
        super().__init__()
        self.entry_score_th = float(entry_score_th)
        self.max_choppiness = float(max_choppiness)
        self.min_consensus_votes = int(min_consensus_votes)
        self.min_gross_fee_mult = float(min_gross_fee_mult)
        self._council = TenAgentMutualAuditCouncil(
            min_consensus_votes=self.min_consensus_votes,
            min_expected_gross_fee_mult=self.min_gross_fee_mult,
        )

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        problem = self._check_frame(df)
        if problem:
            return self._hold(problem, df)

        ind = indicator_score(df)
        ind_val = float(ind.get("score", 0.0))
        pdf_core = compute_pdf_core_confluence(df)
        chop = float(pdf_core.get("choppiness_14", 50.0))
        vwap_z = float(pdf_core.get("vwap20_z", 0.0))

        # Mum tabanlı para akışı vekili: mum gövdesi yönü × bağıl hacim
        closes = df["close"].astype(float)
        opens = df["open"].astype(float)
        vols = df["volume"].astype(float)
        vol_med = float(vols.iloc[-20:].median() or 1.0)
        rvol = float(vols.iloc[-1]) / max(vol_med, 1e-9)
        signed_body = ((closes.iloc[-3:] - opens.iloc[-3:]) / opens.iloc[-3:].replace(0, 1.0) * 100.0)
        flow_proxy = max(-80.0, min(80.0, float((signed_body * (vols.iloc[-3:] / max(vol_med, 1e-9))).sum()) * 18.0))

        price = float(closes.iloc[-1])
        high_s = df["high"].astype(float)
        low_s = df["low"].astype(float)
        tr = (high_s.iloc[-14:] - low_s.iloc[-14:]).mean()
        atr_pct = (float(tr) / price * 100.0) if price > 0 else 0.35

        combined = 0.52 * (ind_val + float(pdf_core.get("score_delta", 0.0))) + 0.48 * flow_proxy

        cand_side = HOLD
        if combined >= self.entry_score_th:
            cand_side = LONG
        elif combined <= -self.entry_score_th:
            cand_side = SHORT

        log = [
            Contributor("ind_score", round(ind_val, 2), cand_side, "TREND_IND").as_dict(),
            Contributor("flow_proxy", round(flow_proxy, 2), cand_side, "VOLUME_FLOW").as_dict(),
            Contributor("choppiness_14", round(chop, 2), "OK" if chop < self.max_choppiness else "CHOP", "CHOP_REGIME").as_dict(),
        ]

        if cand_side == HOLD:
            return self._hold("skor_esik_altinda", df)

        dir_sign = 1.0 if cand_side == LONG else -1.0
        ind_ok = self._req("TREND_IND", ind_val * dir_sign >= 8.0)
        flow_ok = self._req("VOLUME_FLOW", flow_proxy * dir_sign >= 4.0)
        chop_ok = self._req("CHOP_REGIME", chop < self.max_choppiness)

        audit = self._council.evaluate_entry(
            {
                "symbol": "BACKTEST/USDT",
                "side": cand_side,
                "ind_score": ind_val,
                "flow_score": flow_proxy,
                "combined_score": combined,
                "atr_pct": atr_pct,
                "spread_pct": 0.015,
                "roundtrip_fee_pct": 0.04,
                "choppiness_14": chop,
                "rvol": rvol,
                "vwap_atr_z": vwap_z,
                "mtf_aligned": True,
            }
        )
        log.append(
            Contributor(
                "ten_agent_audit",
                float(audit["consensus_votes"]),
                cand_side if audit["approved"] else HOLD,
                "TEN_AGENT_AUDIT",
            ).as_dict()
        )
        audit_ok = self._req("TEN_AGENT_AUDIT", bool(audit["approved"]))

        if ind_ok and flow_ok and chop_ok and audit_ok:
            sig = cand_side
            reg = "v92_onayli"
        else:
            sig = HOLD
            reg = "filtre_reddi"

        self._state["evaluations"] += 1
        self._state["last_signal"] = sig
        return SignalResult(
            signal=sig,
            strategy_name=self.NAME,
            regime=reg,
            contributor_log=log,
            active_families=["TREND_IND", "VOLUME_FLOW", "CHOP_REGIME", "TEN_AGENT_AUDIT"],
            missing_families=[],
            data_timestamp=int(df.iloc[-1]["open_time"]),
            status=self.STATUS,
        )
