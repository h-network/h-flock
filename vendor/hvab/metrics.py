"""Low-overhead attribution for existing store round trips."""

from dataclasses import dataclass
import time
from typing import Callable


@dataclass(slots=True)
class PathTiming:
    """Measured components of one destructive-pop service path."""

    pop_ns: int = 0
    forward_interval_ns: int = 0
    enqueue_ns: int = 0
    store_round_trips: int = 0
    popped_mono_ns: int | None = None
    _forward_recorded: bool = False

    def absorb(self, other: "PathTiming") -> None:
        self.pop_ns += other.pop_ns
        self.forward_interval_ns += other.forward_interval_ns
        self.enqueue_ns += other.enqueue_ns
        self.store_round_trips += other.store_round_trips

    def observe_store(self, category: str, elapsed_ns: int) -> None:
        self.store_round_trips += 1
        if category == "egress":
            self.enqueue_ns += elapsed_ns

    def observe_forwarded(self, mono_ns: int) -> None:
        # A packet is counted once even when fan-out has several handovers.
        # Later target work remains in the independently measured service
        # whole and therefore in its signed residual; summing overlapping
        # packet intervals would manufacture a negative residual.
        if self.popped_mono_ns is not None and not self._forward_recorded:
            self.forward_interval_ns += mono_ns - self.popped_mono_ns
            self._forward_recorded = True


@dataclass(slots=True)
class StoreTiming:
    table_ns: int = 0
    egress_ns: int = 0
    round_trips: int = 0
    observer: Callable[[str, int], None] | None = None

    def measure(self, category: str, call):
        started = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        try:
            return call()
        finally:
            elapsed = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) - started
            if category == "table":
                self.table_ns += elapsed
            elif category == "egress":
                self.egress_ns += elapsed
            else:
                raise ValueError(f"unknown store timing category {category!r}")
            self.round_trips += 1
            if self.observer is not None:
                self.observer(category, elapsed)

    @property
    def total_ns(self) -> int:
        return self.table_ns + self.egress_ns


def measured(timing: StoreTiming | None, category: str, call):
    return call() if timing is None else timing.measure(category, call)
