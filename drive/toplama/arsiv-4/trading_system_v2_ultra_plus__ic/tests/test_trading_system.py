from core.risk import RiskManager

def test_risk_manager():
    rm = RiskManager(initial_balance=1000, base_margin=50, leverage=10, base_risk=25)
    assert rm.can_open_position(0) is True
    print("Trading System Risk Test: PASSED")
