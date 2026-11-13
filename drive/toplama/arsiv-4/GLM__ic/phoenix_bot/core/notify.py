"""İsteğe bağlı Telegram bildirimi — .env'e token girilmezse sessizce devre dışı."""
import logging
import os
import requests

log = logging.getLogger('bot')


class Notifier:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        self.chat = os.getenv('TELEGRAM_CHAT_ID', '').strip()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat)

    def send(self, text: str):
        if not self.enabled:
            return
        try:
            requests.post(
                f'https://api.telegram.org/bot{self.token}/sendMessage',
                json={'chat_id': self.chat, 'text': text}, timeout=10)
        except Exception as e:
            log.debug(f'telegram gönderilemedi: {e}')
