# Transstructure — metacognitive control skeleton

A runnable skeleton for an automated controller that watches its own reasoning
and keeps people in charge of what it does. It takes a signal feed, processes it
into a proposed action, asks whether its own processing can be trusted right
now, checks the action against principles people wrote, and only then actuates.
Every step leaves one trace across all five layers.

Pure Python 3.10+ standard library. No dependencies.

```
signal feed ─▶ processing ─▶ metacognition ─▶ synchronisation ─▶ actuation
 (Signal)      (Estimate,     (Reflection:     (Charter, Overseer,  (Command)
                Proposal)      proceed /        Calibration ->
                               abstain /        Decision)
                               escalate)
     └──────────────── one Trace per step, across every layer ───────────────┘
```

## What each term means here

| Term | Module | What it actually does |
| --- | --- | --- |
| signal feed | `signals.py` | Any iterable of `Signal(source, step, value, meta)`. `ReplayFeed` replays recorded values. |
| processing | `processing.py` | `BandController` keeps a signal inside target ± band. It smooths the level, sets aside glitches, re-anchors on real jumps and proposes `hold`, `raise` or `lower` with a confidence. |
| metacognition | `metacognition.py` | `Monitor` asks whether the processor should be trusted right now, not what it should do. It checks for warm-up, glitches, level jumps, noise-regime change, direction reversals and doubt that lasts. Its verdict is `proceed`, `abstain` or `escalate`. |
| synchronisation with people | `synchronisation.py` | `Charter` holds principles people wrote, each with its reason. `Overseer` is whoever answers. `Calibration` tracks how often people agree with the assembly. `Gate` decides whether an action happens and on whose authority. |
| actuation | `actuation.py` | `Command` and the `Actuator` protocol. Nothing outside the gate creates commands. |
| assembly | `assembly.py` | `Assembly` wires the layers together, and `assemble()` builds one with defaults. |
| transstructure | `Trace` | The record that cuts across every layer for every step, written as JSON lines to an audit file. |

The assembly has no virtues of its own. In practice, keeping it in step with
people means two things. Its freedom to act is bounded by principles people
wrote down. And its confidence bar is adjusted by the verdicts people give.

## Rules it keeps

1. **Holding never needs anyone's consent, and doubt falls back to it.** People
   are asked to approve actions, never inaction.
2. **Principles are not overridden case by case.** A `BLOCK` principle stops an
   action even if a person would approve it. Changing that is a charter
   amendment by a named person, and it is recorded. A `CONSENT` principle sends
   the action to a person.
3. **A "no" stands.** After a denial, the same action is withheld for `respect`
   steps without asking again. The assembly neither works around the refusal
   nor wears the person down with the same question.
4. **Silence is not consent, and not disagreement either.** If the overseer
   errors out or doesn't answer, the action is refused. That outcome isn't
   counted in calibration, and the question is asked again next step.
5. **It can become more cautious on its own, never less.** When people disagree
   with confident proposals, the autonomy threshold rises above the floor
   people set. It never drops below that floor.
6. **People hear about it when it's stuck.** If it is blocked by the charter,
   or escalating with nothing to approve, the overseer is notified once per
   episode, not on every step.
7. **Every step is recorded.** Abstentions, blocks, denials and actions all go
   into the trace in the same detail.

## Demo

```bash
python3 -m transstructure                     # scripted reviewer
python3 -m transstructure --interactive       # you review at the terminal
python3 -m transstructure --audit trace.jsonl # one JSON line per step
```

The demo runs a closed loop against a toy plant (`plant.py`). The plant drifts,
glitches, gets noisy, really shifts, and develops a sensor fault. The scripted
reviewer can see the plant's true level, which the assembly cannot. It agrees
only when a proposal is actually right.

```
step   read  level   true  proposal       conf  verdict  route      by             why
  56  54.07  52.67  53.24  lower   2.67  0.986  proceed  autonomous assembly
 112  47.01  47.62  47.08  raise   2.38  0.929  proceed  autonomous assembly
 115  80.00  49.52  48.99  hold    0.00  1.000  abstain  abstain    assembly       reading +33.4 spreads off the level, set aside
 129  43.24  49.07  48.99  hold    0.00  1.000  escalate abstain    assembly       3 of the last 10 readings set aside; the noise model no longer fits; ...; people notified
 157  53.75  53.82  53.99  lower   3.82  1.000  escalate approved   site engineer  level jumped to 53.82; confirm before acting on it; escalated; agree, true level 54.0
 174  55.72  55.44  50.94  lower   5.44  1.000  escalate denied     site engineer  level jumped to 55.44; ...; consent required; disagree, true level 50.9 calls for hold
 175  55.74  55.50  50.94  lower   5.50  1.000  proceed  withheld   site engineer  lower refused by site engineer at step 174
 186  52.01  51.70  50.94  hold    0.00  0.975  escalate abstain    assembly       level jumped to 51.70; confirm before acting on it; confidence 0.975 below 0.999; people notified

routes    abstain 61, approved 1, autonomous 3, denied 1, hold 125, withheld 9
commands  4 actuated: assembly 3, site engineer 1
reviews   2, Brier score 0.500, autonomy threshold now 0.999 (floor 0.9)
```

| Event | What the assembly did |
| --- | --- |
| slow drift up, then down (30–112) | It waited while the level was on the band edge (a coin flip), then corrected on its own once it was sure. |
| one wild reading (115) | It set the reading aside and didn't chase it. |
| noisy sensor (125–140) | The noise model stopped fitting, so it escalated. Proposals were all `hold`, so people were notified once, not asked every step. |
| real jump of +5 (155) | It re-anchored after three consistent readings and asked for confirmation. A person approved. |
| sensor reads +4.5 high, plant fine (172) | This looks identical to a real jump. Only a person can tell the difference. They refused, the refusal stood without re-asking, and the autonomy threshold rose because the assembly had been confident and wrong. |

## Extending it

Each layer is a seam you can replace:

- **Feed**: any iterable of `Signal`.
- **Processor**: any callable `Signal -> Estimate`, plus `on_command(delta)`.
- **Actuator**: anything with `apply(command)`.
- **Overseer**: `review(case) -> Review | None` and `notify(case)`. A real one
  would page someone and return `None` on timeout.
- **Principles**: `Principle(name, rationale, check)`, where `check(proposal,
  context)` returns `(Severity, detail)` or `None`.

## Known limits

- **The processor is a placeholder.** Its smoothed level lags a steady drift by
  about `drift × (1 − α) / α`. Under a 0.1/step drift, the true level overshoots
  the band edge by up to about 1 unit before each correction (see
  `test_closed_loop_...`). A trend-aware estimator would close that gap.
- **A sensor offset and a real jump look identical to the assembly.** That is
  deliberate: it escalates both, because only a person can tell them apart.
- **Calibration only learns from reviewed cases.** Spot checks (`spot_check`,
  default 10% of autonomous actions) keep it from seeing only the doubtful ones,
  but the sample is still small.
- **State lives in memory.** Calibration, standing denials and the charter do
  not survive a restart.
- **Review is synchronous.** The loop waits for each answer.

## Tests

```bash
python3 -m unittest discover -s transstructure/tests -t .
```

The 25 tests cover each layer on its own and the closed loop end to end. That
includes:

- a glitch that is set aside while a real shift re-anchors the level;
- confidence that is exactly 0.5 on the band edge;
- a block that overrides a would-be approval;
- denials that stand;
- a failing overseer that fails closed without skewing calibration;
- an actuator failure that leaves no phantom command;
- overcorrection (a plant that moves 3× what is commanded) being caught as
  direction reversals.

On 50,000 quiet readings the monitor raised no escalations, and set aside 0.05%
of readings as glitches.
