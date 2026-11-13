"""Kapalı mum getirilerinden, yönleri dikkate alan korelasyon risk kapısı.
Yalnız sayısal tarihsel tahmindir; gelecekteki korelasyon/kayıp garantisi yoktur.
"""
import math
from .data import validate_bars

def correlation_gate(candidate, candidate_side, existing, now, *, window=30, threshold=0.85, max_age=30):
    if candidate_side not in ('long','short') or type(now) is not int or now<0:raise ValueError('invalid candidate or time')
    if type(window) is not int or window<3 or type(max_age) is not int or max_age<0:raise ValueError('invalid window or age')
    try: valid_threshold=isinstance(threshold,(float,int)) and not isinstance(threshold,bool) and math.isfinite(threshold) and 0<=threshold<=1
    except OverflowError:valid_threshold=False
    if not valid_threshold:raise ValueError('invalid threshold')
    if not isinstance(existing,dict):raise ValueError('invalid existing histories')
    def returns(bars):
        if not isinstance(bars,list) or len(bars)<window+1:raise ValueError('insufficient history')
        validate_bars(bars,60)
        subset=bars[-(window+1):]
        end=subset[-1].timestamp+60
        if end>now or now-end>max_age:raise ValueError('future or stale bars')
        prices=[b.close for b in subset]
        values=[b/a-1 for a,b in zip(prices,prices[1:])]
        if not all(math.isfinite(x) for x in values):raise ValueError('invalid return')
        return [b.timestamp for b in subset],values
    try:
        times,candidate_returns=returns(candidate)
        values={}
        for symbol,item in sorted(existing.items()):
            if not isinstance(symbol,str) or not symbol or not isinstance(item,dict) or item.get('side') not in ('long','short'):raise ValueError('missing position direction')
            other_times,other_returns=returns(item.get('bars'))
            if times!=other_times:raise ValueError('unaligned timestamps')
            a_mean=math.fsum(candidate_returns)/window;b_mean=math.fsum(other_returns)/window
            da=[v-a_mean for v in candidate_returns];db=[v-b_mean for v in other_returns]
            av=math.fsum(x*x for x in da);bv=math.fsum(x*x for x in db)
            if av<=1e-28 or bv<=1e-28:raise ValueError('constant or near-constant returns')
            corr=max(-1.0,min(1.0,math.fsum(x*y for x,y in zip(da,db))/math.sqrt(av*bv)))
            direction=(1 if candidate_side==item['side'] else -1);exposure_corr=corr*direction
            values[symbol]={'price_return_correlation':corr,'directional_exposure_correlation':exposure_corr}
        if any(x['directional_exposure_correlation']>=threshold for x in values.values()):
            return {'allowed':False,'reason':'CORRELATED_EXPOSURE','correlations':values,'window_returns':window}
        return {'allowed':True,'reason':'OK','correlations':values,'window_returns':window}
    except (ValueError,TypeError,OverflowError,AttributeError) as e:
        return {'allowed':False,'reason':'CORRELATION_UNKNOWN','detail':str(e),'correlations':{}}
