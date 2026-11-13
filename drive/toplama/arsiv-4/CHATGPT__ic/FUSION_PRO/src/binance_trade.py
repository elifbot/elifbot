import hashlib, hmac, time, uuid
from urllib.parse import urlencode
import httpx
from .exchange_base import ExchangeAdapter

class BinanceTrade(ExchangeAdapter):
    name = 'binance'
    def __init__(self, api_key, api_secret, base='https://fapi.binance.com', recv_window=5000):
        self.api_key=api_key; self.api_secret=api_secret; self.base=base.rstrip('/'); self.recv_window=recv_window
        self.client=httpx.AsyncClient(timeout=10, headers={'X-MBX-APIKEY':api_key,'User-Agent':'FusionPro/3.0'})
    async def close(self): await self.client.aclose()
    def _sign(self, params):
        q=urlencode(params, doseq=True); sig=hmac.new(self.api_secret.encode(),q.encode(),hashlib.sha256).hexdigest(); return q+'&signature='+sig
    async def _signed(self, method, path, params=None):
        p=dict(params or {}); p['timestamp']=int(time.time()*1000); p['recvWindow']=self.recv_window
        q=self._sign(p); url=self.base+path+('?' if method=='GET' else '')+q
        if method=='GET': r=await self.client.get(url)
        else: r=await self.client.request(method,url,data=q)
        r.raise_for_status(); return r.json()
    async def get_balance(self):
        rows=await self._signed('GET','/fapi/v2/balance');
        usdt=next((x for x in rows if x['asset']=='USDT'),None); return float(usdt['availableBalance']) if usdt else 0.0
    async def set_cross_leverage(self,symbol,leverage):
        try: await self._signed('POST','/fapi/v1/marginType',{'symbol':symbol,'marginType':'CROSSED'})
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (400,): raise
        return await self._signed('POST','/fapi/v1/leverage',{'symbol':symbol,'leverage':int(leverage)})
    async def place_maker_entry(self,symbol,side,qty,price,client_id):
        return await self._signed('POST','/fapi/v1/order',{'symbol':symbol,'side':'BUY' if side=='LONG' else 'SELL','type':'LIMIT','timeInForce':'GTX','quantity':qty,'price':price,'newClientOrderId':client_id,'newOrderRespType':'RESULT'})
    async def place_protective_exit(self,symbol,side,qty,stop,target,client_id):
        exit_side='SELL' if side=='LONG' else 'BUY'
        # Conditional market exits are protective; they are not guaranteed maker fills.
        stop_order=await self._signed('POST','/fapi/v1/order',{'symbol':symbol,'side':exit_side,'type':'STOP_MARKET','stopPrice':stop,'closePosition':'false','quantity':qty,'reduceOnly':'true','workingType':'MARK_PRICE','newClientOrderId':client_id+'-SL'})
        tp_order=await self._signed('POST','/fapi/v1/order',{'symbol':symbol,'side':exit_side,'type':'TAKE_PROFIT_MARKET','stopPrice':target,'closePosition':'false','quantity':qty,'reduceOnly':'true','workingType':'MARK_PRICE','newClientOrderId':client_id+'-TP'})
        return {'stop':stop_order,'target':tp_order}
    async def cancel_order(self,symbol,order_id): return await self._signed('DELETE','/fapi/v1/order',{'symbol':symbol,'orderId':order_id})
    async def close_position(self,symbol,side,qty):
        return await self._signed('POST','/fapi/v1/order',{'symbol':symbol,'side':'SELL' if side=='LONG' else 'BUY','type':'MARKET','quantity':qty,'reduceOnly':'true','newOrderRespType':'RESULT'})
