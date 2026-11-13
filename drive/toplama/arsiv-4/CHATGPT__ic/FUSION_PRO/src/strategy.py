from .indicators import enrich
from .features import taker_imbalance, oi_price_context, expected_edge_bps, volume_zscore, bb_width_pct
from .advanced import orderbook_profile, liquidation_proxy, signal_quality, event_score

def analyze(df, snap, cfg, htf_bias=None):
    x=enrich(df); r=x.iloc[-1]; p=float(r.close); atr=float(r.atr); reasons=[]; vetoes=[]; long=short=0.0
    if r.ema20>r.ema50>r.ema200: long+=2; reasons.append('EMA trend bullish')
    elif r.ema20<r.ema50<r.ema200: short+=2; reasons.append('EMA trend bearish')
    else: reasons.append('EMA mixed')
    if r.macd_hist>0: long+=1
    elif r.macd_hist<0: short+=1
    if r.rsi>54: long+=1
    elif r.rsi<46: short+=1
    if r.adx>=cfg['strategy']['adx_trend']:
        if p>r.vwap: long+=1
        elif p<r.vwap: short+=1
    if r.stoch_k>r.stoch_d and r.stoch_k<88: long+=0.75
    elif r.stoch_k<r.stoch_d and r.stoch_k>12: short+=0.75
    if r.close>r.bb_mid: long+=0.5
    elif r.close<r.bb_mid: short+=0.5
    if r.cci>75: long+=0.5
    elif r.cci<-75: short+=0.5
    ti=taker_imbalance(x)
    if ti>0.12: long+=1; reasons.append('taker-buy imbalance')
    elif ti<-0.12: short+=1; reasons.append('taker-sell imbalance')
    depth=float(snap['depth_imbalance'])
    if depth>0.12: long+=0.5
    elif depth<-0.12: short+=0.5
    ob=orderbook_profile(snap.get('depth_raw',{}))
    if ob.get('depth_10',0)>0.18: long+=0.35; reasons.append('multi-level bid pressure')
    elif ob.get('depth_10',0)<-0.18: short+=0.35; reasons.append('multi-level ask pressure')
    oi_ctx='neutral'
    if len(x)>=3:
        _,_,oi_ctx=oi_price_context(p,float(x.close.iloc[-3]),snap['oi'],snap.get('oi_prev',snap['oi']))
        if oi_ctx=='long_build': long+=0.5
        elif oi_ctx=='short_build': short+=0.5
    regime='TREND' if r.adx>=cfg['strategy']['adx_trend'] else 'RANGE'
    if r.atr/p>0.018: regime='HIGH_VOL'
    if r.atr/p<0.003: regime='LOW_VOL'
    vz=volume_zscore(x); bw=bb_width_pct(r)
    if vz < cfg['strategy']['volume_z_min'] and regime in ('TREND','HIGH_VOL'): vetoes.append('volume_not_confirming')
    if bw < cfg['strategy'].get('min_bb_width_pct',0.0): vetoes.append('volatility_compressed')
    if htf_bias=='LONG': long+=1.0; reasons.append('HTF consensus long')
    elif htf_bias=='SHORT': short+=1.0; reasons.append('HTF consensus short')
    elif htf_bias=='MIXED': vetoes.append('htf_conflict')
    if snap['spread_bps']>cfg['market']['max_spread_bps']: vetoes.append('spread_too_wide')
    if snap['data_age_sec']>cfg['market']['stale_sec']: vetoes.append('stale_market')
    if snap.get('funding_guard_active'): vetoes.append('funding_settlement_risk')
    score=max(long,short); side='LONG' if long>short else 'SHORT' if short>long else 'FLAT'
    edge=expected_edge_bps((r.atr/p),score,snap['spread_bps'],cfg['execution']['fee_bps_roundtrip'],cfg['execution']['slippage_bps_side']*2)
    if edge<cfg['strategy']['min_edge_bps']: vetoes.append('net_edge_too_small')
    dynamic_min=cfg['strategy']['min_score'] + (1.0 if regime=='HIGH_VOL' else 0.0) + (0.5 if regime=='RANGE' else 0.0)
    if score<dynamic_min: vetoes.append('score_below_threshold')
    if regime=='RANGE' and score<8.0: vetoes.append('range_not_strong_enough')
    if side=='LONG' and p<r.vwap and regime=='TREND': vetoes.append('below_vwap')
    if side=='SHORT' and p>r.vwap and regime=='TREND': vetoes.append('above_vwap')
    confidence=min(0.99,max(0.01,score/11*0.55 + min(abs(ti),1)*0.15 + min(abs(depth),1)*0.10 + min(max(r.adx,0),40)/40*0.10 + min(abs(ob.get('depth_20',0)),1)*0.10))
    stop=p-(cfg['risk'].get('atr_stop_mult',1.6)*atr) if side=='LONG' else p+(cfg['risk'].get('atr_stop_mult',1.6)*atr)
    target=p+cfg['strategy'].get('target_r',2.2)*abs(p-stop) if side=='LONG' else p-cfg['strategy'].get('target_r',2.2)*abs(stop-p)
    rr=abs(target-p)/max(abs(p-stop),1e-12)
    if rr<cfg['strategy']['min_rr']: vetoes.append('rr_too_low')
    snap['taker_imbalance']=ti; snap['volume_z']=vz; snap['price_change_pct_window']=float((p/x.close.iloc[-6]-1)*100) if len(x)>=6 else 0
    snap['liquidation_proxy']=liquidation_proxy(snap); snap['event_score']=event_score(snap); snap['stale_limit']=cfg['market']['stale_sec']
    quality=signal_quality({'score':score,'edge_bps':edge,'confidence':confidence},snap)
    if quality<cfg['strategy'].get('min_quality_score',65): vetoes.append('quality_below_threshold')
    return {'side':side,'score':round(score,2),'edge_bps':round(edge,2),'regime':regime,'entry':p,'stop':stop,'target':target,'rr':round(rr,2),'quality_score':quality,'reasons':reasons+['oi:'+oi_ctx], 'vetoes':vetoes,'confidence':round(confidence,3),'atr':atr,'features':{'rsi':float(r.rsi),'adx':float(r.adx),'taker_imbalance':float(ti),'depth_imbalance':depth,'depth_5':ob.get('depth_5',0),'depth_10':ob.get('depth_10',0),'depth_20':ob.get('depth_20',0),'volume_z':float(vz),'bb_width_pct':float(bw),'liquidation_proxy':snap['liquidation_proxy'],'event_score':snap['event_score']}}
