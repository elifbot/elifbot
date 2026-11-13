import json
import os

class StateStore:
    """
    Persists active open positions, cumulative PnL, and execution metrics to disk to survive system restarts.
    """
    def __init__(self, filepath="state/trading_state.json"):
        self.filepath = filepath

    def save_state(self, state_data: dict):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w') as f:
            json.dump(state_data, f, indent=4)

    def load_state(self) -> dict:
        if os.path.exists(self.filepath):
            with open(self.filepath, 'r') as f:
                return json.load(f)
        return {"positions": [], "pnl": 0.0}
