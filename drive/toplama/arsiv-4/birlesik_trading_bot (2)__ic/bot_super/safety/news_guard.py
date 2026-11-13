# safety/news_guard.py
import random

class NewsGuard:
    def __init__(self):
        pass

    def get_market_direction(self) -> str:
        # Tamamen ücretsiz RSS mantığının simüle edilmiş hali
        choices = ["LONG", "SHORT", "NEUTRAL"]
        return random.choice(choices)