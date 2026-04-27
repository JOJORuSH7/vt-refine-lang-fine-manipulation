# Methodology

Written companion to the in-class Methodology presentation. Targets a reader who
has not used the system; assumes familiarity with diffusion-policy-based
behavioural cloning and reinforcement-learning fine-tuning at a course-survey
level.

## Problem statement

Make a ALOHA bimanual robot insert a metal aperture rim onto a cylindrical
shaft (the 00581 nut-and-bolt asset from AutoMate) at a depth that the human
operator specifies in **free-form English**. The pipeline must

1. understand instructions of the form `"insert 25 percent"`, `"halfway"`,
   `"insert a litlle bitt"` (typo), `"shove it in just a hair"` (idiom),
   `"asset 00081"` (off-task input), and route each to one of three discrete
   target depths in {0.25, 0.50, 0.75} (or to a `fallback_unparsed` mode);
2. drive the diffusion-based RL policy from VT-Refine to that target depth and
   *hold* the rim there, even though the policy was trained for full
   bottom-out insertion;
3. produce a single mp4 of the run as an end-to-end demo.

The course requires (a) source review, (b) a Methodology presentation, and
(c) a 2-minute Demo of Results with quantitative evidence.

## Why two layers, and exactly these two

The VT-Refine pipeline already covers the visual + tactile diffusion policy,
its RL fine-tuning, and rendering. What it does **not** provide:

- a way to issue partial-depth insertion commands -- the policy is trained
  for one outcome (full insertion);
- a way for a non-technical operator to specify those depths in English
  rather than as a float.

So we add exactly two layers:

| Layer                    | Goal                                              | What it is             |
|--------------------------|---------------------------------------------------|------------------------|
| **Router**               | English -> one of {0.25, 0.50, 0.75} or fallback  | Symbolic + semantic, 4-tier |
| **Stop agent (Phase 4 v3)** | Hold the policy at p\*                          | z-only progress + lateral and lift gates |

Each layer is independent of the other in implementation; they communicate
through a single scalar `target_progress`.

## Design principles

The two design principles below shaped most concrete decisions and are worth
naming explicitly because they are also the lens we want to be evaluated by.

### 1. Symbolic-first, semantic as backstop

Numeric percents (`25%`, `0.25`, `1/4`), a hand-curated phrase map (`halfway`,
`fully`, `quarter`, ...), and regex anchors are checked **before** any
embedding model is consulted. This makes routing on known idioms deterministic,
makes typos trivially correctable via difflib, and makes failures explicit
(an unrelated input lands in `fallback_unparsed`, returning a tagged 0.5
rather than silently). The SBERT embedding tier exists, but in the 372-case
in-distribution evalset and the 18-case OOV/typo set it never had to fire --
the regex anchors plus fuzzy correction cover the relevant idioms.

This is a deliberate trade against an "LLM does everything" approach. A
symbolic core is much easier to reason about, debug, and unit-test, which
matters for a class project where reviewers want to read the code.

### 2. Physics-grounded stop signal, not learned

The stop signal is one scalar per timestep: `progress_z`, computed from
`plug.z`, `socket.z`, and three geometry constants derived from the 00581
mesh (aperture-bottom offset, shaft-top offset, shaft-base offset). Two
gates filter spurious early-episode triggers:

- **Lateral admit** -- the rim's xy must be within 22 mm of the shaft axis,
  otherwise progress reads zero.
- **Lift gate** -- the rim must have been lifted to at least 7 cm at some
  prior timestep, otherwise progress reads zero.

We considered, and rejected, three alternative formulations: a learned reward
shaper, a quaternion-aware "signed distance to seated pose", and a
gate-based delay (count N steps after lateral admission). The z-only
formula has two virtues that the alternatives do not: it has zero free
parameters that have to be tuned per asset (only mesh-derived offsets), and
the formula is transparent enough that any failure mode is diagnosable from
a single trajectory dump.

Geometry derivation, the reason "plug" actually means the white aperture rim
and "socket" means the green shaft (an upstream naming quirk), and the
calibration trajectory we used to validate are all in
`docs/stop_agent_physics.md`.

## Evaluation methodology

We evaluate the two layers separately, then together end-to-end.

### Router

- 372-case **in-distribution evalset**, hand-constructed across 7 input
  categories (numeric percents / decimals / fractions, exact phrases, regex
  anchors / fuzzy, ambiguous, unparsed). String-level disjoint from the
  unit-test inputs (`leakage_policy` recorded in
  `results/router_metrics/day14_router_evalset_metrics.json`).
- 18-case **held-out OOV/typo set**, written *after* the regex anchors and
  phrase map were frozen. Includes double typos (`"insert a litlle bitt"`)
  and idioms (`"shove it in just a hair"`, `"engage just enough to feel it"`).
- 9-case unit-test set (`tests/test_router.py`).

Result: 100 % on all three. The breakdown is in
`results/router_metrics/router_accuracy_breakdown.png`.

### Stop agent

- Calibration trajectory at seed = 41. We replay the trained policy to
  step 200 and record `plug.z`, `socket.z`, and xy distance every 12
  steps in `results/stop_agent_metrics/seed41_state100_trajectory_dump.txt`.
- For each of the three target depths {0.25, 0.50, 0.75} we report the
  first step at which `progress_z >= target_progress`. The three crossings
  are at steps 150, 179, 186 -- monotonic, well-separated, all before
  step 200. Visualised in
  `results/stop_agent_metrics/progress_curves_overlay.png`.

### End-to-end

- 5 demo runs, each a different free-form English input, recorded as mp4
  under `results/demos/`. Animated 6x sped-up versions under
  `results/gifs/` are README-friendly.
- Per-demo routing decision is dumped from `route_instruction(text)` at
  doc-generation time and stored in
  `results/demos/routing_summary.md`. Three different inputs route to the
  same 25 % goal, demonstrating that the router maps surface-form
  variation onto a single discrete target without surprises.
