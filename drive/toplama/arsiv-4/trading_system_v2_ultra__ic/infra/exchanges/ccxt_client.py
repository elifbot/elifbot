import ccxt

class CCXTClient:
    def __init__(self, exchange_name='binance', api_key='', secret=''):
        exchange_class = getattr(ccxt, exchange_name)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
