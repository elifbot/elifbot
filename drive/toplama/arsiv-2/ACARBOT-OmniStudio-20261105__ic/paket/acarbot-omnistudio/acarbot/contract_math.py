"""Experimental, PAPER-only contract math. NOT connected to trading runner.

Native settlement units, explicit multipliers, Decimal and quantity steps.
No FX equivalence, live execution, automatic expiry, actual fees/funding or
portfolio risk claim. Callers must provide validated exchange metadata/prices.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, localcontext

def D(x):
    try:v=Decimal(str(x))
    except (InvalidOperation,ValueError):raise ValueError('invalid decimal') from None
    if not v.is_finite():raise ValueError('non-finite decimal')
    return v

def positive(x):
    v=D(x)
    if v<=0:raise ValueError('must be positive')
    return v

@dataclass(frozen=True)
class ContractSpec:
    market:str
    symbol:str
    kind:str                 # linear/inverse
    settlement:str
    face:Decimal             # linear BASE per unit, inverse QUOTE per contract
    lot_step:Decimal
    min_qty:Decimal
    tick_size:Decimal
    expires_ms:int|None=None
    def __post_init__(self):
        if self.kind not in ('linear','inverse') or not self.settlement or not self.symbol:raise ValueError('unknown contract')
        for x in (self.face,self.lot_step,self.min_qty,self.tick_size):positive(x)
        if self.expires_ms is not None and self.expires_ms<=0:raise ValueError('bad expiry')
    def qty(self,desired):
        q=D(desired)
        if q<=0:raise ValueError('non-positive size')
        q=(q/self.lot_step).to_integral_value(rounding=ROUND_DOWN)*self.lot_step
        if q<self.min_qty:raise ValueError('quantity below minimum')
        return q
    def pnl(self,side,qty,entry,exit):
        if side not in ('LONG','SHORT'):raise ValueError('bad side')
        q=positive(qty);a=positive(entry);b=positive(exit)
        sign=D(1 if side=='LONG' else -1)
        with localcontext() as ctx:
            ctx.prec=34
            return sign*q*self.face*((b-a) if self.kind=='linear' else (D(1)/a-D(1)/b))
    def value_in_settlement(self,qty,price):
        q=positive(qty);p=positive(price)
        return q*self.face*p if self.kind=='linear' else q*self.face/p
    def fee(self,qty,price,fee_rate):
        rate=D(fee_rate)
        if not D(0)<=rate<D(1):raise ValueError('bad fee rate')
        return self.value_in_settlement(qty,price)*rate
    def funding_delta(self,side,qty,mark,rate):
        if side not in ('LONG','SHORT'):raise ValueError('bad side')
        return -D(1 if side=='LONG' else -1)*self.value_in_settlement(qty,mark)*D(rate)

def from_exchange_record(market,r):
    """Map common public specs; fail closed for unsupported or ambiguous records."""
    if market in ('binance_usdm','binance_coinm'):
        state='status' if market=='binance_usdm' else 'contractStatus'
        if r.get(state)!='TRADING':raise ValueError('inactive')
        filters={x.get('filterType'):x for x in r.get('filters',[])}
        lot=filters.get('LOT_SIZE') or {};tick=filters.get('PRICE_FILTER') or {}
        base=r.get('baseAsset');quote=r.get('quoteAsset');settle=r.get('marginAsset')
        if not all((base,quote,settle)):raise ValueError('currency metadata missing')
        kind='linear' if market=='binance_usdm' else 'inverse'
        if (kind=='linear' and settle!=quote) or (kind=='inverse' and settle!=base):raise ValueError('ambiguous settlement')
        face=D(1) if kind=='linear' else positive(r.get('contractSize'))
        ctype=r.get('contractType',''); exp=None if 'PERPETUAL' in ctype else int(r.get('deliveryDate') or 0)
        return ContractSpec(market,r['symbol'],kind,settle,face,positive(lot.get('stepSize')),positive(lot.get('minQty')),positive(tick.get('tickSize')),exp)
    if market in ('okx_swap','okx_futures'):
        if r.get('state')!='live':raise ValueError('inactive')
        symbol=r['instId'];base=symbol.split('-')[0];kind=r.get('ctType');settle=r.get('settleCcy');face_ccy=r.get('ctValCcy');quoted=symbol.split('-')[1].split('_')[0]
        if kind=='linear' and (face_ccy!=base or settle!=quoted):raise ValueError('ambiguous linear units')
        if kind=='inverse' and (face_ccy!=quoted or settle!=base):raise ValueError('ambiguous inverse units')
        face=positive(r.get('ctVal'))*positive(r.get('ctMult'))
        expiry=int(r['expTime']) if r.get('expTime') else None
        return ContractSpec(market,symbol,kind,settle,face,positive(r.get('lotSz')),positive(r.get('minSz')),positive(r.get('tickSz')),expiry)
    raise ValueError('unknown market')

@dataclass
class Position:
    spec:ContractSpec
    side:str
    qty:Decimal
    entry:Decimal
    entry_fee:Decimal
    opened_ms:int
    funding:Decimal=D(0)

class CurrencyLedger:
    """Isolated unit-testable accounting core; not the V10 trading engine.

    Balances are explicitly seeded per currency; no USDT=USD=USDC assumption.
    Margin, liquidation and cross-currency risk are NOT modelled. Expiry is
    blocked, not automatically settled. Caller must provide real funding time.
    """
    def __init__(self,balances):
        self.balance={k:D(v) for k,v in balances.items()};self.positions={};self.funding_ids=set()
    def open(self,spec,side,desired,entry,fee_rate,now_ms):
        key=(spec.market,spec.symbol)
        if key in self.positions:raise ValueError('duplicate position')
        if side not in ('LONG','SHORT'):raise ValueError('bad side')
        if spec.expires_ms and now_ms>=spec.expires_ms:raise ValueError('expired')
        if spec.settlement not in self.balance:raise ValueError('missing settlement balance')
        qty=spec.qty(desired);px=positive(entry);fee=spec.fee(qty,px,fee_rate)
        if self.balance[spec.settlement]<fee:raise ValueError('insufficient fee balance')
        self.balance[spec.settlement]-=fee
        pos=Position(spec,side,qty,px,fee,now_ms);self.positions[key]=pos;return pos
    def apply_funding(self,market,symbol,event_id,mark,rate,at_ms):
        p=self.positions[(market,symbol)];key=(market,symbol,event_id)
        if not event_id or key in self.funding_ids:raise ValueError('duplicate/missing funding id')
        if at_ms<=p.opened_ms:raise ValueError('funding time not after open')
        if p.spec.expires_ms and at_ms>=p.spec.expires_ms:raise ValueError('expired')
        delta=p.spec.funding_delta(p.side,p.qty,mark,rate)
        self.balance[p.spec.settlement]+=delta;p.funding+=delta;self.funding_ids.add(key);return delta
    def close(self,market,symbol,exit,fee_rate,now_ms):
        key=(market,symbol);p=self.positions[key]
        if now_ms<p.opened_ms:raise ValueError('close before open')
        if p.spec.expires_ms and now_ms>=p.spec.expires_ms:raise ValueError('expiry requires official settlement handling')
        px=positive(exit);pnl=p.spec.pnl(p.side,p.qty,p.entry,px);fee=p.spec.fee(p.qty,px,fee_rate)
        self.balance[p.spec.settlement]+=pnl-fee;del self.positions[key]
        return {'currency':p.spec.settlement,'gross':pnl,'entry_fee':p.entry_fee,'exit_fee':fee,'funding':p.funding,'net':pnl-p.entry_fee-fee+p.funding}
