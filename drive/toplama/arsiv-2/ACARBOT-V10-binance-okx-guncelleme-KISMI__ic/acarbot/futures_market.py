"""Binance USD-M/COIN-M ve OKX SWAP/FUTURES kamu veri adaptörleri.
Kamu REST GET haricinde ağ yazımı yoktur. Doğrulama hatası veya 451 asla
başka borsa ya da testnet verisiyle değiştirilmez.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlencode
from omnistudio.core.types import Candle

@dataclass(frozen=True)
class Instrument:
    exchange: str
    market: str
    symbol: str
    settlement: str
    contract_type: str
    contract_value: str
    status: str
    @property
    def key(self): return f'{self.exchange}:{self.market}:{self.symbol}'

MARKETS={
 'binance_usdm':('https://fapi.binance.com','/fapi/v1/exchangeInfo'),
 'binance_coinm':('https://dapi.binance.com','/dapi/v1/exchangeInfo'),
 'okx_swap':('https://www.okx.com','/api/v5/public/instruments?instType=SWAP'),
 'okx_futures':('https://www.okx.com','/api/v5/public/instruments?instType=FUTURES'),
}

def instruments(market:str,data:dict[str,Any]):
    if market.startswith('binance_'):
        if not isinstance(data.get('symbols'),list): raise ValueError('Binance exchangeInfo symbols eksik')
        return [Instrument('binance',market,r['symbol'],r.get('marginAsset',''),r.get('contractType',''),str(r.get('contractSize','')),r.get('status',''))
                for r in data['symbols'] if r.get('status')=='TRADING']
    if data.get('code')!='0' or not isinstance(data.get('data'),list): raise ValueError(f'OKX instruments hatası: {data.get("msg", "geçersiz cevap")}')
    return [Instrument('okx',market,r['instId'],r.get('settleCcy',''),r.get('ctType',''),str(r.get('ctVal','')),r.get('state',''))
            for r in data['data'] if r.get('state')=='live']

def ticker_url(market:str):
    if market=='binance_usdm':return 'https://fapi.binance.com/fapi/v1/ticker/bookTicker'
    if market=='binance_coinm':return 'https://dapi.binance.com/dapi/v1/ticker/bookTicker'
    if market=='okx_swap':return 'https://www.okx.com/api/v5/market/tickers?instType=SWAP'
    if market=='okx_futures':return 'https://www.okx.com/api/v5/market/tickers?instType=FUTURES'
    raise ValueError(market)

def tickers(market:str,data):
    if market.startswith('okx_'):
        if data.get('code')!='0' or not isinstance(data.get('data'),list):raise ValueError('OKX ticker yanıtı geçersiz')
        records=data['data']; keys=('instId','bidPx','askPx','ts')
    else:
        if not isinstance(data,list):raise ValueError('Binance ticker yanıtı geçersiz')
        records=data; keys=('symbol','bidPrice','askPrice','time')
    result={}
    for r in records:
        try:
            name=r[keys[0]];bid=float(r[keys[1]]);ask=float(r[keys[2]]);ts=int(r.get(keys[3]) or 0)
            if bid>0 and ask>=bid:result[name]={'bid':bid,'ask':ask,'ts_ms':ts}
        except (KeyError,TypeError,ValueError):continue
    return result

def candles_url(inst:Instrument):
    if inst.exchange=='okx':
        return 'https://www.okx.com/api/v5/market/candles?'+urlencode({'instId':inst.symbol,'bar':'5m','limit':260})
    base,path=('https://fapi.binance.com','/fapi/v1/klines') if inst.market=='binance_usdm' else ('https://dapi.binance.com','/dapi/v1/klines')
    return base+path+'?'+urlencode({'symbol':inst.symbol,'interval':'5m','limit':260})

def candles(inst:Instrument,data):
    if inst.exchange=='okx':
        if data.get('code')!='0' or not isinstance(data.get('data'),list):raise ValueError('OKX mum yanıtı geçersiz')
        # OKX: volCcyQuote (indeks 7), doğrulanmış kapanış (indeks 8).
        rows=data['data']; out=[Candle(inst.symbol,inst.market,int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[7]),r[8]=='1') for r in rows if len(r)>=9]
    else:
        if not isinstance(data,list):raise ValueError('Binance mum yanıtı geçersiz')
        # USD-M k[7] quote hacmi; COIN-M k[7] baz varlık miktarıdır.
        # COIN-M quote hacmi yaklaşık dönüştürülür, tahmin olarak işaretlenir.
        out=[Candle(inst.symbol,inst.market,int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[7])*(float(r[4]) if inst.market=='binance_coinm' else 1),True) for r in data if len(r)>=8]
    return sorted(out,key=lambda c:c.open_ms)
