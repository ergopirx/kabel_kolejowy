"""Synchronisation: keeping the assembly's autonomy in step with its people.

The assembly has no values of its own. What it has is:

- a Charter of principles people wrote down, each with its reason in plain
  language. A principle can block an action outright or require a person's
  consent. The assembly never amends the charter; a named person does, and the
  amendment is recorded.
- an Overseer: whoever answers when the assembly asks. Silence, errors and
  unavailability all count as "no".
- the Calibration record, which every human verdict feeds, so the confidence
  the assembly needs before acting alone tracks how often people agree with it.
"""
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence

from .actuation import Command
from .metacognition import Calibration, Reflection, Verdict
from .processing import Estimate, Proposal


class Severity(Enum):
    CONSENT = 'consent'    # a person must approve
    BLOCK = 'block'        # never, whatever anyone approves case by case


@dataclass(frozen=True)
class Context:
    step: int
    history: Sequence[Command]     # commands actuated so far


@dataclass(frozen=True)
class Principle:
    name: str
    rationale: str
    check: Callable[[Proposal, Context], Optional[tuple[Severity, str]]]


@dataclass(frozen=True)
class Finding:
    principle: str
    severity: Severity
    detail: str


def bounded_step(limit):
    def check(p, ctx):
        if p.magnitude > limit:
            return Severity.BLOCK, f'move of {p.magnitude:.2f} exceeds the {limit:.2f} limit'
    return Principle('bounded-step',
                     'Changes stay small enough for a person to notice and undo.', check)


def consent_above(limit):
    def check(p, ctx):
        if p.magnitude > limit:
            return Severity.CONSENT, f'move of {p.magnitude:.2f} is above {limit:.2f}'
    return Principle('consent-above',
                     "Large interventions are a person's call, not the assembly's.", check)


def restraint(max_commands, window):
    def check(p, ctx):
        recent = [c for c in ctx.history if c.step > ctx.step - window]
        if len(recent) >= max_commands:
            return Severity.CONSENT, f'{len(recent)} commands in the last {window} steps'
    return Principle('restraint',
                     'Repeated corrections suggest the model is wrong, not the world; '
                     'stop and let a person look.', check)


class Charter:
    def __init__(self, principles=(), *, author):
        self.principles = {}
        self.amendments = []
        for p in principles:
            self.amend(p, by=author)

    def amend(self, principle, *, by, note=''):
        if not by:
            raise ValueError('a charter amendment needs a named person')
        self.principles[principle.name] = principle
        self.amendments.append(('adopt', principle.name, by, note))

    def repeal(self, name, *, by, note=''):
        if not by:
            raise ValueError('a charter amendment needs a named person')
        del self.principles[name]
        self.amendments.append(('repeal', name, by, note))

    def review(self, proposal, ctx):
        if proposal.action == 'hold':
            return []
        findings = []
        for p in self.principles.values():
            hit = p.check(proposal, ctx)
            if hit:
                findings.append(Finding(p.name, *hit))
        return findings


@dataclass(frozen=True)
class Case:
    step: int
    estimate: Estimate
    reflection: Reflection
    findings: tuple[Finding, ...]
    why: tuple[str, ...]           # 'escalated', 'consent required', 'spot check'


@dataclass(frozen=True)
class Review:
    approved: bool
    by: str
    note: str = ''


class Overseer(Protocol):
    def review(self, case: Case) -> Optional[Review]:
        """Approve or refuse an action. None means no answer, which counts as no."""

    def notify(self, case: Case) -> None:
        """Hear about something that needs no approval: the assembly is stuck."""


class PolicyOverseer:
    """A stand-in reviewer driven by a function, for demos and tests."""

    def __init__(self, name, policy):
        self.name, self.policy = name, policy
        self.notices = []

    def review(self, case):
        approved, note = self.policy(case)
        return Review(approved, self.name, note)

    def notify(self, case):
        self.notices.append(case)


def describe(case):
    p, est = case.estimate.proposal, case.estimate
    lines = [f'step {case.step}: {", ".join(case.why)}',
             f'  reading {est.signal.value:.2f}, level {est.level:.2f}, spread {est.spread:.2f}',
             f'  proposal: {p.action} {p.magnitude:.2f} (confidence {p.confidence:.3f}) - {p.rationale}']
    lines += [f'  monitor: {r}' for r in case.reflection.reasons]
    lines += [f'  charter: {f.principle} - {f.detail}' for f in case.findings]
    return '\n'.join(lines)


class ConsoleOverseer:
    """Ask the person at the terminal."""

    def __init__(self, name, ask=input, out=print):
        self.name, self.ask, self.out = name, ask, out

    def review(self, case):
        self.out(describe(case))
        answer = self.ask('  approve? [y/N] ').strip().lower()
        return Review(answer in ('y', 'yes'), self.name)

    def notify(self, case):
        self.out(describe(case))


@dataclass(frozen=True)
class Decision:
    # 'hold', 'abstain', 'blocked', 'withheld', 'autonomous', 'approved', 'denied', 'unanswered'
    route: str
    cleared: bool        # a command may be actuated
    by: str              # 'assembly', 'charter', or the reviewer
    notes: tuple[str, ...] = ()


class Gate:
    """Decide whether a proposal reaches the actuator, and on whose authority.

    People are asked to approve actions, never inaction: holding needs no one's
    consent, and anything doubtful falls back to it. A denial stands for
    `respect` steps: the same action is withheld without asking again, so the
    assembly neither goes around a person's "no" nor wears them down with the
    same question. When the assembly is stuck (blocked by the
    charter, or escalating with nothing to approve) people are told once per
    episode rather than on every step it stays stuck.
    """

    def __init__(self, charter, overseer, calibration: Calibration, spot_check=0.1,
                 respect=10, seed=0):
        self.charter = charter
        self.overseer = overseer
        self.calibration = calibration
        self.spot_check = spot_check
        self.respect = respect
        self.denied = {}            # action -> (step, reviewer) of the last denial
        self.last_notice = None     # step of the last stuck step
        self.rng = random.Random(seed)

    def decide(self, est, reflection, history):
        proposal = est.proposal
        step = est.signal.step
        if proposal.action == 'hold':
            notes = ()
            if reflection.verdict is Verdict.ESCALATE:
                notes = self.notice(Case(step, est, reflection, (), ('escalated, nothing to approve',)))
            proceed = reflection.verdict is Verdict.PROCEED
            return Decision('hold' if proceed else 'abstain', False, 'assembly', notes)
        findings = self.charter.review(proposal, Context(step, tuple(history)))
        blocks = [f for f in findings if f.severity is Severity.BLOCK]
        if blocks:
            # no one approves past a principle case by case; they amend the charter
            notes = tuple(f'{f.principle}: {f.detail}' for f in blocks)
            notes += self.notice(Case(step, est, reflection, tuple(blocks), ('blocked by the charter',)))
            return Decision('blocked', False, 'charter', notes)
        if reflection.verdict is Verdict.ABSTAIN:
            return Decision('abstain', False, 'assembly')
        if proposal.action in self.denied:
            when, by = self.denied[proposal.action]
            if step - when <= self.respect:
                return Decision('withheld', False, by,
                                (f'{proposal.action} refused by {by} at step {when}',))

        why = []
        if reflection.verdict is Verdict.ESCALATE:
            why.append('escalated')
        if findings:
            why.append('consent required')
        if not why:
            if self.rng.random() >= self.spot_check:
                return Decision('autonomous', True, 'assembly')
            # a sample of what it does alone goes to a person, so calibration
            # sees confident cases too, not only the doubtful ones
            why.append('spot check')

        review, failure = self.ask(Case(step, est, reflection, tuple(findings), tuple(why)))
        if review is None:
            # fail closed, but silence is not disagreement: nothing to learn from it,
            # and the next step asks again
            return Decision('unanswered', False, 'overseer', tuple(why) + (failure,))
        self.calibration.record(proposal.confidence, review.approved)
        if not review.approved:
            self.denied[proposal.action] = (step, review.by)
        notes = tuple(why) + ((review.note,) if review.note else ())
        return Decision('approved' if review.approved else 'denied',
                        review.approved, review.by, notes)

    def ask(self, case):
        """The overseer's review, or None and why there is no usable answer."""
        try:
            review = self.overseer.review(case)
        except Exception as e:
            return None, f'overseer failed: {e!r}'
        if review is None:
            return None, 'no answer'
        return review, ''

    def notice(self, case):
        # consecutive stuck steps are one episode, announced on its first step
        first = self.last_notice != case.step - 1
        self.last_notice = case.step
        if not first:
            return ()
        try:
            self.overseer.notify(case)
        except Exception as e:     # the trace still records it; don't stop the loop
            return (f'notice failed: {e!r}',)
        return ('people notified',)
