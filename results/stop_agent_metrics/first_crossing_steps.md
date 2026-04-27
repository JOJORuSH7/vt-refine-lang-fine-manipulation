# Stop-Agent First-Crossing Steps (Calibration Trajectory)

The Phase 4 stop agent uses a single physically-grounded `progress_z` quantity (z-only formula; see `docs/stop_agent_physics.md`) and triggers the hold behaviour when `progress_z >= target_progress` for the first time.

The numbers below come from the calibration trajectory (seed=41), the canonical case used to verify monotonicity and depth separability across the three target depths.

| Target depth | First-crossing step | Delta from previous | Visual outcome |
|--------------|---------------------|---------------------|----------------|
| 0.25 (shallow) | **150** | -    | rim sits on top, ~25% engaged |
| 0.50 (mid)     | **179** | +29  | rim mid-shaft, ~50% engaged |
| 0.75 (deep)    | **186** | +7   | rim near bottom, ~75% engaged |

## Implications for the project's fine-grained range (25 / 50 / 75)

- All three targets cross before step 200, with clear separation between trigger times.
- The delta between 0.50 and 0.75 (+7 steps) is much tighter than between 0.25 and 0.50 (+29 steps). The rim accelerates through the shaft once it clears the lateral-admit gate.
- The fine-grained range covers the practically useful mid-depth band where end-effector control matters most. Endpoint behaviours (no contact at 0% / fully seated at 100%) are out of scope for this controller and are typically handled as discrete primitives rather than a continuous depth target.

## Lateral / lift gates (from `00581_mesh_primitives.json`)

- `LATERAL_ADMIT_M = 0.022 m`. Rim center must be within 22 mm of the shaft axis before any progress is counted.
- `LIFT_GATE_M = 0.07 m`. The rim's running-max bottom-of-rim z must reach 7 cm before progress is gated open. Filters away the trivial start-of-episode high-progress reading caused by the rim being lifted passively above the shaft top.

The full physics derivation (why z-only and not full-pose) is in `docs/stop_agent_physics.md`.

## Raw data

`seed41_state100_trajectory_dump.txt` in this folder. Sampled every 12 steps; columns: step / plug.z / socket.z / xy distance.
