"""
eval_diffusion_aperture_rim_stop_agent.py - Phase 4 v3 of the aperture-rim plan.

CLEAN REWRITE based on validated geometry from seed=41 + state_100 + Phase 2
calibration trajectory analysis. Replaces v1/v2 mesh-frame d_signed formula
which was wrong because plug link frame origin is NOT at the aperture/nut
center but 1.55cm below the nut bottom face.

Verified facts (from trajectory dump matching user visual ground truth):
  - plug link is the WHITE NUT (lifted-and-descending object).
    Aperture bottom in world frame = plug.z + 0.01553 m.
  - socket link is the GREEN BOLT (basically table-fixed).
    Shaft tip in world frame  = socket.z + 0.0747 m.
    Shaft base in world frame = socket.z + 0.0107 m.
  - In seed 41 state_100, max progress reached is 0.86 (policy ceiling).
    User visual confirms "nut hovers around 80% shaft depth". ✓

progress = clip( (shaft_top_world - aperture_bottom_world)
               / (shaft_top_world - shaft_base_world), 0, 1 )

Two gates suppress spurious progress before insertion actually starts:
  gate_lateral: |plug_xy - socket_xy| <= 0.022 m  (parts aligned for insertion)
  gate_lifted:  running max(aperture_bottom_world) >= 0.07 m  (the lift-and-
                descend phase has begun -- prevents spurious progress at
                step 0 when nut and bolt happen to be at similar z while
                in mid-air)

Stop trigger: when gated progress >= target_progress, freeze action.
Hold mode:    inherit from base class (current_joint_state).

Generalization:
  These constants are derived from 00581 mesh + observed plug/socket link
  frame conventions. For other AutoMate assets the conventions should be
  identical (plug link frame origin offset to aperture bottom from mesh
  OBJ z_min, socket link frame at mesh bottom). Should generalize without
  per-asset tuning, but verify by running the same dump script on the
  new asset's calibration npz before trusting demos.
"""

import logging
import os
import numpy as np

from agent.eval.eval_diffusion_stop_agent import EvalPCDiffusionStopAgent

log = logging.getLogger(__name__)


# ----- geometry constants (validated for 00581) -----
DEFAULT_APERTURE_BOTTOM_OFFSET = 0.01553   # m, plug.z + this = aperture bottom world z
DEFAULT_SHAFT_TOP_OFFSET       = 0.0747    # m, socket.z + this = shaft top world z
DEFAULT_SHAFT_BASE_OFFSET      = 0.0107    # m, socket.z + this = shaft base world z
DEFAULT_LATERAL_ADMIT_M        = 0.022     # m, lateral alignment threshold
DEFAULT_LIFT_GATE_M            = 0.07      # m, aperture must have been lifted this high


def _latest_state(prev_obs_venv):
    if "state" not in prev_obs_venv:
        return None
    s = prev_obs_venv["state"]
    if s.ndim == 3:
        return np.asarray(s[:, -1, :], dtype=np.float64)
    if s.ndim == 2:
        return np.asarray(s, dtype=np.float64)
    raise ValueError(f"unexpected state shape: {s.shape}")


class EvalPCDiffusionApertureRimStopAgent(EvalPCDiffusionStopAgent):
    """Z-only progress stop agent (v3).

    cfg keys (all optional):
      aperture_bottom_offset_m: default 0.01553
      shaft_top_offset_m:       default 0.0747
      shaft_base_offset_m:      default 0.0107
      lateral_admit_m:          default 0.022
      lift_gate_m:              default 0.07
    """

    def __init__(self, cfg):
        super().__init__(cfg)

        self._ap_off = float(cfg.get("aperture_bottom_offset_m", DEFAULT_APERTURE_BOTTOM_OFFSET))
        self._st_off = float(cfg.get("shaft_top_offset_m",       DEFAULT_SHAFT_TOP_OFFSET))
        self._sb_off = float(cfg.get("shaft_base_offset_m",      DEFAULT_SHAFT_BASE_OFFSET))
        self._lat_admit = float(cfg.get("lateral_admit_m",       DEFAULT_LATERAL_ADMIT_M))
        self._lift_gate = float(cfg.get("lift_gate_m",           DEFAULT_LIFT_GATE_M))

        # running max of aperture_bottom z, per env, for the lift gate
        self._running_max_apert = None  # (n_envs,) float64

        log.info(
            f"[APERTURE_RIM v3] init  ap_off={self._ap_off:.5f} "
            f"shaft_top_off={self._st_off:.5f} shaft_base_off={self._sb_off:.5f} "
            f"lat_admit={self._lat_admit:.5f} lift_gate={self._lift_gate:.5f} "
            f"target_progress={self.target_progress:.4f}"
        )
        self.progress_source = "aperture_rim_v3/z_only"

        self._first_print_done = False
        self._diag = {k: [] for k in (
            "state_trajs", "plug_pose_trajs", "socket_pose_trajs",
            "aperture_bottom_w_trajs", "shaft_top_w_trajs", "shaft_base_w_trajs",
            "lateral_dist_trajs", "progress_z_trajs", "gate_lat_trajs",
            "gate_lift_trajs", "progress_final_trajs",
        )}

    def _get_progress_venv(self, prev_obs_venv, info_venv=None):
        state_now = _latest_state(prev_obs_venv)
        if state_now is None:
            return np.full((self.n_envs,), np.nan, dtype=np.float32)
        last = state_now.shape[-1]
        if last < 14:
            return np.full((self.n_envs,), np.nan, dtype=np.float32)

        joint_dim = last - 14
        plug_pose = state_now[:, joint_dim : joint_dim + 7]   # (n, 7)
        socket_pose = state_now[:, joint_dim + 7 : joint_dim + 14]

        plug_z = plug_pose[:, 2]                              # (n,)
        plug_xy = plug_pose[:, 0:2]                           # (n, 2)
        sock_z = socket_pose[:, 2]
        sock_xy = socket_pose[:, 0:2]

        aperture_bot_w = plug_z + self._ap_off
        shaft_top_w    = sock_z + self._st_off
        shaft_base_w   = sock_z + self._sb_off

        lateral_dist = np.linalg.norm(plug_xy - sock_xy, axis=1)

        denom = shaft_top_w - shaft_base_w
        denom = np.where(denom > 1e-6, denom, 1e-6)
        penetration = shaft_top_w - aperture_bot_w
        progress_z = np.clip(penetration / denom, 0.0, 1.0)

        gate_lat = (lateral_dist <= self._lat_admit).astype(np.float64)

        # running max aperture bottom (lift gate)
        if self._running_max_apert is None or self._running_max_apert.shape[0] != aperture_bot_w.shape[0]:
            self._running_max_apert = np.copy(aperture_bot_w)
        else:
            self._running_max_apert = np.maximum(self._running_max_apert, aperture_bot_w)
        gate_lift = (self._running_max_apert >= self._lift_gate).astype(np.float64)

        progress_final = progress_z * gate_lat * gate_lift

        if not self._first_print_done:
            with np.printoptions(precision=5, suppress=True):
                print(
                    f"[APERTURE_RIM v3] first-step diagnostic:\n"
                    f"  target_progress    = {self.target_progress:.4f}\n"
                    f"  state.shape        = {state_now.shape}\n"
                    f"  plug_pose[0]       = {plug_pose[0]}\n"
                    f"  socket_pose[0]     = {socket_pose[0]}\n"
                    f"  aperture_bot_w[0]  = {float(aperture_bot_w[0]):+.5f} m\n"
                    f"  shaft_top_w[0]     = {float(shaft_top_w[0]):+.5f} m\n"
                    f"  shaft_base_w[0]    = {float(shaft_base_w[0]):+.5f} m\n"
                    f"  lateral_dist[0]    = {float(lateral_dist[0]):.5f} m  (admit={self._lat_admit:.5f})\n"
                    f"  progress_z[0]      = {float(progress_z[0]):.4f}\n"
                    f"  gate_lat[0]        = {float(gate_lat[0]):.0f}\n"
                    f"  gate_lift[0]       = {float(gate_lift[0]):.0f}\n"
                    f"  progress_final[0]  = {float(progress_final[0]):.4f}\n"
                    "  EXPECT for step 0:  progress_final = 0 (gate_lift=0 because nut not yet lifted)"
                )
            self._first_print_done = True

        # populate parent's slots for legacy result.npz fields
        self.last_dist = lateral_dist.astype(np.float32).copy()
        self.last_raw_progress = progress_z.astype(np.float32).copy()
        self.last_rel_pos = (plug_pose[:, :3] - socket_pose[:, :3]).astype(np.float32)

        # diag accumulation
        self._diag["state_trajs"].append(state_now.astype(np.float32).copy())
        self._diag["plug_pose_trajs"].append(plug_pose.astype(np.float32).copy())
        self._diag["socket_pose_trajs"].append(socket_pose.astype(np.float32).copy())
        self._diag["aperture_bottom_w_trajs"].append(aperture_bot_w.astype(np.float32).copy())
        self._diag["shaft_top_w_trajs"].append(shaft_top_w.astype(np.float32).copy())
        self._diag["shaft_base_w_trajs"].append(shaft_base_w.astype(np.float32).copy())
        self._diag["lateral_dist_trajs"].append(lateral_dist.astype(np.float32).copy())
        self._diag["progress_z_trajs"].append(progress_z.astype(np.float32).copy())
        self._diag["gate_lat_trajs"].append(gate_lat.astype(np.float32).copy())
        self._diag["gate_lift_trajs"].append(gate_lift.astype(np.float32).copy())
        self._diag["progress_final_trajs"].append(progress_final.astype(np.float32).copy())

        return progress_final.astype(np.float32)

    def run(self):
        for k in self._diag:
            self._diag[k] = []
        self._running_max_apert = None
        self._first_print_done = False

        super().run()

        rp = getattr(self, "result_path", None)
        if rp is None:
            return
        run_dir = os.path.dirname(rp)
        diag_path = os.path.join(run_dir, "aperture_rim_diag.npz")
        if len(self._diag["progress_final_trajs"]) == 0:
            return

        save_kwargs = {k: np.stack(v, axis=0) for k, v in self._diag.items()}
        save_kwargs.update({
            "aperture_bottom_offset_m": np.float32(self._ap_off),
            "shaft_top_offset_m":       np.float32(self._st_off),
            "shaft_base_offset_m":      np.float32(self._sb_off),
            "lateral_admit_m":          np.float32(self._lat_admit),
            "lift_gate_m":              np.float32(self._lift_gate),
            "target_progress":          np.float32(self.target_progress),
        })
        np.savez(diag_path, **save_kwargs)
        print(f"[APERTURE_RIM v3] saved diag npz: {diag_path}")
