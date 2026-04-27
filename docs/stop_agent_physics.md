# Stop-Agent Physics: z-only Progress Formula

The Phase 4 v3 stop agent uses a single scalar progress signal, derived from
z-coordinates of two link frames and three constants. This document explains
where the constants come from and why the z-only formulation is preferred to
alternatives that use the full 6D pose.

## Asset-side naming convention (important)

The 00581 AutoMate asset has two URDFs whose names are **opposite of common
sense**:

- `plug.urdf` is the white **aperture rim** (the part the robot lifts and
  brings down onto the shaft).
- `socket.urdf` is the green **shaft + base** (the static cylinder the rim
  slides onto).

This is verified by both the URDF / mesh content (the plug mesh is a thin
toroidal rim, the socket mesh is a tall solid cylinder) and the recorded
trajectory (during a successful run `plug.z` ranges over roughly 0 to 11 cm
while `socket.z` stays within 1 mm of the table surface). Throughout this
document and the source code, **plug = rim, socket = shaft**, regardless
of the colloquial meaning of "plug" and "socket" in mechanical assembly.

The `inspect_aperture_rim_mesh.py` script under `dppo_extensions/scripts/`
loads each URDF, scales the mesh, and prints these geometric primitives.
Its JSON output for 00581 is checked in at
`results/stop_agent_metrics/00581_mesh_primitives.json` and is the source
for the constants below.

## Geometry constants for 00581

| Constant                | Value (m)  | Meaning                                                       |
|-------------------------|-----------:|---------------------------------------------------------------|
| `APERTURE_BOTTOM_OFFSET` | `0.01553` | aperture-rim bottom face is 1.55 cm above the plug-link origin |
| `SHAFT_TOP_OFFSET`       | `0.0747`  | shaft tip is 7.47 cm above the socket-link origin              |
| `SHAFT_BASE_OFFSET`      | `0.0107`  | shaft base (top of cylindrical pedestal) is 1.07 cm above the socket-link origin |
| `LATERAL_ADMIT_M`        | `0.022`   | rim must be within 22 mm of the shaft axis (xy distance)        |
| `LIFT_GATE_M`            | `0.07`    | running-max rim height must reach 7 cm at least once            |

The first three are derived from the mesh; the lateral and lift gates are
chosen to suppress the only spurious-progress regime we observed during
calibration (the policy briefly hovers the rim above the shaft tip with
horizontal offset, which would otherwise read as `progress_z > 0`).

## Formula

At each timestep, given world-frame `plug.z` and `socket.z`:

```
aperture_bot_w = plug.z   + APERTURE_BOTTOM_OFFSET
shaft_top_w    = socket.z + SHAFT_TOP_OFFSET
shaft_base_w   = socket.z + SHAFT_BASE_OFFSET

progress_z_raw = (shaft_top_w - aperture_bot_w) / (shaft_top_w - shaft_base_w)
progress_z     = clip(progress_z_raw, 0, 1)
```

`progress_z` is 0 when the rim's bottom face is at or above the shaft tip,
and 1 when it is at the shaft base. The denominator is constant per asset.

Two gates filter spurious readings:

```
gate_lat  = (||rim_xy - shaft_xy||_2 <= LATERAL_ADMIT_M)
gate_lift = (running_max(aperture_bot_w) >= LIFT_GATE_M)
progress_final = progress_z * gate_lat * gate_lift
```

A hold is triggered the first step at which `progress_final >= target_progress`.
From that step on, the agent emits zero actions for the remainder of the
episode.

## Why z-only and not full-pose

A natural alternative would be to compute a signed distance from the rim's
inner-bottom edge to the seated pose, accounting for tilt. We rejected
this for three reasons:

1. **No free parameters.** The z-only formula reads only mesh constants and
   live link positions. Quaternion-aware variants need a tilt tolerance,
   which is asset- and policy-dependent and has to be tuned.
2. **Diagnosability.** When the formula misbehaves, the trajectory dump
   shows it in two columns. With a full-pose formulation it would take a
   short script to recover the same answer.
3. **The trained policy is already near-vertical at engagement.** Lateral
   admit catches the only relevant deviation; tilt within the admit cone
   has negligible impact on engaged depth.

## Validation against trajectory ground truth

We replay seed=41 and dump every 12 steps to
`results/stop_agent_metrics/seed41_state100_trajectory_dump.txt`. From the
recorded `plug.z` / `socket.z` we can compute `progress_z` offline; the
calibration log of the actual stop-agent run records the first step at
which `progress_z >= target_progress` for each of {0.25, 0.50, 0.75}.

| Target | First-crossing step |
|--------|---------------------|
| 0.25   | 150                 |
| 0.50   | 179                 |
| 0.75   | 186                 |

Monotone, well separated, and all comfortably before the 200-step horizon
we use for the demo videos.

## Plotted overlay

`results/stop_agent_metrics/progress_curves_overlay.png` overlays the
sparse-sampled `progress_z(t)` on the three target levels and the three
first-crossing steps. The visualisation is the canonical figure for the
2-minute Demo of Results.
