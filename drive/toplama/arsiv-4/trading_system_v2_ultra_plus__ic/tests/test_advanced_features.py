from core.risk import RiskManager
from safety.smart_exit import SmartExitEngine
from infra.slippage import LatencySlippageSimulator
import pandas as pd
import numpy as np

def test_atr_dynamic_sizing():
    rm = RiskManager()
    df = pd.DataFrame({
        'high': np.linspace(101, 201, 50),
        'low': np.linspace(99, 199, 50),
        'close': np.linspace(100, 200, 50)
    })
    res = rm.calculate_atr_dynamic_sizing(df, 200.0, "LONG")
    assert "dynamic_margin" in res
    print("ATR Dynamic Sizing Test: PASSED")

def test_slippage_and_smart_exit():
    sim = LatencySlippageSimulator()
    slipped = sim.apply_slippage(100.0, "LONG")
    assert slipped >= 100.0
    
    exit_engine = SmartExitEngine()
    pos = {"entry_price": 100.0, "side": "LONG", "partial_tp_done": False}
    decision = exit_engine.process_position_exit(pos, 102.0)
    assert decision['action'] == "PARTIAL_TP"
    print("Slippage & Smart Exit Test: PASSED")
