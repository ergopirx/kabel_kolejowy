"""Run the assembly against a scripted toy plant and report what each layer did.

    python3 -m transstructure [--steps 200] [--seed 3] [--audit trace.jsonl] [--interactive]
"""
import argparse
from collections import Counter

from .assembly import assemble
from .plant import ToyPlant
from .synchronisation import ConsoleOverseer, PolicyOverseer

TARGET, BAND = 50.0, 2.0

# what happens to the plant, and what each event should exercise
SCRIPT = {
    30: {'drift': 0.12},    # slow drift up, then down: routine autonomous corrections
    80: {'drift': -0.15},
    112: {'drift': 0.0},
    115: {'glitch': 80.0},  # one wild reading: set it aside, don't chase it
    125: {'noise': 2.5},    # sensor goes noisy: escalate, tell people
    140: {'noise': 0.5},
    155: {'shift': 5.0},    # sudden real change: confirm it; a large move needs consent
    172: {'bias': 4.5},     # sensor reads high, plant is fine: only a person can tell
    184: {'bias': 0.0},
}


def site_engineer(case):
    """A reviewer who can see the true level: agrees only when the proposal is right."""
    true = case.estimate.signal.meta['true_level']
    wanted = 'raise' if true < TARGET - BAND else 'lower' if true > TARGET + BAND else 'hold'
    if case.estimate.proposal.action == wanted:
        return True, f'agree, true level {true:.1f}'
    return False, f'disagree, true level {true:.1f} calls for {wanted}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--steps', type=int, default=200)
    ap.add_argument('--seed', type=int, default=3)
    ap.add_argument('--audit', help='write one JSON line per step to this file')
    ap.add_argument('--interactive', action='store_true',
                    help='you review escalations at the terminal')
    args = ap.parse_args()

    plant = ToyPlant(level=TARGET, steps=args.steps, seed=args.seed, script=SCRIPT)
    overseer = (ConsoleOverseer('you') if args.interactive
                else PolicyOverseer('site engineer', site_engineer))
    audit = open(args.audit, 'w') if args.audit else None
    try:
        asm = assemble(TARGET, BAND, overseer, plant, author='site engineer',
                       seed=args.seed, audit=audit)
        traces = asm.run(plant)
    finally:
        if audit:
            audit.close()

    print(f'{"step":>4} {"read":>6} {"level":>6} {"true":>6}  {"proposal":<13} {"conf":>5}  '
          f'{"verdict":<8} {"route":<10} {"by":<14} why')
    for t in traces:
        quiet = t.decision.route in ('hold', 'autonomous') or (
            t.decision.route == 'abstain' and t.reflection.reasons[0].startswith('warming'))
        if quiet and t.command is None:
            continue
        p = t.estimate.proposal
        why = '; '.join(t.reflection.reasons + t.decision.notes)
        print(f'{t.step:>4} {t.estimate.signal.value:>6.2f} {t.estimate.level:>6.2f} '
              f'{t.estimate.signal.meta["true_level"]:>6.2f}  {p.action:<6} {p.magnitude:>5.2f}  '
              f'{p.confidence:>5.3f}  {t.reflection.verdict.value:<8} {t.decision.route:<10} '
              f'{t.decision.by:<14} {why}')

    routes = Counter(t.decision.route for t in traces)
    in_band = sum(abs(t.estimate.signal.meta['true_level'] - TARGET) <= BAND for t in traces)
    cal = asm.monitor.calibration
    print()
    print('routes   ', ', '.join(f'{k} {v}' for k, v in sorted(routes.items())))
    print('commands ', len(asm.history), 'actuated:',
          ', '.join(f'{k} {v}' for k, v in Counter(c.authorised_by for c in asm.history).items()))
    print(f'reviews   {len(cal.reviews)}, Brier score {cal.brier():.3f}, '
          f'autonomy threshold now {asm.monitor.threshold:.3f} (floor {asm.monitor.min_confidence})')
    print(f'true level in band for {in_band}/{len(traces)} steps')


if __name__ == '__main__':
    main()
