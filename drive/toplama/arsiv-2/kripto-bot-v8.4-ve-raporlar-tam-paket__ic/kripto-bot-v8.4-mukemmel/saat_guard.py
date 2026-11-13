"""NTP sıçraması / VM duraklaması / sistem saati kayması koruyucusu (ClockDiscontinuityGuard)."""
from __future__ import annotations

import math
import time


class ClockDiscontinuityGuard:
    """Duvar saati (time.time) ile monotonik saat (time.monotonic) farkını izler.

    Sanal makine askıya alma (suspend/resume) veya sert NTP düzeltmelerinde
    duvar saati ileri/geri sıçrayabilir. Böyle bir süreksizlik tespit edildiğinde
    ``check()`` ``False`` döndürür (fail-closed).
    """

    def __init__(self, max_drift_sec: float = 5.0):
        self.max_drift_sec = float(max_drift_sec)
        self._base_wall = time.time()
        self._base_mono = time.monotonic()
        self._last_wall = self._base_wall
        self._last_mono = self._base_mono
        self._samples = 0
        self._max_observed_drift_sec = 0.0
        self._ok = True
        self._reason: str | None = None

    def check(self) -> bool:
        """Yeni bir saat çifti okur; süreksizlik varsa kalıcı olarak False döndürür."""
        wall = time.time()
        mono = time.monotonic()
        self._samples += 1

        if not (math.isfinite(wall) and math.isfinite(mono)):
            self._ok = False
            self._reason = "non_finite_clock"
            return False

        d_wall = wall - self._last_wall
        d_mono = mono - self._last_mono
        step_drift = abs(d_wall - d_mono)
        total_drift = abs((wall - self._base_wall) - (mono - self._base_mono))
        observed = max(step_drift, total_drift)
        if observed > self._max_observed_drift_sec:
            self._max_observed_drift_sec = observed

        if d_mono < 0:
            self._ok = False
            self._reason = "monotonic_backstep"
        elif step_drift > self.max_drift_sec or total_drift > self.max_drift_sec * 2.0:
            self._ok = False
            self._reason = f"clock_discontinuity:{observed:.4f}s"

        self._last_wall = wall
        self._last_mono = mono
        return self._ok

    def status(self) -> dict:
        return {
            "ok": self._ok,
            "samples": self._samples,
            "max_drift_sec": round(self._max_observed_drift_sec, 6),
            "threshold_sec": self.max_drift_sec,
            "reason": self._reason,
        }
