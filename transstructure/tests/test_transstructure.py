import io
import json
import math
import random
import unittest

from transstructure import (BandController, Calibration, Charter, Estimate, Gate, Monitor,
                            PolicyOverseer, Proposal, RecordingActuator, Reflection, Signal,
                            Verdict, assemble, bounded_step, consent_above, restraint)
from transstructure.plant import ToyPlant


def readings(n, level=50.0, noise=0.5, seed=1):
    rng = random.Random(seed)
    return [level + rng.gauss(0.0, noise) for _ in range(n)]


def feed(ctl, values, start=0):
    return [ctl(Signal('test', start + i, v)) for i, v in enumerate(values)]


def estimate(step, action='hold', confidence=1.0, magnitude=0.0, n=None, spread=0.5,
             outlier=None):
    return Estimate(Signal('test', step, 50.0), step + 1 if n is None else n, 50.0, spread,
                    0.0, outlier, Proposal(action, magnitude, confidence, ''))


def warmed_monitor(**kw):
    m = Monitor(warmup=20, **kw)
    for i in range(20):
        m(estimate(i))
    return m


class Recorder:
    """An overseer that answers from a list and remembers what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked, self.notices = [], []

    def review(self, case):
        from transstructure import Review
        self.asked.append(case)
        answer = self.answers.pop(0) if self.answers else True
        if isinstance(answer, Exception):
            raise answer
        return None if answer is None else Review(answer, 'tester')

    def notify(self, case):
        self.notices.append(case)


class ProcessingTest(unittest.TestCase):
    def setUp(self):
        self.ctl = BandController(target=50.0, band=2.0)
        self.ctl.n = self.ctl.updates = 100
        self.ctl.var = 0.25

    def test_band_edge_is_a_coin_flip(self):
        self.ctl.level = 52.0
        self.assertAlmostEqual(self.ctl.propose().confidence, 0.5, places=6)
        self.ctl.level = 52.0 + 1e-9
        p = self.ctl.propose()
        self.assertEqual(p.action, 'lower')
        self.assertAlmostEqual(p.confidence, 0.5, places=6)

    def test_far_outside_band_is_certain(self):
        self.ctl.level = 45.0
        p = self.ctl.propose()
        self.assertEqual(p.action, 'raise')
        self.assertAlmostEqual(p.magnitude, 5.0)
        self.assertGreater(p.confidence, 0.9999)

    def test_single_glitch_is_set_aside(self):
        ctl = BandController(50.0, 2.0)
        feed(ctl, readings(30))
        level, spread = ctl.level, ctl.spread
        est = ctl(Signal('test', 30, 80.0))
        self.assertEqual(est.outlier, 'glitch')
        self.assertEqual((ctl.level, ctl.spread), (level, spread))

    def test_run_of_outliers_reanchors_the_level(self):
        ctl = BandController(50.0, 2.0)
        feed(ctl, readings(30))
        ests = feed(ctl, [58.1, 57.9, 58.0], start=30)
        self.assertEqual([e.outlier for e in ests], ['glitch', 'glitch', 'shift'])
        self.assertAlmostEqual(ctl.level, 58.0)
        self.assertEqual(ests[-1].proposal.action, 'lower')

    def test_non_finite_reading_leaves_state_alone(self):
        ctl = BandController(50.0, 2.0)
        feed(ctl, readings(5))
        n, level = ctl.n, ctl.level
        est = ctl(Signal('test', 5, math.nan))
        self.assertEqual((ctl.n, ctl.level), (n, level))
        self.assertEqual(est.proposal.confidence, 0.0)

    def test_spread_tracks_the_noise(self):
        ctl = BandController(50.0, 2.0)
        feed(ctl, readings(400, noise=0.5))
        # residual RMS of an alpha=0.2 EWMA is sigma * sqrt(2 / (2 - alpha)) ~ 0.53
        self.assertAlmostEqual(ctl.spread, 0.53, delta=0.12)


class MonitorTest(unittest.TestCase):
    def test_warm_up_abstains(self):
        m = Monitor(warmup=5)
        verdicts = [m(estimate(i)).verdict for i in range(6)]
        self.assertEqual(verdicts, [Verdict.ABSTAIN] * 5 + [Verdict.PROCEED])

    def test_noise_increase_escalates(self):
        ctl, m = BandController(50.0, 2.0), Monitor()
        quiet = [m(e) for e in feed(ctl, readings(40, noise=0.5))]
        noisy = [m(e) for e in feed(ctl, readings(20, noise=3.0, seed=2), start=40)]
        self.assertNotIn(Verdict.ESCALATE, [r.verdict for r in quiet])
        self.assertIn(Verdict.ESCALATE, [r.verdict for r in noisy])

    def test_reversals_escalate(self):
        m = warmed_monitor()
        r = [m(estimate(20 + i, a, magnitude=2.0)) for i, a in enumerate(['raise', 'lower', 'raise'])]
        self.assertEqual(r[1].verdict, Verdict.PROCEED)
        self.assertEqual(r[2].verdict, Verdict.ESCALATE)
        self.assertIn('reversed direction', r[2].reasons[0])

    def test_lasting_doubt_about_a_move_escalates_doubt_about_holding_does_not(self):
        m = warmed_monitor(patience=3)
        moves = [m(estimate(20 + i, 'lower', 0.6, 2.0)).verdict for i in range(5)]
        self.assertEqual(moves, [Verdict.ABSTAIN] * 3 + [Verdict.ESCALATE] * 2)
        holds = [m(estimate(25 + i, 'hold', 0.6)).verdict for i in range(10)]
        self.assertEqual(set(holds), {Verdict.ABSTAIN})

    def test_shift_escalates_and_glitch_abstains(self):
        m = warmed_monitor()
        self.assertEqual(m(estimate(20, outlier='shift')).verdict, Verdict.ESCALATE)
        self.assertEqual(m(estimate(21, outlier='glitch')).verdict, Verdict.ABSTAIN)


class CalibrationTest(unittest.TestCase):
    def test_disagreement_raises_the_threshold(self):
        cal = Calibration()
        m = Monitor(min_confidence=0.9, calibration=cal)
        cal.record(0.95, agreed=False)
        self.assertGreater(m.threshold, 0.9)
        self.assertLessEqual(m.threshold, 0.999)

    def test_threshold_never_drops_below_its_floor(self):
        cal = Calibration()
        m = Monitor(min_confidence=0.9, calibration=cal)
        for _ in range(20):
            cal.record(0.5, agreed=True)        # underconfident
        self.assertLess(cal.overconfidence(), 0)
        self.assertEqual(m.threshold, 0.9)


class GateTest(unittest.TestCase):
    PROCEED = Reflection(Verdict.PROCEED, (), 0.9)
    ESCALATE = Reflection(Verdict.ESCALATE, ('test',), 0.9)

    def gate(self, overseer, *principles, **kw):
        kw.setdefault('spot_check', 0.0)
        return Gate(Charter(principles, author='tester'), overseer, Calibration(), **kw)

    def test_block_wins_and_people_are_told_once(self):
        person = Recorder()
        gate = self.gate(person, bounded_step(3.0))
        decisions = [gate.decide(estimate(i, 'lower', 1.0, 5.0), self.ESCALATE, [])
                     for i in range(30, 34)]
        self.assertEqual({d.route for d in decisions}, {'blocked'})
        self.assertEqual(person.asked, [])
        self.assertEqual(len(person.notices), 1)
        gate.decide(estimate(40, 'lower', 1.0, 5.0), self.PROCEED, [])
        self.assertEqual(len(person.notices), 2)    # a new episode

    def test_consent_goes_to_a_person(self):
        person = Recorder(True)
        d = self.gate(person, consent_above(3.0)).decide(
            estimate(30, 'lower', 1.0, 4.0), self.PROCEED, [])
        self.assertEqual((d.route, d.cleared, d.by), ('approved', True, 'tester'))
        self.assertEqual(person.asked[0].why, ('consent required',))

    def test_restraint_asks_after_repeated_commands(self):
        from transstructure import Command
        person = Recorder(False)
        history = [Command(s, 'lower', 1.0, 'assembly') for s in (25, 27, 29)]
        d = self.gate(person, restraint(3, 10)).decide(
            estimate(30, 'lower', 1.0, 1.0), self.PROCEED, history)
        self.assertEqual(d.route, 'denied')

    def test_holding_never_needs_a_person(self):
        person = Recorder()
        d = self.gate(person).decide(estimate(30, 'hold', 1.0), self.ESCALATE, [])
        self.assertEqual((d.route, d.cleared), ('abstain', False))
        self.assertEqual(person.asked, [])
        self.assertEqual(len(person.notices), 1)

    def test_a_denial_stands_without_asking_again(self):
        person = Recorder(False)
        gate = self.gate(person, respect=5)
        first = gate.decide(estimate(30, 'lower', 0.5, 2.0), self.ESCALATE, [])
        later = [gate.decide(estimate(s, 'lower', 1.0, 2.0), self.PROCEED, [])
                 for s in range(31, 36)]
        self.assertEqual(first.route, 'denied')
        self.assertEqual({d.route for d in later}, {'withheld'})
        self.assertEqual(len(person.asked), 1)
        # other actions are unaffected, and the denial lapses after the window
        self.assertEqual(gate.decide(estimate(36, 'raise', 1.0, 2.0), self.PROCEED, []).route,
                         'autonomous')
        self.assertEqual(gate.decide(estimate(37, 'lower', 1.0, 2.0), self.PROCEED, []).route,
                         'autonomous')

    def test_silence_and_errors_fail_closed_and_teach_nothing(self):
        person = Recorder(None, RuntimeError('pager down'), True)
        gate = self.gate(person)
        d1 = gate.decide(estimate(30, 'lower', 0.9, 2.0), self.ESCALATE, [])
        d2 = gate.decide(estimate(31, 'lower', 0.9, 2.0), self.ESCALATE, [])
        d3 = gate.decide(estimate(32, 'lower', 0.9, 2.0), self.ESCALATE, [])
        self.assertEqual([d.route for d in (d1, d2, d3)], ['unanswered', 'unanswered', 'approved'])
        self.assertFalse(d1.cleared or d2.cleared)
        self.assertIn('pager down', d2.notes[-1])
        self.assertEqual(len(gate.calibration.reviews), 1)

    def test_spot_checks_sample_autonomous_actions(self):
        person = Recorder()
        gate = self.gate(person, spot_check=0.5, seed=4)
        routes = [gate.decide(estimate(30 + i, 'lower', 1.0, 1.0), self.PROCEED, []).route
                  for i in range(200)]
        self.assertTrue(60 < routes.count('approved') < 140)
        self.assertEqual(routes.count('approved') + routes.count('autonomous'), 200)


class CharterTest(unittest.TestCase):
    def test_amendments_need_a_named_person(self):
        with self.assertRaises(ValueError):
            Charter([bounded_step(1.0)], author='')
        charter = Charter([bounded_step(1.0)], author='a')
        charter.amend(bounded_step(2.0), by='b', note='loosened after review')
        charter.repeal('bounded-step', by='c')
        self.assertEqual([(a[0], a[2]) for a in charter.amendments],
                         [('adopt', 'a'), ('adopt', 'b'), ('repeal', 'c')])
        with self.assertRaises(ValueError):
            charter.amend(bounded_step(9.0), by=None)


class AssemblyTest(unittest.TestCase):
    def test_closed_loop_keeps_the_plant_in_band_and_audits_every_step(self):
        plant = ToyPlant(steps=200, seed=5, script={30: {'drift': 0.1}})
        audit = io.StringIO()
        asm = assemble(50.0, 2.0, Recorder(), plant, author='tester', audit=audit)
        traces = asm.run(plant)
        lines = [json.loads(line) for line in audit.getvalue().splitlines()]
        self.assertEqual(len(traces), 200)
        self.assertEqual([line['step'] for line in lines], list(range(200)))
        # uncorrected, the drift would carry the level to 67. The smoothed level lags
        # the drift, and the assembly waits to be sure, so it overshoots the band
        # edge a little before each correction, but never by much
        true_levels = [t.estimate.signal.meta['true_level'] for t in traces]
        self.assertLess(max(abs(x - 50.0) for x in true_levels), 3.5)
        self.assertGreater(sum(abs(x - 50.0) <= 2.0 for x in true_levels), 100)
        self.assertGreater(len(asm.history), 5)
        for t in traces:
            self.assertEqual(t.command is not None, t.decision.cleared)

    def test_nothing_actuates_during_warm_up(self):
        actuator = RecordingActuator()
        asm = assemble(50.0, 2.0, Recorder(), actuator, author='tester', warmup=20)
        asm.run([Signal('test', i, 60.0) for i in range(20)])
        self.assertEqual(actuator.commands, [])

    def test_overcorrection_is_noticed(self):
        # the plant moves three times what is commanded, so corrections overshoot
        plant = ToyPlant(steps=120, gain=3.0, seed=6, script={30: {'shift': 4.0}})
        asm = assemble(50.0, 2.0, Recorder(), plant, author='tester',
                       charter=Charter([], author='tester'))
        reasons = [r for t in asm.run(plant) for r in t.reflection.reasons]
        self.assertTrue(any(r.startswith('reversed direction') for r in reasons))

    def test_actuator_failure_records_no_command(self):
        class Broken:
            def apply(self, command):
                raise IOError('relay stuck')

        asm = assemble(50.0, 2.0, Recorder(), Broken(), author='tester', warmup=5)
        asm.run([Signal('test', i, 50.0 + (i % 2) * 0.1) for i in range(5)])
        with self.assertRaises(IOError):
            for i in range(5, 40):
                asm.step(Signal('test', i, 60.0))
        self.assertEqual(asm.history, [])


if __name__ == '__main__':
    unittest.main()
