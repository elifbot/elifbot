import os
from .binance_public import BinancePublic
from .okx_public import OKXPublic
from .binance_trade import BinanceTrade
from .okx_trade import OKXTrade

def public_client(cfg):
    ex=cfg['market'].get('exchange','binance').lower()
    if ex=='okx': return OKXPublic(cfg['market'].get('okx_rest_base','https://www.okx.com'))
    return BinancePublic(cfg['market']['rest_base'],cfg['market']['ws_base'])

def trade_client(cfg):
    ex=cfg['market'].get('exchange','binance').lower(); c=cfg['exchange_credentials']
    if ex=='okx':
        return OKXTrade(os.getenv(c['okx_api_key_env'],''),os.getenv(c['okx_secret_env'],''),os.getenv(c['okx_passphrase_env'],''),cfg['market'].get('okx_rest_base','https://www.okx.com'),os.getenv(c['okx_demo_env'],'0')=='1')
    return BinanceTrade(os.getenv(c['binance_api_key_env'],''),os.getenv(c['binance_api_secret_env'],''),cfg['market']['rest_base'])
