# safety/news_guard.py
import xml.etree.ElementTree as ET
import urllib.request

class NewsGuard:
    def __init__(self, config):
        self.config = config
        self.rss_urls = [
            "https://cointelegraph.com/rss",
            "https://cryptoslate.com/feed/",
            "https://www.coindesk.com/arc/outboundfeeds/rss/"
        ]
        self.bullish_words = {"bullish": 1.5, "launch": 1.0, "approve": 2.0, "surge": 1.2, "breakout": 1.5}
        self.bearish_words = {"bearish": 1.5, "hack": 2.5, "scam": 2.5, "ban": 2.0, "reject": 1.8, "crash": 2.0}
        self.processed_titles = set()

    def get_market_sentiment(self) -> str:
        """
        Haber akışını tarar ve ikincil destekleyici filtre olarak duyarlılık döndürür.
        """
        if not self.config.get("enabled", True):
            return "NEUTRAL"
            
        total_score = 0.0
        news_count = 0

        for url in self.rss_urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    root = ET.fromstring(response.read())
                    for item in root.findall('.//item'):
                        title = item.find('title').text.lower() if item.find('title') is not None else ""
                        if title in self.processed_titles: continue
                        self.processed_titles.add(title)
                        
                        item_score = 0.0
                        for word, weight in self.bullish_words.items():
                            if word in title: item_score += weight
                        for word, weight in self.bearish_words.items():
                            if word in title: item_score -= weight
                        total_score += item_score
                        news_count += 1
                        if news_count % 3 == 0: break
            except:
                continue

        if news_count == 0: return "NEUTRAL"
        final_score = total_score / news_count
        
        if final_score >= self.config.get("sentiment_long_threshold", 0.3): return "BULLISH_SUPPORT"
        elif final_score <= self.config.get("sentiment_short_threshold", -0.3): return "BEARISH_SUPPORT"
        return "NEUTRAL"
