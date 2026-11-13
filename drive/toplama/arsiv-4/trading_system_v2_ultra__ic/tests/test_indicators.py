from core.indicators import TechnicalIndicators
import pandas as pd
import numpy as np

def test_ema_and_rsi():
    data = {'close': np.linspace(100, 200, 100)}
    df = pd.DataFrame(data)
    ema = TechnicalIndicators.calculate_ema(df, 20)
    rsi = TechnicalIndicators.calculate_rsi(df, 14)
    assert len(ema) == 100
    assert len(rsi) == 100
    print("Indicators Test: PASSED")
