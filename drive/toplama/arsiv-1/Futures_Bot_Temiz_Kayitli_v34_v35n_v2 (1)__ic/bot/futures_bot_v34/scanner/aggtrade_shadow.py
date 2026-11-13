"""Gözlenen aggTrade hacmi: sınırlı bellek, ana sinyal yoluna bağlı değildir.
Bağlantı ve olay kapsamı doğrulanmadı; 'kesin tam hacim' olarak kullanılamaz.
"""
from collections import deque
import math

class AggTradeShadow:
    def __init__(self):
        self._events={}; self.invalid=0; self.out_of_order=0
    def add(self,symbol,price,qty,ts):
        try: price=float(price);qty=float(qty);ts=int(ts)
        except (ValueError,TypeError,OverflowError): self.invalid+=1;return
        if ts<=0 or not all(math.isfinite(x) and x>0 for x in (price,qty,price*qty)):
            self.invalid+=1;return
        q=self._events.setdefault(symbol,deque(maxlen=181)); sec=ts//1000*1000
        if q and ts<q[-1][3]: self.out_of_order+=1;return
        if q and q[-1][0]==sec:
            q[-1][1]+=price*qty;q[-1][2]+=1;q[-1][3]=ts
        else:q.append([sec,price*qty,1,ts])
        while q and q[0][0]<sec-180_000:q.popleft()
    def snapshot(self,symbol,now):
        # Saniyelik kova kapanmadan kullanilmaz: aynı kovadaki gelecekteki
        # tradeler geriye dönük sinyal değerlendirmesine sızamaz.
        cutoff=int(now)//1000*1000
        q=self._events.get(symbol,())
        selected=[x for x in q if cutoff-120_000 <= x[0] < cutoff]
        if not selected:return {'status':'unknown','reason':'no_closed_second','coverage':'unverified'}
        recent=sum(x[1] for x in selected if x[0]>=cutoff-10_000)
        total=sum(x[1] for x in selected)
        return {'status':'observed','coverage':'unverified','bucket_ms':1000,'window_end_ms':cutoff,
                'usd_10s':recent,'usd_120s':total,'last_trade_age_ms':int(now)-selected[-1][3],
                'sample_count_120s':sum(x[2] for x in selected),
                'observed_span_ms':selected[-1][3]-selected[0][0],
                'rvol_10_120':recent/total*12 if total>0 else None}
