import os, time, uuid

class LiveBroker:
    """Thin live execution layer. Disabled unless config trading.live_enabled=true."""
    def __init__(self, adapter, cfg): self.adapter=adapter; self.cfg=cfg; self.positions={}
    async def open(self,signal,plan):
        symbol=signal['symbol']; side=signal['side']; lev=int(plan['leverage']); await self.adapter.set_cross_leverage(symbol,lev)
        # Maker-first entry: place slightly inside the book only if it remains post-only.
        entry=float(signal['entry']); bps=float(self.cfg['trading'].get('maker_entry_requote_bps',2.0))/10000
        price=entry*(1-bps if side=='LONG' else 1+bps)
        cid=('fp'+uuid.uuid4().hex)[:28]
        order=await self.adapter.place_maker_entry(symbol,side,plan['qty'],price,cid)
        pos={'id':cid,'symbol':symbol,'side':side,'qty':plan['qty'],'entry_order':order,'stop':plan['stop'],'target':plan['target'],'margin':plan['margin'],'leverage':lev,'opened_ts':int(time.time()*1000)}
        self.positions[cid]=pos
        return pos
    async def close(self,pid):
        p=self.positions.get(pid)
        if not p:return None
        out=await self.adapter.close_position(p['symbol'],p['side'],p['qty']); self.positions.pop(pid,None); return out
