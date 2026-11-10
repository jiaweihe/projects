"""Discrete-event simulation clock shared by every simulated tenant and vehicle."""

from __future__ import annotations

import heapq
import itertools
import random
from typing import Callable


class SimWorld:
    def __init__(self, seed: int = 7, start: float = 0.0):
        self.now = start
        self.rng = random.Random(seed)
        self._heap: list[tuple[float, int, Callable[[], None]]] = []
        self._seq = itertools.count()

    def schedule(self, t: float, fn: Callable[[], None]) -> None:
        heapq.heappush(self._heap, (max(t, self.now), next(self._seq), fn))

    def run_until(self, t_end: float) -> None:
        while self._heap and self._heap[0][0] <= t_end:
            t, _, fn = heapq.heappop(self._heap)
            self.now = t
            fn()
        self.now = max(self.now, t_end)

    def pending(self) -> int:
        return len(self._heap)
