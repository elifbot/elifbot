"""Sinyal birleştirici — botun "beyni".
  Toplam skor = indikatör + para akışı + haber + ML yön tahmini
  GİRİŞ: skor >= +long_esik → LONG | skor <= -short_esik → SHORT
"""
from __future__ import annotations

class Strategy:
    def __init__(
        self,
        w_ind: float = 0.50,
        w_flow: float = 0.30,
        w_news: float = 0.20,
        long_th: float = 55,
        short_th: float = -55,
        exit_th: float = 15,
        allow_short: bool = True,
        w_ml: float = 0.0,
        flow_trigger: bool = True,
        flow_th: float = 50.0,
        flow_ind_min: float = 10.0,
        flow_min_total: float = 15.0,
    ):
        self.flow_trigger = bool(flow_trigger)
        self.flow_th = float(flow_th)
        self.flow_ind_min = float(flow_ind_min)
        self.flow_min_total = float(flow_min_total)
        self.w_ind = float(w_ind)
        self.w_flow = float(w_flow)
        self.w_news = float(w_news)
        self.w_ml = float(w_ml)
        self.long_th = float(long_th)
        self.short_th = float(short_th)
        self.exit_th = float(exit_th)
        self.allow_short = bool(allow_short)

    def evaluate(self, ind_score: float, flow_score: float, news_score: float, ml_score: float = 0.0) -> dict:
        total_score = (
            ind_score * self.w_ind +
            flow_score * self.w_flow +
            news_score * self.w_news +
            ml_score * self.w_ml
        )
        
        signal = "HOLD"
        if total_score >= self.long_th:
            signal = "LONG"
        elif self.allow_short and total_score <= self.short_th:
            signal = "SHORT"
        elif self.flow_trigger and flow_score >= self.flow_th and ind_score >= self.flow_ind_min and total_score >= self.flow_min_total:
            signal = "LONG"
            
        return {
            "signal": signal,
            "total_score": total_score
        }