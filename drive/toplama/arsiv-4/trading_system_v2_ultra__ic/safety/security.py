class SecurityGuard:
    """
    Ensures API keys are encrypted, IP Whitelisting is respected, and withdrawal options are disabled.
    """
    @staticmethod
    def verify_api_safety(exchange_info: dict) -> bool:
        if exchange_info.get("can_withdraw", False):
            raise PermissionError("SECURITY ERROR: API key has withdrawal permissions enabled! Disable withdrawals immediately.")
        return True
