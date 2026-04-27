# Results -- Index for the Demo-of-Results Speaker

Read this file first, then descend into subfolders. Everything needed for the 2-minute Demo-of-Results presentation is in this directory tree.

## Folder layout

- **`demos/`** -- the 5 full-speed mp4 videos plus `routing_summary.md` (input -> tier -> p* table).
- **`gifs/`** -- the same 5 demos rendered as 6x sped-up animations with a 2-second tail freeze. README-friendly, drop-in usable.
- **`frames/`** -- 3 end-frame stills, one per target depth (25 / 50 / 75). Use as static slide assets if a moving GIF is not appropriate.
- **`router_metrics/`** -- quantitative evidence for the natural-language router:
    - `day14_router_evalset_metrics.json` (372 cases, raw)
    - `day14_router_eval_report.md` (evalset narrative)
    - `18_case_oov_typo_result.txt` (raw `unittest -v` stdout, 18/18 PASS)
    - `oov_typo_18cases.md` (the 18 cases as a readable table)
    - `router_accuracy_breakdown.png` (Phase 3.2 chart)
- **`stop_agent_metrics/`** -- quantitative evidence for the Phase 4 stop agent:
    - `seed41_state100_trajectory_dump.txt` (raw plug.z / socket.z / xy)
    - `00581_mesh_primitives.json` (geometry constants)
    - `first_crossing_steps.md` (25 / 50 / 75 trigger steps + interpretation)
    - `progress_curves_overlay.png` (Phase 3.2 chart)

## Recommended 2-minute talk outline

| Time  | Show                                            | Say                                                         |
|-------|-------------------------------------------------|-------------------------------------------------------------|
| 0:00  | one halfway GIF                                 | Pipeline in one shot. Type "halfway", robot stops at 50%. |
| 0:20  | three 25%-target GIFs (different inputs)        | Three different ways to ask for 25% -- exact, idiom, typo. All hit the same depth. |
| 0:50  | the most-of-the-way GIF                         | Same robot, same policy. Different words gets 75%.        |
| 1:10  | router_accuracy_breakdown chart                 | 372 / 372 on evalset, 18 / 18 on OOV+typo, 9 / 9 on unit tests. |
| 1:30  | progress_curves_overlay chart                   | Physics side: progress is z-only, gated by lateral and lift. Three targets trip at 150 / 179 / 186. |

## Key numbers worth memorising

- **Router**: 372 / 372 evalset accuracy = 100%; 18 / 18 OOV+typo accuracy = 100%; 9 / 9 unit-test pass.
- **Stop-agent**: first-crossing steps **150 / 179 / 186** for 25 / 50 / 75 targets.
- **Geometry constants** (00581-specific):
    - aperture-bottom offset 1.553 cm above plug-frame origin
    - shaft-top offset 7.47 cm above socket-frame origin
    - shaft-base offset 1.07 cm above socket-frame origin (1/7 base)
    - lateral admit 22 mm; lift gate 7 cm

## What this folder does NOT contain

- **No model checkpoints** (`*.pth`, `*.ckpt`, `*.pt`). They are large and gitignored. To reproduce the demos, follow the upstream [VT-Refine](https://github.com/NVlabs/vt-refine) install, then drop our `dppo_extensions/` files into the right places via `scripts/install_dppo_extensions.sh`.
- **No raw simulation logs**. Only the curated calibration trajectory used for stop-agent verification.
- **No intermediate or failed sweep videos**. Only the five final demos.
