# safety/news_guard.py
import xml.etree.ElementTree as ET
import urllib.request
import time
import re

class NewsGuard:
    def __init__(self, config):
        self.config = config
        self.rss_urls = [
            "https://cointelegraph.com/rss",
            "https://cryptoslate.com/feed/"
        ]
        self.bullish_words = ["bullish", "launch", "partnership", "adopt", "approve", "surge", "breakout", "buy", "accumulate", "upgrade"]
        self.bearish_words = ["bearish", "hack", "scam", "ban", "reject", "drop", "crash", "sell", "lawsuit", "liquidated"]
        self.processed_titles = set()
        self.last_scan_time = 0
        self.cached_sentiment = "NEUTRAL"

    def fetch_latest_news_sentiment(self) -> float:
        current_time = time.time()
        if current_time - self.last_scan_time < self.config.get("scan_interval_minutes", 5) * 60 and self.last_scan_time != 0:
            return 0.0
            
        self.last_scan_time = current_time
        total_score = 0.0
        news_count = 0

        for url in self.rss_urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    xml_data = response.read()
                    root = ET.fromstring(xml_data)
                    
                    for item in root.findall('.//item'):
                        title = item.find('title').text.lower() if item.find('title') is not None else ""
                        description = item.find('description').text.lower() if item.find('description') is not None else ""
                        combined_text = f"{title} {description}"
                        
                        if title in self.processed_titles:
                            continue
                        self.processed_titles.add(title)
                        
                        item_score = 0.0
                        # Tam kelime eşleşmesi için regex sınırları (\b) kullanılıyor
                        for word in self.bullish_words:
                            if re.search(r'\b' + re.escape(word) + r'\b', combined_text):
                                item_score += 1.5
                        for word in self.bearish_words:
                            if re.search(r'\b' + re.escape(word) + r'\b', combined_text):
                                item_score -= 1.5
                                
                        total_score += item_score
                        news_count += 1
                        if news_count >= 10:
                            break
            except Exception:
                continue

        if news_count == 0:
            return 0.0
        return total_score / news_count

    def get_market_direction(self) -> str:
        sentiment = self.fetch_latest_news_sentiment()
        if sentiment >= 0.3:
            self.cached_sentiment = "LONG"
        elif sentiment <= -0.3:
            self.cached_sentiment = "SHORT"
        else:
            self.cached_sentiment = "NEUTRAL"
        return self.cached_sentiment
