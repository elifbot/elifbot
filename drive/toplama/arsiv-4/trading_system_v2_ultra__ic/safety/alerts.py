class AlertManager:
    """
    Telegram / Webhook emergency and execution alerting system.
    """
    def send_notification(self, message: str):
        print(f"[ALERT NOTIFICATION]: {message}")

    def send_emergency_stop(self, reason: str):
        print(f"[EMERGENCY ALERT HALT]: {reason}")
