"""Latch unexpected wall/monotonic discontinuities for the paper profile.

This is an in-process safety check, not a trusted external clock or a guarantee
that a whole-VM freeze is observable. Restart + reinitialization is required.
"""
from __future__ import annotations
import math
import time


class ClockDiscontinuityGuard:
    def __init__(self, tolerance_s: float = 2.0, *, wall=None, mono=None):
        self.tolerance_s = float(tolerance_s)
        if not math.isfinite(self.tolerance_s) or self.tolerance_s <= 0:
            raise ValueError('clock jump tolerance must be positive')
        self.wall = float(time.time() if wall is None else wall)
        self.mono = float(time.monotonic() if mono is None else mono)
        self.tripped = False
        self.delta_s = None
        self.reason = None

    def check(self, *, wall=None, mono=None):
        if self.tripped:
            return False
        w = float(time.time() if wall is None else wall)
        m = float(time.monotonic() if mono is None else mono)
        if not all(math.isfinite(x) for x in (w,m,self.wall,self.mono)) or m < self.mono:
            self.tripped = True; self.reason = 'invalid_clock_reading'
            return False
        difference = (w - self.wall) - (m - self.mono)
        if abs(difference) > self.tolerance_s:
            self.tripped = True; self.delta_s = difference; self.reason = 'wall_monotonic_discontinuity'
            return False
        self.wall, self.mono = w, m
        return True

    def status(self):
        return {'enabled': True, 'tripped': self.tripped, 'reason': self.reason,
                'delta_s': self.delta_s, 'tolerance_s': self.tolerance_s,
                'reset': 'restart_and_full_reinitialization'}
