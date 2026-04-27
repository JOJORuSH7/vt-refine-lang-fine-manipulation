# Known Pitfalls Caught During Development

A short list of non-obvious bugs we hit while building this system. Each
one cost real debugging time, and each one is the kind of issue that
generic ML or robotics intuition would not predict. We include them here
mostly so a reviewer reading the source can see *why* certain code looks
the way it does.

---

## 1. The `plug` link is the rim, not the bolt

**Symptom.** Early versions of the stop-agent progress formula used a
"plug enters socket" mental model, with `plug` as the male bolt and
`socket` as the female receiver. Every progress trace started near 1.0
and decreased over time -- a clear sign the formula was inverted.

**Diagnosis.** Print `plug.z` and `socket.z` for the first 60 steps and
look at the ranges. `plug.z` swept across roughly 0 to 11 cm (the rim
being lifted into position then descending onto the shaft). `socket.z`
stayed within 1 mm of the table. Whichever object moves a lot is the one
the robot is manipulating; that is the rim, not a bolt.

**Resolution.** Rewrite the formula treating `plug = white aperture rim`
and `socket = green shaft + base`. The naming is an upstream URDF quirk
in the AutoMate dataset and disagrees with the colloquial mechanical
sense of those words. Documented at the top of
`docs/stop_agent_physics.md` so no future contributor repeats this.

**General lesson.** Object-name semantics in third-party datasets are
not a reliable source of geometric truth. Check by replaying the
trajectory and looking at which numbers actually change.

---

## 2. The plug-link origin is **not** the rim's bottom face

**Symptom.** The first attempt to compute `progress_z` used `plug.z`
directly as the rim's bottom-face height. At step 0 of the calibration
trajectory, this gave `progress = 0.93` -- meaning "rim already sitting
at the shaft base before the episode starts". Visually wrong; the rim
is on the table at step 0.

**Diagnosis.** Inspect the plug mesh in `inspect_aperture_rim_mesh.py`
and look at the bounding box's z range *relative to the plug-link frame
origin*. The mesh extends from `z = 0.01553 m` to roughly `z = 0.0389 m`
in the link frame -- the rim's bottom face is **above** the link origin
by about 1.55 cm.

**Resolution.** Add a constant offset:
`aperture_bot_w = plug.z + APERTURE_BOTTOM_OFFSET (= 0.01553)`.
Same treatment for shaft top and shaft base. All three constants live
at the top of `eval_diffusion_aperture_rim_stop_agent.py`. With the
correction, step-0 progress is 0.0 as expected.

**General lesson.** A link's `pos` is the link-frame origin, which is
chosen by whoever exported the URDF and is not necessarily aligned to
any meaningful geometric feature. When you need a specific feature's
world position, derive the offset from the mesh and add it explicitly.

---

## 3. The demo camera was never being created

**Symptom.** Every demo mp4 was rendered from a top-down view, no matter
what we set `ALOHA_DEMO_CAMERA_OFFSET` and `ALOHA_DEMO_CAMERA_TARGET` to.
The driver script and the agent code both looked correct.

**Diagnosis.** Trace the camera-creation code in `easysim-envs/aloha.py`.
The demo camera is conditionally created when `ALOHA_DEMO_CAMERA=1` is
set in the environment. Without that flag, the agent silently falls
back to the policy observation camera, which is fixed top-down and not
the offset we want. Our driver script was setting `_OFFSET` and
`_TARGET` but not `ALOHA_DEMO_CAMERA` itself.

**Resolution.** Add `export ALOHA_DEMO_CAMERA=1` to
`scripts/run_with_text_command.sh` (and any other Phase 4 driver). The
sideview demo videos in `results/demos/` were re-rendered after this fix.

**General lesson.** When a configuration knob "does nothing", check
whether the *enabling* flag is set first. Read the camera-creation
condition; do not just stare at the offset values.

---

These three are the ones we think are most useful for a reviewer who
wants to understand the surface area of the system without re-walking
the whole debugging history. Several smaller issues (a typo in a regex
anchor that swallowed `"snug"`, a paste-pipeline bug that ate triple
backticks, an interpretation of seed-sweep variance that turned out to
be inverted) are recorded in our internal notes but are not central to
the design.
