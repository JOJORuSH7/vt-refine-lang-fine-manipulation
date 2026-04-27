# Upstream Changes Notice

This document satisfies the modification-notice requirement of the NVIDIA
Source Code License inherited from
[NVlabs/vt-refine](https://github.com/NVlabs/vt-refine).

## Relationship to upstream

This repository is **not** a fork. It contains only files we authored,
plus the inherited `LICENSE`. None of the upstream VT-Refine source code
is copied here. Our additions are designed to drop into a local clone of
vt-refine via `scripts/install_dppo_extensions.sh` (see also
`dppo_extensions/README.md`).

The runtime dependency is real: our `eval_diffusion_aperture_rim_stop_agent`
imports the upstream diffusion-policy classes and runs inside the upstream
simulator. That makes our code a derivative work in the NSCL sense, even
though no upstream source is redistributed in this tree.

## Files we authored

All files in this repository are our additions. The list below is split by
where they live in our tree, with a one-line description of each.

### `router/`

| File | Purpose |
|------|---------|
| `router/router.py` | The 4-tier router itself: `route_instruction(text) -> RouteResult`. Phrase map, regex anchors, fuzzy correction, SBERT backstop, fallback. |

### `tests/`

| File | Purpose |
|------|---------|
| `tests/test_router.py` | Unit tests for numeric / phrase / regex routing. |
| `tests/test_router_typos.py` | 18-case OOV/typo regression set, also runnable via `python3 -m unittest tests.test_router_typos -v`. |

### `dppo_extensions/`

These four files are written to drop into a local vt-refine clone at the
matching paths. We never imported, copied, or modified upstream code; the
files import upstream by name and rely on it being on the Python path.

| File | Drops into | Purpose |
|------|------------|---------|
| `dppo_extensions/agent/eval/eval_diffusion_aperture_rim_stop_agent.py` | `dppo/agent/eval/` | Phase 4 v3 stop agent: z-only progress + lateral and lift gates + hold on first crossing. |
| `dppo_extensions/agent/eval/eval_diffusion_calibration_log_agent.py` | `dppo/agent/eval/` | Calibration-trajectory dumper used to derive geometry constants. |
| `dppo_extensions/scripts/inspect_aperture_rim_mesh.py` | `dppo/scripts/` | Mesh inspector that emits geometry primitives JSON for an asset. |
| `dppo_extensions/scripts/analyze_aperture_rim_progress.py` | `dppo/scripts/` | Offline progress-curve analyzer (kept for reference; the v3 stop agent supersedes it). |

### `scripts/`

| File | Purpose |
|------|---------|
| `scripts/run_with_text_command.sh` | End-to-end driver: text -> router -> stop agent -> mp4. |
| `scripts/run_aperture_rim_pipeline.sh` | Phase 1->4 pipeline driver (mesh inspection -> calibration -> stop agent run). |
| `scripts/install_dppo_extensions.sh` | One-shot install of the four `dppo_extensions/` files into a target vt-refine clone. |

### `results/`

Curated final outputs (5 mp4 + 5 GIF + 3 PNG + metrics + 2 charts + per-folder
README). All of this content was generated from runs of our own agent and
analysis code on the upstream simulator. None of it is upstream-authored.

### `docs/`

All written by us:

`methodology.md`, `system_architecture.md`, `stop_agent_physics.md`,
`router_design.md`, `known_pitfalls.md`, and this file
(`upstream_changes.md`).

### Repository root

`README.md`, `CITATION.cff`, `CONTRIBUTORS.md`, `.gitignore`,
`.gitattributes` -- all written by us. `LICENSE` is copied verbatim from
upstream and intentionally not modified.

## What we did **not** modify

- No upstream Python files (under `dppo/`, `easysim-envs/`, `cfg/`,
  `data/`, `docker/`) are present in this tree.
- No upstream `LICENSE` text was modified -- the file at the root of
  this repository is byte-identical to upstream.
- No upstream config files were forked or rewritten.

## Reproducibility caveat

Because we do not redistribute upstream code, reproducing the demos
requires a separate installation of vt-refine following its own
instructions, after which the install script merges our four
`dppo_extensions/` files into the appropriate paths in that clone.
See README.md "Reproducing the demos" for the procedure.
