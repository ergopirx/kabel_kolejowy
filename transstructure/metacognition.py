"""Metacognition: the assembly watching its own processing.

The processor answers "what should be done?". This layer answers "should the
processor be trusted right now?". It does not judge the action itself, only
whether the conditions the processor relies on still hold:

- warm-up: too few readings for the noise estimate to mean anything
- validity: non-finite readings, and readings the processor set aside
- shift: the processor re-anchored its level on a sudden jump; a person
  confirms what happened before the assembly acts on it
- noise regime: the spread has left the level calibrated during warm-up, or
  the processor is setting aside too many readings, so its confidence figures
  no longer describe reality
- reversal: the proposal keeps switching between raise and lower, which means
  its own corrections are being undone, usually by overcorrection
- confidence: the proposal is less sure than the autonomy threshold. That
  threshold rises when human reviewers disagree with the assembly. Doubt about
  holding is harmless, since holding is what abstaining does anyway; doubt
  about a move that lasts past `patience` steps goes to a person
"""
import math
from collections import deque
from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    PROCEED = 'proceed'    # act on its own
    ABSTAIN = 'abstain'    # do nothing this step; not worth a person's attention
    ESCALATE = 'escalate'  # a person decides


@dataclass(frozen=True)
class Reflection:
    verdict: Verdict
    reasons: tuple[str, ...]
    threshold: float       # the confidence bar in force for this step


class Calibration:
    """How well the assembly's confidence matches what human reviewers decide.

    Each review records the confidence the assembly had and whether the person
    agreed. Overconfidence is shrunk toward zero by `prior` pseudo-reviews of
    perfect calibration, so a sustained pattern counts for more than one verdict.
    """

    def __init__(self, window=50, prior=5):
        self.reviews = deque(maxlen=window)
        self.prior = prior

    def record(self, confidence, agreed):
        self.reviews.append((confidence, 1.0 if agreed else 0.0))

    def overconfidence(self):
        return sum(c - a for c, a in self.reviews) / (len(self.reviews) + self.prior)

    def brier(self):
        if not self.reviews:
            return math.nan
        return sum((c - a) ** 2 for c, a in self.reviews) / len(self.reviews)


class Monitor:
    def __init__(self, warmup=20, min_confidence=0.9, noise_limit=3.0, patience=5,
                 window=10, max_outliers=3, max_reversals=2, calibration=None):
        if warmup < 1:
            raise ValueError('warmup must be at least one reading')
        self.warmup = warmup
        self.min_confidence = min_confidence
        self.noise_limit = noise_limit
        self.patience = patience
        self.max_outliers = max_outliers
        self.max_reversals = max_reversals
        self.calibration = calibration if calibration is not None else Calibration()
        self.reference_spread = None
        self.warmup_spreads = []
        self.recent = deque(maxlen=window)          # (action, outlier) per step
        self.unsure_run = 0

    @property
    def threshold(self):
        # it may grow more cautious than its configured floor on its own, never less
        return min(0.999, self.min_confidence + max(0.0, self.calibration.overconfidence()))

    def __call__(self, est):
        threshold = self.threshold
        if not math.isfinite(est.signal.value):
            return Reflection(Verdict.ABSTAIN, ('non-finite reading',), threshold)
        if est.n <= self.warmup:
            # the EWMA spread starts biased low; average its later half as the reference
            if est.n > self.warmup // 2:
                self.warmup_spreads.append(est.spread)
            if est.n == self.warmup:
                self.reference_spread = max(sum(self.warmup_spreads) / len(self.warmup_spreads), 1e-12)
            return Reflection(Verdict.ABSTAIN, (f'warming up ({est.n}/{self.warmup})',), threshold)

        escalate, abstain = [], []
        if est.outlier == 'shift':
            escalate.append(f'level jumped to {est.level:.2f}; confirm before acting on it')
        elif est.outlier == 'glitch':
            abstain.append(f'reading {est.z:+.1f} spreads off the level, set aside')
        p = est.proposal
        self.recent.append((p.action, est.outlier))
        ratio = est.spread / self.reference_spread
        if ratio > self.noise_limit:
            escalate.append(f'noise at {ratio:.1f}x the calibrated level; '
                            f'confidence figures assume calibrated noise')
        # set-aside readings never reach the spread, so count them separately
        outliers = sum(o == 'glitch' for _, o in self.recent)
        if outliers >= self.max_outliers:
            escalate.append(f'{outliers} of the last {len(self.recent)} readings set aside; '
                            f'the noise model no longer fits')

        moves = [a for a, _ in self.recent if a != 'hold']
        reversals = sum(a != b for a, b in zip(moves, moves[1:]))
        if reversals >= self.max_reversals:
            escalate.append(f'reversed direction {reversals} times in {len(self.recent)} steps')

        unsure = p.confidence < threshold
        self.unsure_run = self.unsure_run + 1 if unsure and p.action != 'hold' else 0
        if self.unsure_run > self.patience:
            escalate.append(f'confidence below {threshold:.3f} on {p.action} '
                            f'for {self.unsure_run} steps')
        elif unsure:
            abstain.append(f'confidence {p.confidence:.3f} below {threshold:.3f}')

        verdict = Verdict.ESCALATE if escalate else Verdict.ABSTAIN if abstain else Verdict.PROCEED
        return Reflection(verdict, tuple(escalate + abstain), threshold)
