# System Architecture

How the router and stop agent compose end-to-end. Single page; companion to
`docs/methodology.md` (motivation) and `docs/stop_agent_physics.md` (physics).

## End-to-end dataflow

```mermaid
flowchart LR
    U[Free-form English<br/>"halfway" / "litlle bitt" / ...] --> R{4-tier router}
    R -- "Tier 1<br/>numeric / phrase" --> P[target_progress<br/>p* in {0.25, 0.50, 0.75}]
    R -- "Tier 2<br/>regex + fuzzy" --> P
    R -- "Tier 3<br/>SBERT zero-shot" --> P
    R -- "Tier 4<br/>fallback_unparsed" --> F[mode=fallback_unparsed,<br/>p*=0.5 (tagged)]
    P --> SA[Phase 4 v3 stop agent<br/>progress_z gated by<br/>lateral admit + lift gate]
    F --> SA
    SA -- "every step:<br/>progress_z &gt;= p*?" --> H{hold?}
    H -- no --> SA
    H -- yes --> Hold[Hold rim at depth,<br/>actions zeroed]
    Hold --> Demo[Demo mp4]
```

The whole pipeline is one process. The router produces a `RouteResult`
containing `(p_star, mode, ...)`. The driver script
`scripts/run_with_text_command.sh` reads `p_star` from the router's stdout,
exports it as an env var, and launches the Phase 4 stop agent. The stop
agent rolls the diffusion policy out for up to 240 steps, computing
`progress_z` from `plug.z` / `socket.z` at each step, and switches to a
zero-action hold when `progress_z >= p*`.

## Router internals (one-paragraph summary)

`route_instruction(text) -> RouteResult` runs four checks in priority order:

1. **`exact`** -- numeric formats (`25%`, `0.25`, `1/4`, `25 percent`) and
   the static phrase map (`halfway`, `quarter`, `fully`, ...). Returns
   `mode='exact'`.
2. **`semantic_offline`** (regex anchors + fuzzy correction) -- a
   hand-curated set of regex patterns that match informal English
   ("a little", "most of the way", "barely", "snug", "drive it home", ...).
   `difflib.get_close_matches` corrects typos before matching. Returns
   `mode='semantic_offline'`.
3. **`semantic_embedding`** -- sentence-transformers MiniLM-L6-v2 cosine
   similarity vs per-anchor exemplar sentences. Only consulted if tiers
   1-2 do not resolve. In the current evalset and held-out OOV set it
   never has to fire.
4. **`fallback_unparsed`** -- explicit failure mode. Returns
   `(p_star=0.5, mode='fallback_unparsed')` so callers can tell that the
   router did not understand, rather than mistakenly treating 0.5 as an
   intentional midpoint instruction.

Detailed waterfall, regex list, and known limitations are in
`docs/router_design.md`.

## Stop agent internals (one-paragraph summary)

Per timestep, given `plug.z` (rim height) and `socket.z` (shaft base height),
compute three world-frame z-coordinates from mesh-derived offsets:

- `aperture_bot = plug.z + APERTURE_BOTTOM_OFFSET (= 0.01553)`
- `shaft_top    = socket.z + SHAFT_TOP_OFFSET (= 0.0747)`
- `shaft_base   = socket.z + SHAFT_BASE_OFFSET (= 0.0107)`

Then:

`progress_z = clip((shaft_top - aperture_bot) / (shaft_top - shaft_base), 0, 1)`

Two gates suppress spurious early triggers (rim still being lifted into
position):

- `LATERAL_ADMIT_M = 0.022` -- xy distance between rim and shaft axis
  must be at most 22 mm.
- `LIFT_GATE_M = 0.07` -- the rim's running-max z must have reached 7 cm
  at least once.

If both gates pass, the agent triggers a hold the first time
`progress_z >= target_progress`. From that step on, all robot actions are
zeroed and the rim sits at depth.

Why z-only and not full-pose, why these specific offsets, and the upstream
naming convention "plug = aperture rim, socket = shaft" are derived in
`docs/stop_agent_physics.md`.

## Decision boundary between the two layers

The contract is one scalar (`target_progress`) and one mode label. The
router does **not** know about `progress_z`, mesh geometry, or the policy.
The stop agent does **not** know about English, embeddings, or fuzzy
matching. Either layer can be replaced independently:

- Swap the router for an LLM-based one without touching the stop agent.
- Swap the stop agent for a learned reward shaper without touching the
  router.

This is the whole reason the two layers exist as separate modules rather
than a single end-to-end pipeline.

## Where to read the code

| Concern                                       | File                                                                  |
|-----------------------------------------------|-----------------------------------------------------------------------|
| Router 4-tier dispatch                        | `router/router.py` -> `route_instruction(text)`                       |
| Phrase map, anchor exemplars                  | `router/router.py` -> `PHRASE_MAP`, `SEMANTIC_ANCHOR_EXEMPLARS`       |
| Regex anchors and soft-full suppression       | `router/router.py` -> `_direct_semantic_result`, `SOFT_FULL_PATTERNS` |
| Fuzzy typo correction                         | `router/router.py` -> `_fuzzy_correct`, `_normalize_text`             |
| Stop-agent main loop                          | `dppo_extensions/agent/eval/eval_diffusion_aperture_rim_stop_agent.py`|
| Geometry constants                            | same file, top of module                                              |
| Calibration logger (used to derive constants) | `dppo_extensions/agent/eval/eval_diffusion_calibration_log_agent.py`  |
| Mesh inspection (raw asset -> constants)      | `dppo_extensions/scripts/inspect_aperture_rim_mesh.py`                |
| End-to-end driver                             | `scripts/run_with_text_command.sh`                                    |
