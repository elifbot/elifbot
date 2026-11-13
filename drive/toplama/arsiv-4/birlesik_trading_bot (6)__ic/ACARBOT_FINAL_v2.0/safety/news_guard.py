# -*- coding: utf-8 -*-
import urllib.request
import xml.etree.ElementTree as ET
import re
import time

class NewsGuard:
    def __init__(self, config):
        self.config = config
        self.rss_urls = [
            "https://cointelegraph.com/rss",
            "https://cryptoslate.com/feed/"
        ]
        self.bullish_words = ["bullish", "launch", "partnership", "adopt", "approve", "surge", "breakout"]
        self.bearish_words = ["bearish", "hack", "scam", "ban", "reject", "drop", "crash", "lawsuit"]
        self.cached_sentiment = "NEUTRAL"
        self.last_scan_time = 0
        self.scan_interval = 300  # 5 dakika önbellek

    def fetch_latest_news_sentiment(self) -> str:
        current_time = time.time()
        if current_time - self.last_scan_time < self.scan_interval:
            return self.cached_sentiment

        total_score = 0
        news_count = 0

        for url in self.rss_urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    root = ET.fromstring(response.read())
                    for item in root.findall('.//item'):
                        title = item.find('title').text.lower() if item.find('title') is not None else ""
                        desc = item.find('description').text.lower() if item.find('description') is not None else ""
                        full_text = f"{title} {desc}"

                        item_score = 0
                        # Tam kelime sınırları () ile "ban" -> "bank" eşleşme bug'ı fixlendi
                        for word in self.bullish_words:
                            if re.search(r'\b' + word + r'\b', full_text):
                                item_score += 1.0
                        for word in self.bearish_words:
                            if re.search(r'\b' + word + r'\b', full_text):
                                item_score -= 1.0

                        total_score += item_score
                        news_count += 1
                        if news_count >= 10: break
            except:
                continue

        self.last_scan_time = current_time
        if news_count == 0:
            self.cached_sentiment = "NEUTRAL"
        else:
            avg = total_score / news_count
            if avg >= 0.2: self.cached_sentiment = "LONG"
            elif avg <= -0.2: self.cached_sentiment = "SHORT"
            else: self.cached_sentiment = "NEUTRAL"

        return self.cached_sentiment
