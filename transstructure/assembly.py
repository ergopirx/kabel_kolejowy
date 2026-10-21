"""The assembly: feed -> processing -> metacognition -> synchronisation -> actuation.

Every step leaves a Trace that cuts across all five layers, whether or not
anything was actuated: abstentions, blocks and denials are recorded with the
same care as actions.
"""
import json
import math
from dataclasses import dataclass
from typing import Optional

from .actuation import Command
from .metacognition import Calibration, Monitor, Reflection
from .processing import BandController, Estimate
from .synchronisation import Charter, Decision, Gate, bounded_step, consent_above, restraint


@dataclass(frozen=True)
class Trace:
    step: int
    estimate: Estimate
    reflection: Reflection
    decision: Decision
    command: Optional[Command]

    def to_dict(self):
        est, p = self.estimate, self.estimate.proposal

        def num(x):
            return round(x, 4) if math.isfinite(x) else None

        return {
            'step': self.step,
            'reading': num(est.signal.value),
            'meta': dict(est.signal.meta),
            'level': num(est.level),
            'spread': num(est.spread),
            'proposal': {'action': p.action, 'magnitude': num(p.magnitude),
                         'confidence': num(p.confidence), 'rationale': p.rationale},
            'verdict': self.reflection.verdict.value,
            'reasons': list(self.reflection.reasons),
            'threshold': num(self.reflection.threshold),
            'route': self.decision.route,
            'by': self.decision.by,
            'notes': list(self.decision.notes),
            'command': None if self.command is None else {
                'action': self.command.action, 'magnitude': num(self.command.magnitude),
                'authorised_by': self.command.authorised_by},
        }


class Assembly:
    def __init__(self, processor, monitor, gate, actuator, audit=None):
        self.processor = processor
        self.monitor = monitor
        self.gate = gate
        self.actuator = actuator
        self.audit = audit          # file-like; one JSON line per step
        self.history = []

    def step(self, signal):
        est = self.processor(signal)
        reflection = self.monitor(est)
        decision = self.gate.decide(est, reflection, self.history)
        command = None
        if decision.cleared:
            p = est.proposal
            command = Command(signal.step, p.action, p.magnitude, decision.by)
            # apply first: if the actuator raises, no phantom command is recorded
            self.actuator.apply(command)
            self.history.append(command)
            self.processor.on_command(command.delta)
        trace = Trace(signal.step, est, reflection, decision, command)
        if self.audit is not None:
            self.audit.write(json.dumps(trace.to_dict()) + '\n')
        return trace

    def run(self, feed):
        return [self.step(signal) for signal in feed]


def assemble(target, band, overseer, actuator, *, author, charter=None,
             spot_check=0.1, seed=0, audit=None, **monitor_args):
    """Wire the default layers together. Charter limits default to multiples of the band."""
    calibration = Calibration()
    if charter is None:
        charter = Charter([bounded_step(4 * band), consent_above(2 * band), restraint(3, 10)],
                          author=author)
    return Assembly(BandController(target, band),
                    Monitor(calibration=calibration, **monitor_args),
                    Gate(charter, overseer, calibration, spot_check=spot_check, seed=seed),
                    actuator, audit=audit)
