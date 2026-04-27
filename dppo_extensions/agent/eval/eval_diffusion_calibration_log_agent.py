"""
eval_diffusion_calibration_log_agent.py — Phase 2 of the aperture-rim plan.

Subclasses EvalPCDiffusionStopAgent and adds raw trajectory logging for
offline aperture-rim calibration. Does NOT change progress logic.

Behavior:
  - Per step: records state_now, plug_pose, socket_pose, tactile_max
  - Prints plug_pose row 0 on the first step so we can verify state is RAW
    (meters/quaternion) vs normalized [-1, 1]  -- per rule 11.4.
  - Writes a SIBLING file calibration.npz next to result.npz at the end.
"""

import os
import logging

import numpy as np

from agent.eval.eval_diffusion_stop_agent import EvalPCDiffusionStopAgent

log = logging.getLogger(__name__)


def _latest_state_array(prev_obs_venv):
    if "state" not in prev_obs_venv:
        return None
    state = prev_obs_venv["state"]
    if state.ndim == 3:
        return np.asarray(state[:, -1, :], dtype=np.float32)
    if state.ndim == 2:
        return np.asarray(state, dtype=np.float32)
    raise ValueError(f"Unexpected state shape: {state.shape}")


def _tactile_max_array(prev_obs_venv, n_envs):
    if "tactile_points" not in prev_obs_venv:
        return np.zeros((n_envs,), dtype=np.float32)
    x = np.asarray(prev_obs_venv["tactile_points"])
    try:
        if x.ndim == 4:
            vals = x[:, -1, 3, :]
        elif x.ndim == 3:
            vals = x[:, 3, :]
        else:
            return np.zeros((n_envs,), dtype=np.float32)
        return np.nanmax(vals, axis=-1).astype(np.float32)
    except Exception:
        return np.zeros((n_envs,), dtype=np.float32)


class EvalPCDiffusionCalibrationLogAgent(EvalPCDiffusionStopAgent):
    """Calibration trajectory logger. Stop logic unchanged."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self._calib_state_trajs = None
        self._calib_plug_pose_trajs = None
        self._calib_socket_pose_trajs = None
        self._calib_tactile_max_trajs = None
        self._calib_step = 0
        self._calib_first_print_done = False
        self._calib_target_progress = float(self.target_progress)
        self._calib_disable_stop = bool(self.disable_stop_when_target_one)

    def _record_calib_step(self, prev_obs_venv):
        state_now = _latest_state_array(prev_obs_venv)
        if state_now is None:
            return
        n_envs = state_now.shape[0]
        last = state_now.shape[-1]
        if last < 14:
            log.warning(
                f"[CALIB] state last-dim={last} < 14; cannot parse plug/socket pose"
            )
            return

        joint_dim = last - 14
        plug_pose = state_now[:, joint_dim : joint_dim + 7].astype(np.float32)
        socket_pose = state_now[:, joint_dim + 7 : joint_dim + 14].astype(np.float32)
        tactile = _tactile_max_array(prev_obs_venv, n_envs)

        if not self._calib_first_print_done:
            with np.printoptions(precision=5, suppress=True):
                print(
                    "[CALIB] first step diagnostic "
                    "(rule 11.4 -- verify RAW vs normalized state):"
                )
                print(f"  state.shape           = {state_now.shape}")
                print(f"  joint_dim (state-14)  = {joint_dim}")
                print(f"  plug_pose[0]          = {plug_pose[0]}")
                print(f"  socket_pose[0]        = {socket_pose[0]}")
                print(f"  tactile_max[0]        = {float(tactile[0]):.4f}")
                print(
                    "  EXPECT for RAW: positions in meters (|xyz| <= ~0.5),"
                    " quaternion magnitudes near 1.0."
                )
                print(
                    "  EXPECT for NORMALIZED: positions in [-1, 1] regardless"
                    " of physical scale."
                )
            self._calib_first_print_done = True

        self._calib_state_trajs.append(state_now.copy())
        self._calib_plug_pose_trajs.append(plug_pose.copy())
        self._calib_socket_pose_trajs.append(socket_pose.copy())
        self._calib_tactile_max_trajs.append(tactile.copy())
        self._calib_step += 1

    def _get_progress_venv(self, prev_obs_venv, info_venv=None):
        if self._calib_state_trajs is None:
            self._calib_state_trajs = []
            self._calib_plug_pose_trajs = []
            self._calib_socket_pose_trajs = []
            self._calib_tactile_max_trajs = []
            self._calib_step = 0
            self._calib_first_print_done = False

        try:
            self._record_calib_step(prev_obs_venv)
        except Exception as exc:
            log.warning(f"[CALIB] failed to record this step: {exc}")

        return super()._get_progress_venv(prev_obs_venv, info_venv=info_venv)

    def run(self):
        self._calib_state_trajs = []
        self._calib_plug_pose_trajs = []
        self._calib_socket_pose_trajs = []
        self._calib_tactile_max_trajs = []
        self._calib_step = 0
        self._calib_first_print_done = False

        super().run()

        result_path = getattr(self, "result_path", None)
        if result_path is None:
            log.warning(
                "[CALIB] self.result_path not set on the agent; cannot save"
                " calibration.npz next to it"
            )
            return

        run_dir = os.path.dirname(result_path)
        calib_path = os.path.join(run_dir, "calibration.npz")

        n_steps = len(self._calib_state_trajs)
        if n_steps == 0:
            log.warning("[CALIB] no calibration steps were recorded; skipping save")
            return

        state_arr = np.stack(self._calib_state_trajs, axis=0)
        plug_arr = np.stack(self._calib_plug_pose_trajs, axis=0)
        socket_arr = np.stack(self._calib_socket_pose_trajs, axis=0)
        tactile_arr = np.stack(self._calib_tactile_max_trajs, axis=0)

        np.savez(
            calib_path,
            state_trajs=state_arr,
            plug_pose_trajs=plug_arr,
            socket_pose_trajs=socket_arr,
            tactile_max_trajs=tactile_arr,
            n_steps_recorded=np.int32(n_steps),
            target_progress=np.float32(self._calib_target_progress),
            disable_stop_when_target_one=np.bool_(self._calib_disable_stop),
            agent_class=np.array(self.__class__.__name__),
        )
        print(f"[CALIB] saved calibration trajectory: {calib_path}")
        print(f"[CALIB]   state_trajs.shape       = {state_arr.shape}")
        print(f"[CALIB]   plug_pose_trajs.shape   = {plug_arr.shape}")
        print(f"[CALIB]   socket_pose_trajs.shape = {socket_arr.shape}")
        print(f"[CALIB]   tactile_max_trajs.shape = {tactile_arr.shape}")
