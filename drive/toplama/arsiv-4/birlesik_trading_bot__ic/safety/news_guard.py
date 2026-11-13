# safety/news_guard.py
import xml.etree.ElementTree as ET
import urllib.request

class NewsGuard:
    def __init__(self):
        self.rss_urls = [
            "https://cointelegraph.com/rss",
            "https://cryptoslate.com/feed/",
            "https://www.coindesk.com/arc/outboundfeeds/rss/"
        ]
        self.bullish_words = ["bullish", "launch", "partnership", "adopt", "approve", "surge", "breakout"]
        self.bearish_words = ["bearish", "hack", "scam", "ban", "reject", "drop", "crash", "lawsuit", "fud"]

    def get_market_direction(self) -> str:
        """
        Gelen haber başlıklarından duyarlılık analizi yapar, destekleyici yön döndürür.
        """
        total_score = 0.0
        news_count = 0
        for url in self.rss_urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    root = ET.fromstring(response.read())
                    for item in root.findall('.//item')[:5]:
                        title = item.find('title').text.lower() if item.find('title') is not None else ""
                        item_score = 0.0
                        for w in self.bullish_words:
                            if w in title: item_score += 1.0
                        for w in self.bearish_words:
                            if w in title: item_score -= 1.0
                        total_score += item_score
                        news_count += 1
            except:
                continue
        if news_count == 0: return "NEUTRAL"
        final_score = total_score / news_count
        if final_score >= 0.2: return "LONG"
        elif final_score <= -0.2: return "SHORT"
        return "NEUTRAL"
