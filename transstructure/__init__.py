"""Transstructure: a metacognitive control skeleton with people in the loop.

    signal feed ─▶ processing ─▶ metacognition ─▶ synchronisation ─▶ actuation
     (Signal)      (Estimate,     (Reflection:     (Charter, Overseer,  (Command)
                    Proposal)      proceed /        Calibration ->
                                   abstain /        Decision)
                                   escalate)
         └──────────────── one Trace per step, across every layer ───────────────┘
"""
from .actuation import Command, RecordingActuator
from .assembly import Assembly, Trace, assemble
from .metacognition import Calibration, Monitor, Reflection, Verdict
from .processing import BandController, Estimate, Proposal
from .signals import ReplayFeed, Signal
from .synchronisation import (Case, Charter, ConsoleOverseer, Context, Decision, Finding, Gate,
                              Overseer, PolicyOverseer, Principle, Review, Severity,
                              bounded_step, consent_above, restraint)
