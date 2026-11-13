"""v9.4.1 descriptive gate cohorts, not causal gate-profit claims.

Occurrence counts, retained unique cohorts and matured horizon denominators are
separate. LONG/SHORT are never silently pooled without disclosing both counts.
"""
from __future__ import annotations
import math
import time
from typing import Any


class CounterfactualTracker:
    def __init__(self,max_blocked_records=800,dedup_sec=45.,horizon_tolerance_sec=30.):
        self.max_blocked_records=max(50,int(max_blocked_records));self.dedup_sec=max(5.,float(dedup_sec))
        self.horizon_tolerance_sec=max(0.,float(horizon_tolerance_sec))
        self._last_gate_log={};self._decision_ids=set();self.blocked_signals=[];self.gate_counts={}
        self.unique_counts={};self.dropped_counts={}
        self.shadow_legacy_cuts={};self.completed_shadow_comparisons=[]

    def record_blocked_signal(self,*,gate,symbol,side,price,reason='',now_ts=None,
                              decision_id=None,exchange=None,roundtrip_cost_bps=13.,cohort_type='FIRST_FAILURE_CONDITIONAL',tactical_stop_bps=None):
        if side not in ('LONG','SHORT') or not math.isfinite(float(price)) or price<=0:return
        now=float(now_ts if now_ts is not None else time.time())
        if not math.isfinite(now) or not math.isfinite(float(roundtrip_cost_bps)) or roundtrip_cost_bps<0:return
        g=str(gate or 'unknown');b=self.gate_counts.setdefault(g,{'LONG':0,'SHORT':0,'total':0})
        b[side]+=1;b['total']+=1
        key=(g,symbol,side,exchange)
        if decision_id is not None:
            event=key+(str(decision_id),)
            if event in self._decision_ids:return
            self._decision_ids.add(event)
            # Retain sufficient identities for this bounded in-memory session.
            if len(self._decision_ids)>100000:self._decision_ids={event}
        else:
            prior=self._last_gate_log.get(key)
            if prior is not None and now-prior<self.dedup_sec:return
            self._last_gate_log[key]=now
        unique=self.unique_counts.setdefault(g,{'LONG':0,'SHORT':0});unique[side]+=1
        self.blocked_signals.append({'gate':g,'symbol':symbol,'side':side,'entry_price':float(price),
            'ts':now,'reason':str(reason)[:150],'decision_id':decision_id,'exchange':exchange,
            'cohort_type':cohort_type,'roundtrip_cost_bps':float(roundtrip_cost_bps),
            'tactical_stop_bps':tactical_stop_bps,'mae_5m_bps':None,'mae_15m_bps':None,'mfe_5m_bps':None,'mfe_15m_bps':None,
            'px_5m':None,'px_15m':None,'observed_5m_ts':None,'observed_15m_ts':None,
            'latest_px':float(price),'latest_ts':now,'observed_mae_bps':0.,'observed_mfe_bps':0.})
        while len(self.blocked_signals)>self.max_blocked_records:
            gone=self.blocked_signals.pop(0);self.dropped_counts[gone['gate']]=self.dropped_counts.get(gone['gate'],0)+1

    def on_price_update(self,symbol,price,now_ts=None,exchange=None):
        if not math.isfinite(float(price)) or price<=0:return
        now=float(now_ts if now_ts is not None else time.time())
        for row in self.blocked_signals:
            if row['symbol']!=symbol or now<row['latest_ts']:continue
            if row.get('exchange') is not None and exchange!=row['exchange']:continue
            row['latest_px']=float(price);row['latest_ts']=now;age=now-row['ts']
            if age<0:continue
            if row['px_15m'] is None and age<=900+self.horizon_tolerance_sec:
                ret=self._signed_ret_bps(row['side'],row['entry_price'],price)
                row['observed_mae_bps']=min(row['observed_mae_bps'],ret)
                row['observed_mfe_bps']=max(row['observed_mfe_bps'],ret)
            for label,horizon in (('5m',300.),('15m',900.)):
                if row['px_'+label] is None and horizon<=age<=horizon+self.horizon_tolerance_sec:
                    row['px_'+label]=float(price);row['observed_'+label+'_ts']=now
                    row['mae_'+label+'_bps']=row['observed_mae_bps'];row['mfe_'+label+'_bps']=row['observed_mfe_bps']

    @staticmethod
    def _signed_ret_bps(side,entry_px,future_px):
        if future_px is None or entry_px<=0 or future_px<=0:return None
        result=(future_px-entry_px)/entry_px*10000
        return result if side=='LONG' else -result

    def record_shadow_legacy_time_cut(
        self,
        *,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        shadow_cut_price: float,
        qty: float,
        entry_fee_usdt: float,
        age_sec: float,
        now_ts: float | None = None,
    ) -> None:
        """Eski 135sn zaman kesicisinin tetikleneceği ilk anı gölgede kaydeder (pozisyonu kapatmaz!)."""
        if not position_id or position_id in self.shadow_legacy_cuts or qty <= 0:
            return
        now = float(now_ts if now_ts is not None else time.time())
        gross = (
            (shadow_cut_price - entry_price) * qty
            if side == "LONG"
            else (entry_price - shadow_cut_price) * qty
        )
        taker_exit_fee = shadow_cut_price * qty * 0.0005
        shadow_net = gross - float(entry_fee_usdt) - taker_exit_fee
        self.shadow_legacy_cuts[position_id] = {
            "position_id": position_id,
            "symbol": symbol,
            "side": side,
            "age_at_shadow_cut_sec": round(age_sec, 1),
            "shadow_cut_price": float(shadow_cut_price),
            "shadow_legacy_net_pnl_usdt": round(shadow_net, 4),
            "ts": now,
        }

    def resolve_shadow_cut_on_close(
        self,
        *,
        position_id: str,
        actual_net_pnl_usdt: float,
        exit_reason: str,
    ) -> None:
        snap = self.shadow_legacy_cuts.pop(position_id, None)
        if snap is None:
            return
        delta = float(actual_net_pnl_usdt) - float(snap["shadow_legacy_net_pnl_usdt"])
        self.completed_shadow_comparisons.append(
            {
                **snap,
                "actual_v92_net_pnl_usdt": round(float(actual_net_pnl_usdt), 4),
                "v92_minus_legacy_135s_usdt": round(delta, 4),
                "actual_exit_reason": exit_reason,
            }
        )

    def summary(self,now_ts=None):
        asof=float(now_ts if now_ts is not None else time.time())
        gates={}
        for gate,counts in self.gate_counts.items():
            samples=[r for r in self.blocked_signals if r['gate']==gate]
            per_side={}
            for side in ('LONG','SHORT'):
                rows=[r for r in samples if r['side']==side]
                stats={'retained_unique':len(rows)}
                for label,horizon in (('5m',300.),('15m',900.)):
                    observed=[r for r in rows if r['px_'+label] is not None]
                    gross=[self._signed_ret_bps(side,r['entry_price'],r['px_'+label]) for r in observed]
                    net=[v-r['roundtrip_cost_bps'] for v,r in zip(gross,observed)]
                    stats[label]={'matured_observed_n':len(observed),
                        'pending_n':sum(r['px_'+label] is None and asof-r['ts']<horizon for r in rows),
                        'in_observation_window_n':sum(r['px_'+label] is None and horizon<=asof-r['ts']<=horizon+self.horizon_tolerance_sec for r in rows),
                        'missed_or_unobserved_n':sum(r['px_'+label] is None and asof-r['ts']>horizon+self.horizon_tolerance_sec for r in rows),
                        'signed_gross_mark_return_bps':round(sum(gross)/len(gross),4) if gross else None,
                        'cost_scenario_mark_return_bps':round(sum(net)/len(net),4) if net else None,
                        'stress_8bps_per_side_mark_return_bps':round(sum(v-r['roundtrip_cost_bps']-10 for v,r in zip(gross,observed))/len(observed),4) if observed else None,
                        'observed_mean_mae_bps':round(sum(r['mae_'+label+'_bps'] for r in observed)/len(observed),4) if observed else None,
                        'observed_worst_mae_bps':min((r['mae_'+label+'_bps'] for r in observed),default=None),
                        'observed_mean_mfe_bps':round(sum(r['mfe_'+label+'_bps'] for r in observed)/len(observed),4) if observed else None,
                        'observed_emergency_8pct_barrier_touches':sum(r['mae_'+label+'_bps']<=-800 for r in observed),
                        'observed_initial_tactical_barrier_touches':sum(r.get('tactical_stop_bps') is not None and r['mae_'+label+'_bps']<=-r['tactical_stop_bps'] for r in observed)}
                    from .gate_statistics import confidence
                    observations=[{'day':int(r['ts'])//86400,'symbol':r['symbol'],'gross_bps':v,
                        'net_base_bps':v-r['roundtrip_cost_bps'],'net_stress_bps':v-r['roundtrip_cost_bps']-10} for v,r in zip(gross,observed)]
                    stats[label]['confidence']=confidence(observations)
                per_side[side]=stats
            r5=[self._signed_ret_bps(r['side'],r['entry_price'],r['px_5m']) for r in samples if r['px_5m'] is not None]
            r15=[self._signed_ret_bps(r['side'],r['entry_price'],r['px_15m']) for r in samples if r['px_15m'] is not None]
            latest=[self._signed_ret_bps(r['side'],r['entry_price'],r['latest_px']) for r in samples]
            gates[gate]={'blocked_long':counts['LONG'],'blocked_short':counts['SHORT'],'total':counts['total'],
                'count_semantics':'raw gate occurrences, not independent trades',
                'sampled_unique':len(samples),'lifetime_unique':sum(self.unique_counts.get(gate,{}).values()),
                'dropped_retained_cohorts':self.dropped_counts.get(gate,0),
                'matured_5m_n':len(r5),'matured_15m_n':len(r15),
                'blocked_signal_5m_signed_bps':round(sum(r5)/len(r5),2) if r5 else None,
                'blocked_signal_15m_signed_bps':round(sum(r15)/len(r15),2) if r15 else None,
                'blocked_signal_latest_signed_bps':round(sum(latest)/len(latest),2) if latest else None,
                'by_side':per_side,'interpretation':'DESCRIPTIVE_OPPORTUNITY_COST_HINT_NOT_EXECUTED_NET_PROFIT_OR_CAUSAL_EFFECT'}
        delta=sum(c['v92_minus_legacy_135s_usdt'] for c in self.completed_shadow_comparisons)
        return {'gate_asymmetry_and_forward_returns':gates,
            'measurement_notes':{'asof_epoch':asof,'horizon_tolerance_sec':self.horizon_tolerance_sec,
            'sample_unit':'gate-symbol-side-venue-decision_id when supplied, otherwise 45s temporal dedup',
            'not_independent':'Horizons overlap and symbols share market factors. No IID significance claim.',
            'cost_scenario':'Base = 7bps fee + 2x3bps slippage + recorded spread; stress = 7 + 2x8 + spread. No fill queue/funding/stop-path PnL simulation.',
            'mae_scope':'Observed quote path only; absence of an observed barrier touch is not proof the exchange price never touched it.',
            'causality':'First failing gates see a conditional, order-dependent sample; no automatic gate-removal recommendation.'},
            'shadow_135s_cut_comparison':{'completed_count':len(self.completed_shadow_comparisons),
                'active_open_shadow_count':len(self.shadow_legacy_cuts),'net_advantage_of_holding_usdt':round(delta,4),
                'comparisons':self.completed_shadow_comparisons[-25:]}}
