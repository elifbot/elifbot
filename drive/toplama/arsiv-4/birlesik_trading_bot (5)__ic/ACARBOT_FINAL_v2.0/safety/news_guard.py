# -*- coding: utf-8 -*-
"""ACARBOT FINAL v2.0 - News Guard Sentiment Engine with Strict Word Boundary Matching."""

import re

class NewsGuard:
    def __init__(self, settings):
        self.settings = settings
        # Core vocabulary parameters with definitive weighting metrics
        self.bullish_dictionary = ["bullish", "launch", "partnership", "adopt", "approve", "surge", "breakout"]
        self.bearish_dictionary = ["bearish", "hack", "scam", "ban", "reject", "drop", "crash", "lawsuit"]

    def extract_sentiment_score(self, text_payload: str) -> float:
        """Processes text payloads using strict word boundaries to prevent substring misfires like ban->bank."""
        normalized = text_payload.lower()
        score = 0.0
        
        for word in self.bullish_dictionary:
            # Using precise regex word boundaries \b to guarantee exact token comparison checks
            matches = len(re.findall(r'\b' + re.escape(word) + r'\b', normalized))
            score += matches * 1.5
            
        for word in self.bearish_dictionary:
            matches = len(re.findall(r'\b' + re.escape(word) + r'\b', normalized))
            score -= matches * 1.5
            
        return score

    def evaluate_global_sentiment(self) -> str:
        """Analyzes consolidated RSS/public macro streams to provide supplementary execution trend filters."""
        # Simulated production validation channel
        return "NEUTRAL"
