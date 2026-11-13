from backtest.walkforward import WalkForwardLab
import pandas as pd

def test_walkforward_split():
    df = pd.DataFrame({'close': range(1000)})
    lab = WalkForwardLab(train_ratio=0.6)
    res = lab.run_walkforward_analysis(df)
    assert res['out_of_sample_performance'] == "VERIFIED_PASSED"
    print("WalkForward Test: PASSED")
