import math, time


def orderbook_profile(depth, levels=(5,10,20,50)):
    bids=[(float(x[0]),float(x[1])) for x in depth.get('bids',[])]
    asks=[(float(x[0]),float(x[1])) for x in depth.get('asks',[])]
    out={}
    for n in levels:
        b=sum(p*q for p,q in bids[:n]); a=sum(p*q for p,q in asks[:n]); out[f'depth_{n}']=(b-a)/(b+a) if b+a else 0.0
    out['microprice_imbalance']=out.get('depth_5',0)*0.5+out.get('depth_10',0)*0.3+out.get('depth_20',0)*0.2
    return out


def event_score(snapshot):
    move=abs(float(snapshot.get('price_change_pct_24h',0)))
    volz=abs(float(snapshot.get('volume_z',0)))
    oi=abs(float(snapshot.get('oi_change_pct',0)))
    liq=float(snapshot.get('liquidation_proxy',0))
    return round(min(100.0, 25*min(move/8,1)+25*min(volz/3,1)+25*min(oi/5,1)+25*min(liq,1)),2)


def liquidation_proxy(snapshot):
    # Proxy, not a claimed exchange liquidation feed: combines price impulse, OI flush and taker flow.
    p=abs(float(snapshot.get('price_change_pct_window',0)))/2.0
    oi=max(0.0,-float(snapshot.get('oi_change_pct',0)))/2.0
    flow=abs(float(snapshot.get('taker_imbalance',0)))
    return min(1.0,0.45*min(p,1)+0.35*min(oi,1)+0.20*min(flow,1))


def signal_quality(a, snap):
    score=float(a.get('score',0)); edge=float(a.get('edge_bps',0)); conf=float(a.get('confidence',0));
    event=float(snap.get('event_score',0))/100.0
    data=max(0.0,1.0-float(snap.get('data_age_sec',0))/max(1,float(snap.get('stale_limit',12))))
    return round(max(0,min(100, score/11*40 + min(edge/20,1)*20 + conf*20 + event*10 + data*10)),2)


def signal_expired(created_ts, max_age_sec):
    return (time.time()*1000-created_ts)/1000 > max_age_sec


def portfolio_beta(symbol, side, exposures):
    # Lightweight symbol-family correlation proxy. BTC beta is 1; other majors/altcoins are grouped.
    s=symbol.upper(); beta=1.0 if 'BTC' in s else 0.75 if any(k in s for k in ('ETH','SOL','BNB','XRP')) else 0.55
    signed=beta*(1 if side=='LONG' else -1)
    return signed, sum(v for v in exposures.values())
