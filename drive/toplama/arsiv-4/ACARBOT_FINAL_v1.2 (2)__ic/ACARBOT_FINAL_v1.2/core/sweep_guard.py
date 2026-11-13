import time

class SweepGuard:
    def __init__(self, max_entries_per_minute=5):
        self.max_entries_per_minute = max_entries_per_minute
        self.entry_timestamps = []

    def filter_signals(self, signals):
        # Sort signals by score descending
        sorted_signals = sorted(signals, key=lambda x: x.get('score', 0), reverse=True)
        current_time = time.time()
        # Clean old timestamps
        self.entry_timestamps = [t for t in self.entry_timestamps if current_time - t < 60]
        
        allowed_signals = []
        for sig in sorted_signals:
            if len(self.entry_timestamps) < self.max_entries_per_minute:
                allowed_signals.append(sig)
                self.entry_timestamps.append(current_time)
            else:
                break
        return allowed_signals
