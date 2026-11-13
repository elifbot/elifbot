import time

class PaperBroker:
    """
    Simulates orderbook liquidity, Maker/Taker logic, partial fills, and Time-To-Live (TTL).
    """
    def __init__(self, initial_balance=1000.0):
        self.balance = initial_balance
        self.open_orders = []
        self.positions = []

    def place_maker_order(self, symbol: str, side: str, amount: float, price: float, ttl_seconds: int = 60):
        order = {
            "id": f"ORD_{int(time.time() * 1000)}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "filled": 0.0,
            "status": "OPEN",
            "timestamp": time.time(),
            "ttl": ttl_seconds
        }
        self.open_orders.append(order)
        return order

    def update_orderbook_feed(self, symbol: str, current_bid: float, current_ask: float):
        # Simulate execution for limit orders
        for order in self.open_orders:
            if order['status'] == 'OPEN' and order['symbol'] == symbol:
                if order['side'] == 'LONG' and current_ask <= order['price']:
                    order['filled'] = order['amount']
                    order['status'] = 'FILLED'
                elif order['side'] == 'SHORT' and current_bid >= order['price']:
                    order['filled'] = order['amount']
                    order['status'] = 'FILLED'
