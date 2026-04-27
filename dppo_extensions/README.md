# `dppo_extensions/` -- drop-in additions to upstream `vt-refine/dppo/`

The four Python files under this directory are written to be **dropped
into a local clone of [VT-Refine (NVlabs)](https://github.com/NVlabs/vt-refine)**
at the matching relative paths. They are not standalone -- they import
upstream classes and configurations and rely on `dppo/` and
`easysim-envs/` being on the Python path.

## Layout

```
dppo_extensions/
+-- agent/eval/
|   +-- eval_diffusion_aperture_rim_stop_agent.py    -> drops into dppo/agent/eval/
|   +-- eval_diffusion_calibration_log_agent.py      -> drops into dppo/agent/eval/
+-- scripts/
+-- inspect_aperture_rim_mesh.py                 -> drops into dppo/scripts/
+-- analyze_aperture_rim_progress.py             -> drops into dppo/scripts/
```

## What each file does

| File | Role |
|------|------|
| `eval_diffusion_aperture_rim_stop_agent.py` | The Phase 4 v3 stop agent. Subclass / variant of the upstream diffusion-policy eval agent that adds a `target_progress` parameter and uses the z-only `progress_z` formula (with lateral / lift gates) to trigger an action-zero hold. This is the agent invoked by `scripts/run_with_text_command.sh`. |
| `eval_diffusion_calibration_log_agent.py` | A "do nothing, just observe" agent that runs the trained policy and dumps `plug.z`, `socket.z`, and xy distance every N steps. Used to produce `results/stop_agent_metrics/seed41_state100_trajectory_dump.txt`, which in turn was used to validate the `progress_z` formula offline. |
| `inspect_aperture_rim_mesh.py` | Standalone script. Loads the `plug.urdf` and `socket.urdf` for an asset, scales the mesh, and prints the geometric primitives (bounding-box z range, base-vs-shaft separation, etc.) used to derive `APERTURE_BOTTOM_OFFSET`, `SHAFT_TOP_OFFSET`, `SHAFT_BASE_OFFSET`. The 00581 output is checked in at `results/stop_agent_metrics/00581_mesh_primitives.json`. |
| `analyze_aperture_rim_progress.py` | Offline progress-curve analyzer used during early Phase 3 development. Kept for reference; the Phase 4 v3 stop agent supersedes it for production use. |

## Installing into a vt-refine clone

Use the helper script:

```
bash scripts/install_dppo_extensions.sh /path/to/vt-refine
```

This copies each file from the structure above into the matching path in
the target vt-refine clone (`dppo/agent/eval/...` and `dppo/scripts/...`).
The script will refuse to overwrite if a target file already exists, so a
re-run after a partial install is safe.

After installing, run the end-to-end driver from inside the upstream
container:

```
ROUTER_SEMANTIC_BACKEND=auto bash scripts/run_with_text_command.sh "halfway"
```

## Why a separate top-level directory and not a fork

We chose this layout over forking vt-refine because it makes the
boundary between our additions and upstream completely unambiguous:
**every file under `dppo_extensions/` is ours**. A reviewer reading
this directory does not have to scroll past thousands of lines of
upstream code to find what we changed. The trade-off is the extra
install step above, which we think is worth it for a class project
whose first audience is the course staff reviewing source.

See also `docs/upstream_changes.md` for the corresponding NVIDIA-Source-
Code-License modification notice.
