import time
from typing import List, Dict, Any

class SweepGuard:
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.entry_timestamps = []

    def filter_signals(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sinyalleri skorlarına göre sıralar ve hız limitine göre ilk en iyileri seçer."""
        current_time = time.time()
        # Son 1 dakikadaki girişleri temizle
        self.entry_timestamps = [t for t in self.entry_timestamps if current_time - t < 60]
        
        available_slots = self.max_per_minute - len(self.entry_timestamps)
        if available_slots <= 0:
            return []
            
        # Skorlara göre azalan sırada sırala (En yüksek öncelikli sinyaller üstte)
        sorted_signals = sorted(signals, key=lambda x: x.get("score", 0.0), reverse=True)
        allowed_signals = sorted_signals[:available_slots]
        
        return allowed_signals

    def register_entry(self):
        self.entry_timestamps.append(time.time())
