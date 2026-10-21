"""A toy plant that closes the loop for the demo and the tests.

It is both a signal feed (noisy readings of a level) and an actuator (commands
move the level), with scripted disturbances. Nothing in the assembly depends
on it; swap in a real feed and actuator with the same two methods.
"""
import random

from .signals import Signal


class ToyPlant:
    def __init__(self, level=50.0, noise=0.5, gain=0.8, steps=200, seed=0, script=None):
        self.level = level
        self.noise = noise
        self.drift = 0.0
        self.bias = 0.0             # sensor offset: readings move, the level does not
        self.gain = gain            # share of a commanded move that actually happens
        self.glitch = None          # one-off reading that replaces the next sample
        self.steps = steps
        self.rng = random.Random(seed)
        # {step: {attribute: value}}; the key 'shift' adds to the level instead
        self.script = script or {}

    def __iter__(self):
        for step in range(self.steps):
            for name, value in self.script.get(step, {}).items():
                if name == 'shift':
                    self.level += value
                else:
                    setattr(self, name, value)
            self.level += self.drift
            value = self.level + self.bias + self.rng.gauss(0.0, self.noise)
            if self.glitch is not None:
                value, self.glitch = self.glitch, None
            yield Signal('toy-plant', step, value, {'true_level': round(self.level, 4)})

    def apply(self, command):
        self.level += command.delta * self.gain
