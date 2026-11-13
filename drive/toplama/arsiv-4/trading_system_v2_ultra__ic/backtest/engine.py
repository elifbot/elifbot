import pandas as pd

class BacktestEngine:
    def __init__(self, initial_capital=1000.0):
        self.capital = initial_capital
        self.trades = []

    def run(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame, df_4h: pd.DataFrame):
        return {"total_trades": 0, "win_rate": 0.0, "net_pnl": 0.0}
