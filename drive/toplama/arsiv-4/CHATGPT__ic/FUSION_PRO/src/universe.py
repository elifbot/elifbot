import time, math, asyncio
from dataclasses import dataclass, asdict

@dataclass
class Instrument:
    exchange: str
    symbol: str
    base: str
    quote: str
    settle: str
    contract_type: str
    tick_size: float
    qty_step: float
    min_qty: float
    status: str = 'TRADING'
    volume_24h_quote: float = 0.0
    price_change_pct: float = 0.0
    mark_price: float = 0.0
    open_interest: float = 0.0

    def to_dict(self): return asdict(self)


def _floor_step(v, step):
    if step <= 0: return v
    return math.floor(v / step + 1e-12) * step


class UniverseScanner:
    """Discovers every eligible linear futures instrument and ranks event candidates.
    It does not hard-code a 100-coin universe. Lightweight ticker monitoring covers the
    full exchange universe; expensive candle/orderbook analysis is only done for symbols
    showing abnormal activity."""
    def __init__(self, binance=None, okx=None, cfg=None):
        self.binance=binance; self.okx=okx; self.cfg=cfg or {}
        self.cache={}

    async def binance_instruments(self):
        if not self.binance: return []
        rows=await self.binance.get('/fapi/v1/exchangeInfo')
        out=[]
        for x in rows.get('symbols',[]):
            if x.get('status')!='TRADING' or x.get('quoteAsset')!='USDT': continue
            if x.get('contractType') not in ('PERPETUAL','CURRENT_QUARTER','NEXT_QUARTER'): continue
            filters={f['filterType']:f for f in x.get('filters',[])}
            lot=filters.get('LOT_SIZE',{})
            pricef=filters.get('PRICE_FILTER',{})
            out.append(Instrument('binance',x['symbol'],x['baseAsset'],x['quoteAsset'],x.get('marginAsset','USDT'),x.get('contractType',''),float(pricef.get('tickSize',0) or 0),float(lot.get('stepSize',0) or 0),float(lot.get('minQty',0) or 0)))
        return out

    async def binance_stats(self):
        if not self.binance: return {}
        rows=await self.binance.get('/fapi/v1/ticker/24hr')
        return {x['symbol']:{'volume':float(x.get('quoteVolume') or 0),'change':float(x.get('priceChangePercent') or 0),'price':float(x.get('lastPrice') or 0)} for x in rows}

    async def okx_instruments(self):
        if not self.okx: return []
        out=[]
        for inst_type in ('SWAP','FUTURES'):
            rows=await self.okx.get('/api/v5/public/instruments',{'instType':inst_type})
            for x in rows:
                if x.get('state')!='live': continue
                if x.get('settleCcy') not in ('USDT','USDC'): continue
                out.append(Instrument('okx',x['instId'],x.get('baseCcy') or x.get('uly','').split('-')[0],x.get('quoteCcy') or 'USDT',x.get('settleCcy',''),inst_type,float(x.get('tickSz') or 0),float(x.get('lotSz') or x.get('ctVal') or 0),float(x.get('minSz') or 0)))
        return out

    async def okx_stats(self):
        if not self.okx: return {}
        out={}
        for inst_type in ('SWAP','FUTURES'):
            rows=await self.okx.get('/api/v5/market/tickers',{'instType':inst_type})
            for x in rows:
                out[x['instId']]={'volume':float(x.get('volCcy24h') or x.get('vol24h') or 0),'change':0.0,'price':float(x.get('last') or 0),'bid':float(x.get('bidPx') or 0),'ask':float(x.get('askPx') or 0)}
        return out

    async def discover(self):
        b_i,b_s,o_i,o_s=await asyncio.gather(self.binance_instruments(),self.binance_stats(),self.okx_instruments(),self.okx_stats())
        for i in b_i:
            s=b_s.get(i.symbol,{}) ; i.volume_24h_quote=s.get('volume',0); i.price_change_pct=s.get('change',0); i.mark_price=s.get('price',0)
        for i in o_i:
            s=o_s.get(i.symbol,{}) ; i.volume_24h_quote=s.get('volume',0); i.price_change_pct=s.get('change',0); i.mark_price=s.get('price',0)
        all_i=b_i+o_i
        self.cache={f'{i.exchange}:{i.symbol}':i for i in all_i}
        return all_i

    def rank_event_candidates(self, instruments, max_candidates=40):
        # Full-universe tracking is lightweight; deep analysis is concentrated on abnormal activity.
        rows=[]
        for i in instruments:
            v=max(i.volume_24h_quote,1.0)
            vol_score=min(1.0,math.log10(v)/10.0)
            move=min(1.0,abs(i.price_change_pct)/8.0)
            score=0.55*move+0.25*vol_score+0.20*(1.0 if i.status=='TRADING' else 0)
            rows.append((score,i))
        rows.sort(key=lambda x:x[0],reverse=True)
        return rows[:max_candidates]

    def size_qty(self, instrument, notional, price):
        raw=notional/max(price,1e-12)
        return _floor_step(raw,instrument.qty_step) if instrument.qty_step else raw
