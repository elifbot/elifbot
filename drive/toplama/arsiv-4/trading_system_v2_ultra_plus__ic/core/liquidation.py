class LiquidationClusterDetector:
    """
    Detects liquidation walls and open interest spikes to avoid stop-hunt sweeps by market makers.
    """
    def __init__(self, threshold_usd=500000):
        self.threshold = threshold_usd

    def is_stop_hunt_imminent(self, orderbook_depth: dict) -> bool:
        # Evaluates bid/ask imbalance near major round levels
        bids_near_key = orderbook_depth.get('bid_volume_cluster', 0)
        asks_near_key = orderbook_depth.get('ask_volume_cluster', 0)
        
        if bids_near_key > self.threshold or asks_near_key > self.threshold:
            return True
        return False
