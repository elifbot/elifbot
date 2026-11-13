class SmartExitEngine:
    """
    Partial Take-Profit (50% lock at 1:1.5 RR) and Dynamic Trailing Stop Engine.
    """
    def __init__(self, partial_tp_ratio=0.5, trailing_pct=0.015):
        self.partial_tp_ratio = partial_tp_ratio
        self.trailing_pct = trailing_pct

    def process_position_exit(self, position: dict, current_price: float) -> dict:
        entry = position['entry_price']
        side = position['side']
        
        if side == "LONG":
            profit_pct = (current_price - entry) / entry
            if profit_pct >= 0.015 and not position.get('partial_tp_done', False):
                return {"action": "PARTIAL_TP", "amount_pct": self.partial_tp_ratio, "new_stop": entry}
        return {"action": "HOLD"}
