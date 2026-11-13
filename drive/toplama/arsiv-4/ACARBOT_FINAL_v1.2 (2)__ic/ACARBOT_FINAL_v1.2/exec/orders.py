import uuid

class OrderExecutor:
    def __init__(self, exchange_client):
        self.client = exchange_client
        self.sent_orders = set()

    def create_client_order_id(self):
        return f"acar_{uuid.uuid4().hex[:12]}"

    def place_order_with_reconciliation(self, symbol, side, qty, price=None, reduce_only=False):
        client_order_id = self.create_client_order_id()
        if client_order_id in self.sent_orders:
            return None # Duplicate check
        
        self.sent_orders.add(client_order_id)
        # In live mode, this sends to the exchange with reduce_only flag support
        order = self.client.place_order(
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            client_order_id=client_order_id,
            reduce_only=reduce_only
        )
        return order

    def initial_reconciliation(self):
        exchange_positions = self.client.get_open_positions()
        return exchange_positions
