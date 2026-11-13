import base64, hashlib, hmac, json, time, uuid
import httpx
from .exchange_base import ExchangeAdapter

class OKXTrade(ExchangeAdapter):
    name='okx'
    def __init__(self, api_key, secret_key, passphrase, base='https://www.okx.com', demo=False):
        self.api_key=api_key; self.secret=secret_key; self.passphrase=passphrase; self.base=base.rstrip('/'); self.demo=demo
        self.client=httpx.AsyncClient(timeout=10, headers={'User-Agent':'FusionPro/3.0'})
    async def close(self): await self.client.aclose()
    def _headers(self,method,path,body=''):
        ts=time.strftime('%Y-%m-%dT%H:%M:%S.000Z',time.gmtime())
        msg=ts+method+path+body; sig=base64.b64encode(hmac.new(self.secret.encode(),msg.encode(),hashlib.sha256).digest()).decode()
        return {'OK-ACCESS-KEY':self.api_key,'OK-ACCESS-SIGN':sig,'OK-ACCESS-TIMESTAMP':ts,'OK-ACCESS-PASSPHRASE':self.passphrase,'Content-Type':'application/json','x-simulated-trading':'1' if self.demo else '0'}
    async def _req(self,method,path,payload=None):
        body=json.dumps(payload,separators=(',',':')) if payload is not None else ''
        r=await self.client.request(method,self.base+path,content=body,headers=self._headers(method,path,body)); r.raise_for_status(); d=r.json()
        if d.get('code')!='0': raise RuntimeError(f"OKX error {d}")
        return d['data']
    async def get_balance(self):
        rows=await self._req('GET','/api/v5/account/balance');
        if not rows:return 0.0
        details=rows[0].get('details',[]); usdt=next((x for x in details if x.get('ccy')=='USDT'),None); return float(usdt.get('availEq') or usdt.get('cashBal') or 0) if usdt else 0.0
    async def set_cross_leverage(self,symbol,leverage):
        return await self._req('POST','/api/v5/account/set-leverage',{'instId':symbol,'lever':str(leverage),'mgnMode':'cross'})
    async def place_maker_entry(self,symbol,side,qty,price,client_id):
        return (await self._req('POST','/api/v5/trade/order',{'instId':symbol,'tdMode':'cross','side':'buy' if side=='LONG' else 'sell','ordType':'post_only','px':str(price),'sz':str(qty),'clOrdId':client_id}))[0]
    async def place_protective_exit(self,symbol,side,qty,stop,target,client_id):
        # OKX algo orders are conditional; triggered exits can be taker. Entry remains post-only.
        exit_side='sell' if side=='LONG' else 'buy'
        sl=(await self._req('POST','/api/v5/trade/order-algo',{'instId':symbol,'tdMode':'cross','side':exit_side,'ordType':'conditional','sz':str(qty),'slTriggerPx':str(stop),'slOrdPx':'-1','reduceOnly':'true','algoClOrdId':client_id+'-SL'}))[0]
        tp=(await self._req('POST','/api/v5/trade/order-algo',{'instId':symbol,'tdMode':'cross','side':exit_side,'ordType':'conditional','sz':str(qty),'tpTriggerPx':str(target),'tpOrdPx':'-1','reduceOnly':'true','algoClOrdId':client_id+'-TP'}))[0]
        return {'stop':sl,'target':tp}
    async def cancel_order(self,symbol,order_id): return (await self._req('POST','/api/v5/trade/cancel-order',{'instId':symbol,'ordId':order_id}))[0]
    async def close_position(self,symbol,side,qty):
        return (await self._req('POST','/api/v5/trade/order',{'instId':symbol,'tdMode':'cross','side':'sell' if side=='LONG' else 'buy','ordType':'market','sz':str(qty),'reduceOnly':'true'}))[0]
