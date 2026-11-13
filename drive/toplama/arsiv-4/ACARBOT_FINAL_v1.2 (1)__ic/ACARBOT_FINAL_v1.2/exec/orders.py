from typing import Dict, Any

class OrderExecutor:
    def __init__(self, exchange_client):
        self.client = exchange_client
        self.sent_orders = set()

    def execute_live_order(self, symbol: str, side: str, amount: float, client_order_id: str) -> Dict[str, Any]:
        """Mükerrer gönderimi engellemek için clientOrderId kontrolü ve canlı emir iletimi."""
        if client_order_id in self.sent_orders:
            print(f"[Uyarı] Mükerrer emir engellendi: {client_order_id}")
            return {"status": "rejected", "reason": "duplicate"}
            
        self.sent_orders.add(client_order_id)
        order = self.client.create_order(symbol, "market", side, amount, params={"clientOrderId": client_order_id})
        return order

    def place_reduce_only_stop(self, symbol: str, stop_price: float, amount: float) -> Dict[str, Any]:
        """Bot çökmelerine karşı borsada kalan koruyucu reduce-only stop emri."""
        return self.client.create_order(
            symbol=symbol,
            type="stop",
            side="sell",
            amount=amount,
            price=stop_price,
            params={"reduceOnly": True, "stopPrice": stop_price}
        )

    def reconcile_positions(self, local_store) -> None:
        """Başlangıç mutabakatı: Borsa verileriyle yerel durumu eşitler."""
        exchange_positions = self.client.fetch_positions()
        for pos in exchange_positions:
            local_store.update_position(pos["symbol"], pos["size"])
