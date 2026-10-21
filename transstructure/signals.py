"""Signal feed: the one way data enters the assembly."""
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Mapping, Protocol


@dataclass(frozen=True)
class Signal:
    source: str
    step: int
    value: float
    meta: Mapping[str, object] = field(default_factory=dict)


class SignalFeed(Protocol):
    def __iter__(self) -> Iterator[Signal]: ...


class ReplayFeed:
    """Replay recorded values, e.g. from a log or a test fixture."""

    def __init__(self, values: Iterable[float], source: str = 'replay'):
        self.values = list(values)
        self.source = source

    def __iter__(self):
        for step, value in enumerate(self.values):
            yield Signal(self.source, step, float(value))
