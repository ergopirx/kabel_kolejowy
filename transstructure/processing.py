"""Signal processing: turn raw readings into a proposed action.

The processor reports how sure it is under its own noise model. Whether that
model still describes the world is the metacognition layer's question, not this
one's, so nothing here second-guesses itself.
"""
import math
from dataclasses import dataclass
from typing import Optional

from .signals import Signal


@dataclass(frozen=True)
class Proposal:
    action: str        # 'hold', 'raise' or 'lower'
    magnitude: float   # size of the move, in signal units
    confidence: float  # P(action is right) under the processor's noise model
    rationale: str


@dataclass(frozen=True)
class Estimate:
    signal: Signal
    n: int                  # finite readings seen so far
    level: float            # smoothed level (nan before the first finite reading)
    spread: float           # RMS residual of readings against the level
    z: float                # this reading's residual in spreads (nan when undefined)
    outlier: Optional[str]  # None, 'glitch' (set aside) or 'shift' (level re-anchored)
    proposal: Proposal


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class BandController:
    """Keep a signal inside target ± band.

    The level is an exponentially weighted mean (`alpha`), the spread a slower
    exponentially weighted RMS of residuals (`beta`). Once settled, a reading
    beyond `clip_z` spreads is set aside as a glitch; `shift_after` of them in a
    row on the same side means the level really moved, so it is re-anchored.

    Confidence is the probability, under Gaussian noise, that the smoothed level
    really is on the side of the band edge it appears to be: a level sitting on
    the edge is a coin flip (0.5), not a certainty.
    """

    def __init__(self, target, band, alpha=0.2, beta=0.1, clip_z=4.0, settle=10, shift_after=3):
        self.target, self.band = target, band
        self.alpha, self.beta = alpha, beta
        self.clip_z, self.settle, self.shift_after = clip_z, settle, shift_after
        self.n = 0
        self.level = math.nan
        self.var = 0.0
        self.updates = 0                    # readings that reached the variance
        self.run, self.run_up = [], False   # consecutive outliers on one side

    @property
    def spread(self):
        if not self.updates:
            return 0.0
        # the EW mean of squares starts at zero; divide out that start-up bias
        return math.sqrt(self.var / (1 - (1 - self.beta) ** self.updates))

    def __call__(self, signal):
        x = signal.value
        if not math.isfinite(x):
            # leave the state alone; the monitor decides what a bad reading means
            return Estimate(signal, self.n, self.level, self.spread, math.nan, None,
                            Proposal('hold', 0.0, 0.0, 'no finite reading'))
        z, outlier = math.nan, None
        if self.n == 0:
            self.level = x
        else:
            r = x - self.level
            if self.spread > 0:
                z = r / self.spread
            if self.n >= self.settle and abs(z) > self.clip_z:
                if not self.run or (r > 0) != self.run_up:
                    self.run, self.run_up = [], r > 0
                self.run.append(x)
                outlier = 'glitch'
                if len(self.run) >= self.shift_after:
                    # a run of outliers on one side is the level moving, not noise
                    self.level = sum(self.run) / len(self.run)
                    self.run = []
                    outlier = 'shift'
            else:
                self.run = []
                self.level += self.alpha * r
                self.var = (1 - self.beta) * self.var + self.beta * r * r
                self.updates += 1
        self.n += 1
        return Estimate(signal, self.n, self.level, self.spread, z, outlier, self.propose())

    def propose(self):
        lo, hi = self.target - self.band, self.target + self.band
        # standard error of the level: an EWMA of white noise has variance
        # alpha/(2-alpha) sigma^2, and the residual mean square is sigma^2 * 2/(2-alpha)
        se = max(self.spread * math.sqrt(self.alpha / 2), 1e-12)
        if self.level < lo:
            return Proposal('raise', self.target - self.level,
                            normal_cdf((lo - self.level) / se),
                            f'level {self.level:.2f} below band floor {lo:.2f}')
        if self.level > hi:
            return Proposal('lower', self.level - self.target,
                            normal_cdf((self.level - hi) / se),
                            f'level {self.level:.2f} above band ceiling {hi:.2f}')
        inside = normal_cdf((hi - self.level) / se) + normal_cdf((self.level - lo) / se) - 1
        return Proposal('hold', 0.0, inside, f'level {self.level:.2f} inside band')

    def on_command(self, delta):
        """Predict step: assume a commanded move happened; residuals correct the rest."""
        self.level += delta
