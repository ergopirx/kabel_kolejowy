"""Actuation: the only place the assembly changes anything outside itself."""
from dataclasses import dataclass
from typing import Protocol

DIRECTION = {'raise': 1.0, 'lower': -1.0, 'hold': 0.0}


@dataclass(frozen=True)
class Command:
    step: int
    action: str
    magnitude: float
    authorised_by: str     # 'assembly', or the person who approved it

    @property
    def delta(self):
        return DIRECTION[self.action] * self.magnitude


class Actuator(Protocol):
    def apply(self, command: Command) -> None: ...


class RecordingActuator:
    """Dry run: records commands instead of driving anything."""

    def __init__(self):
        self.commands = []

    def apply(self, command):
        self.commands.append(command)
