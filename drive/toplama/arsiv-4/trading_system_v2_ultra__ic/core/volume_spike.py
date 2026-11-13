import pandas as pd

class VolumeSpikeDetector:
    """
    Identifies abnormal volume bursts relative to SMA 20 volume.
    """
    @staticmethod
    def is_volume_burst(df: pd.DataFrame, multiplier: float = 2.5) -> bool:
        avg_vol = df['volume'].rolling(20).mean().iloc[-1]
        current_vol = df['volume'].iloc[-1]
        return current_vol >= (avg_vol * multiplier)
