from core.risk import RiskManager

def test_risk_manager():
    rm = RiskManager(initial_balance=1000, margin_per_trade=50, leverage=10, max_risk_per_trade=25)
    stop_long = rm.calculate_stop_loss(100.0, "LONG")
    stop_short = rm.calculate_stop_loss(100.0, "SHORT")
    assert stop_long == 95.0
    assert stop_short == 105.0
    print("Trading System Risk Test: PASSED")
