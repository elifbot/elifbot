from safety.security import SecurityGuard

def test_security_check():
    safe_info = {"can_withdraw": False}
    assert SecurityGuard.verify_api_safety(safe_info) is True
    print("Regression Security Test: PASSED")
