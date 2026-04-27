#!/usr/bin/env python3
"""
analyze_aperture_rim_progress.py - Phase 3 v2 of the aperture-rim plan.

Same as v1 plus:
  - Computes d_signed anchor (first time |d_signed| crosses below a threshold,
    interpreted as 'aperture just touched shaft tip') and d_signed full
    (minimum of d_signed over the trajectory, interpreted as 'aperture has
    slid all the way down').
  - Reports a NEW progress definition based on this empirical [anchor, full]
    interval -- this is the variant Phase 4 should use, since it survives the
    sign + denom mismatch the geometric formula has at startup pose.
  - Writes anchor/full into the analysis JSON so Phase 4 agent can read them.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def quat_xyzw_to_matrix(q):
    q = np.asarray(q, dtype=np.float64)
    x = q[..., 0]; y = q[..., 1]; z = q[..., 2]; w = q[..., 3]
    n = np.sqrt(x * x + y * y + z * z + w * w)
    n = np.where(n > 1e-12, n, 1.0)
    x = x / n; y = y / n; z = z / n; w = w / n
    xx = x * x; yy = y * y; zz = z * z
    xy = x * y; xz = x * z; yz = y * z
    wx = w * x; wy = w * y; wz = w * z
    R = np.empty(q.shape[:-1] + (3, 3), dtype=np.float64)
    R[..., 0, 0] = 1.0 - 2.0 * (yy + zz)
    R[..., 0, 1] = 2.0 * (xy - wz)
    R[..., 0, 2] = 2.0 * (xz + wy)
    R[..., 1, 0] = 2.0 * (xy + wz)
    R[..., 1, 1] = 1.0 - 2.0 * (xx + zz)
    R[..., 1, 2] = 2.0 * (yz - wx)
    R[..., 2, 0] = 2.0 * (xz - wy)
    R[..., 2, 1] = 2.0 * (yz + wx)
    R[..., 2, 2] = 1.0 - 2.0 * (xx + yy)
    return R


def load_mesh_primitives(json_path):
    with open(json_path, "r") as f:
        prim = json.load(f)
    plug = prim["plug"]
    socket = prim["socket"]
    if not plug.get("ok", False):
        raise RuntimeError(f"plug primitives not ok: {plug.get('reason')}")
    if not socket.get("ok", False):
        raise RuntimeError(f"socket primitives not ok: {socket.get('reason')}")

    return {
        "asset_id": prim.get("asset_id"),
        "shaft_tip_local": np.asarray(plug["shaft_tip_local"], dtype=np.float64),
        "shaft_base_local": np.asarray(plug["shaft_base_local"], dtype=np.float64),
        "shaft_length_m": float(plug["shaft_length_m"]),
        "shaft_radius_threshold_m": float(plug["shaft_radius_threshold_m"]),
        "plug_body_axis_local_tip_to_base": np.asarray(
            plug["body_axis_local_tip_to_base"], dtype=np.float64
        ),
        "aperture_rim_local": np.asarray(socket["aperture_rim_local"], dtype=np.float64),
        "bore_back_local": np.asarray(socket["bore_back_local"], dtype=np.float64),
        "bore_length_m": float(socket["bore_length_m"]),
        "bore_axis_local_aperture_to_back": np.asarray(
            socket["bore_axis_local_aperture_to_back"], dtype=np.float64
        ),
    }


def compute_aperture_rim_progress(prim, plug_pose_t, socket_pose_t):
    plug_pose_t = np.asarray(plug_pose_t, dtype=np.float64)
    socket_pose_t = np.asarray(socket_pose_t, dtype=np.float64)

    plug_pos = plug_pose_t[:, :3]
    plug_quat = plug_pose_t[:, 3:7]
    socket_pos = socket_pose_t[:, :3]
    socket_quat = socket_pose_t[:, 3:7]

    Rp = quat_xyzw_to_matrix(plug_quat)
    Rs = quat_xyzw_to_matrix(socket_quat)

    shaft_tip_w = plug_pos + np.einsum("tij,j->ti", Rp, prim["shaft_tip_local"])
    aperture_w = socket_pos + np.einsum("tij,j->ti", Rs, prim["aperture_rim_local"])
    back_w = socket_pos + np.einsum("tij,j->ti", Rs, prim["bore_back_local"])

    u_raw = back_w - aperture_w
    u_norm = np.linalg.norm(u_raw, axis=-1, keepdims=True)
    u_norm = np.where(u_norm > 1e-9, u_norm, 1.0)
    u = u_raw / u_norm

    plug_body_w = np.einsum("tij,j->ti", Rp, prim["plug_body_axis_local_tip_to_base"])
    plug_body_norm = np.linalg.norm(plug_body_w, axis=-1, keepdims=True)
    plug_body_norm = np.where(plug_body_norm > 1e-9, plug_body_norm, 1.0)
    plug_body_unit = plug_body_w / plug_body_norm

    axis_alignment = -np.sum(plug_body_unit * u, axis=-1)

    delta = shaft_tip_w - aperture_w
    d_signed = np.sum(delta * u, axis=-1)

    lat_vec = delta - d_signed[:, None] * u
    lateral_dist = np.linalg.norm(lat_vec, axis=-1)

    return {
        "shaft_tip_world": shaft_tip_w,
        "aperture_world": aperture_w,
        "back_world": back_w,
        "u_world": u,
        "plug_body_world_unit": plug_body_unit,
        "axis_alignment": axis_alignment,
        "d_signed_m": d_signed,
        "lateral_dist_m": lateral_dist,
    }


def first_crossing(arr, threshold):
    idx = np.argmax(arr >= threshold)
    if arr[idx] >= threshold:
        return int(idx)
    return -1


def crossings_table(arr, thresholds=(0.05, 0.10, 0.25, 0.50, 0.75, 0.90)):
    return {f"first_ge_{t:.2f}": first_crossing(arr, t) for t in thresholds}


def separation_check(crossings, min_gap=3):
    pairs = [(0.10, 0.25), (0.25, 0.50), (0.50, 0.75)]
    gaps = {}
    bad = []
    for lo, hi in pairs:
        a = crossings.get(f"first_ge_{lo:.2f}", -1)
        b = crossings.get(f"first_ge_{hi:.2f}", -1)
        if a < 0 or b < 0:
            gaps[f"{lo:.2f}->{hi:.2f}"] = None
            bad.append(f"{lo:.2f}->{hi:.2f}: missing crossing")
            continue
        gap = b - a
        gaps[f"{lo:.2f}->{hi:.2f}"] = int(gap)
        if gap < min_gap:
            bad.append(f"{lo:.2f}->{hi:.2f}: gap={gap} steps < min_gap={min_gap}")
    return (len(bad) == 0), gaps, ("; ".join(bad) if bad else None)


def find_anchor_and_full(d_signed_t, lateral_t, lat_admit_m,
                         anchor_lateral_m=None, anchor_d_signed_eps=None):
    """Empirically find the (anchor, full) endpoints of the insertion interval.

    anchor = the d_signed value at the FIRST step where lateral_dist drops
             below `anchor_lateral_m` (lazy proxy for 'parts are aligned').
             If there is no such step, anchor = max(d_signed) (worst case).

    full   = the MINIMUM of d_signed over the trajectory restricted to the
             post-anchor region. This is 'how deep the policy actually
             managed to push'.

    These two are seed-specific (different seeds may align/insert differently),
    but the agent uses them as scale; what matters is that the interval is
    monotonic and large enough.
    """
    T = len(d_signed_t)
    if anchor_lateral_m is None:
        anchor_lateral_m = lat_admit_m  # default: same as lateral admission

    anchor_idx = -1
    for i in range(T):
        if lateral_t[i] <= anchor_lateral_m:
            anchor_idx = i
            break

    if anchor_idx < 0:
        anchor_d = float(d_signed_t.max())
        full_d = float(d_signed_t.min())
        anchor_idx = int(d_signed_t.argmax())
    else:
        anchor_d = float(d_signed_t[anchor_idx])
        full_d = float(d_signed_t[anchor_idx:].min())

    return {
        "anchor_idx": int(anchor_idx),
        "anchor_d_signed_m": float(anchor_d),
        "full_d_signed_m": float(full_d),
        "interval_m": float(anchor_d - full_d),
    }


def progress_from_calibrated_interval(d_signed_t, anchor_d, full_d):
    """Map d_signed -> progress in [0, 1] using the empirical anchor/full.

    progress = clip((anchor - d_signed) / (anchor - full), 0, 1)

    - At anchor (aperture just touched shaft tip): progress = 0
    - At full (aperture slid all the way down):    progress = 1
    """
    interval = max(anchor_d - full_d, 1e-6)
    return np.clip((anchor_d - d_signed_t) / interval, 0.0, 1.0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--mesh-json",
        default="/root/vt-refine/log/aperture_rim_calib/00581_mesh_primitives.json",
    )
    p.add_argument("--run-dir", required=True)
    p.add_argument("--env-idx", type=int, default=0)
    p.add_argument("--out-json", default=None)
    p.add_argument("--lateral-admission-m", type=float, default=None)
    p.add_argument("--tactile-min", type=float, default=0.02)
    p.add_argument("--min-gap", type=int, default=3)
    args = p.parse_args()

    run_dir = Path(args.run_dir)

    print(f"=== Phase 3 v2 aperture-rim analyzer ===")
    print(f"  mesh JSON:        {args.mesh_json}")
    calib_npz = run_dir / "calibration.npz"
    if not calib_npz.exists():
        raise FileNotFoundError(calib_npz)
    print(f"  calibration npz:  {calib_npz}")
    print()

    prim = load_mesh_primitives(args.mesh_json)
    print(f"  asset_id              = {prim['asset_id']}")
    print(f"  shaft_length_m        = {prim['shaft_length_m']:.5f}")
    print(f"  bore_length_m         = {prim['bore_length_m']:.5f}")
    print(f"  shaft_radius_thr_m    = {prim['shaft_radius_threshold_m']:.5f}")
    print()

    z = np.load(calib_npz, allow_pickle=True)
    plug_trajs = np.asarray(z["plug_pose_trajs"], dtype=np.float64)
    socket_trajs = np.asarray(z["socket_pose_trajs"], dtype=np.float64)
    tactile_trajs = np.asarray(z["tactile_max_trajs"], dtype=np.float64)

    plug_pose_t = plug_trajs[:, args.env_idx, :]
    socket_pose_t = socket_trajs[:, args.env_idx, :]
    tactile_t = tactile_trajs[:, args.env_idx]

    res = compute_aperture_rim_progress(prim, plug_pose_t, socket_pose_t)

    d_signed = res["d_signed_m"]
    lateral = res["lateral_dist_m"]
    align = res["axis_alignment"]

    if args.lateral_admission_m is None:
        lat_admit = 1.5 * prim["shaft_radius_threshold_m"]
    else:
        lat_admit = float(args.lateral_admission_m)

    print("=== Per-step diagnostics summary ===")
    print(f"  d_signed_m  min / max         = {d_signed.min():+.5f} / {d_signed.max():+.5f}")
    print(f"  lateral_dist_m  min / max     = {lateral.min():.5f} / {lateral.max():.5f}")
    print(f"  axis_alignment  min / max     = {align.min():+.4f} / {align.max():+.4f}")
    print(f"  tactile_max  min / max        = {tactile_t.min():.4f} / {tactile_t.max():.4f}")
    print(f"  lateral_admission used        = {lat_admit:.5f}")
    print()

    # ---------------- Calibrated-interval progress ---------------------
    af = find_anchor_and_full(d_signed, lateral, lat_admit)
    progress_cal = progress_from_calibrated_interval(
        d_signed, af["anchor_d_signed_m"], af["full_d_signed_m"]
    )
    print("=== Calibrated insertion interval (data-driven, seed-specific) ===")
    print(f"  anchor_idx (first lat_dist<=admit)  = {af['anchor_idx']}")
    print(f"  anchor_d_signed_m                   = {af['anchor_d_signed_m']:+.5f}")
    print(f"  full_d_signed_m  (min after anchor) = {af['full_d_signed_m']:+.5f}")
    print(f"  interval_m  (anchor - full)         = {af['interval_m']:.5f}")
    print(f"  progress_cal max                    = {progress_cal.max():.4f}"
          f"  (expected ~ shaft_length used over this seed)")
    print()

    # Also keep the legacy variants for comparison
    denom_geom = max(min(prim["shaft_length_m"], prim["bore_length_m"]), 1e-6)
    progress_raw = np.clip(d_signed / denom_geom, 0.0, 1.0)
    gate_lateral = lateral <= lat_admit
    gate_tactile = tactile_t >= float(args.tactile_min)
    progress_gated_lateral = progress_raw * gate_lateral.astype(np.float64)
    progress_gated_tactile = progress_raw * gate_tactile.astype(np.float64)
    progress_gated_both = progress_raw * gate_lateral.astype(np.float64) * gate_tactile.astype(np.float64)
    progress_cal_gated = progress_cal * gate_lateral.astype(np.float64)

    thresholds = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90)
    cross_raw = crossings_table(progress_raw, thresholds)
    cross_lat = crossings_table(progress_gated_lateral, thresholds)
    cross_tac = crossings_table(progress_gated_tactile, thresholds)
    cross_both = crossings_table(progress_gated_both, thresholds)
    cross_cal = crossings_table(progress_cal, thresholds)
    cross_cal_gated = crossings_table(progress_cal_gated, thresholds)

    def _print_crossings(label, table):
        print(f"  {label:32s}", end="")
        for t in thresholds:
            v = table[f"first_ge_{t:.2f}"]
            print(f"  >={t:.2f}@{v:>4d}", end="")
        print()

    print("=== First-crossing steps (-1 means never crossed) ===")
    _print_crossings("progress_raw (legacy)",       cross_raw)
    _print_crossings("progress_gated_lateral",      cross_lat)
    _print_crossings("progress_gated_tactile",      cross_tac)
    _print_crossings("progress_gated_both",         cross_both)
    _print_crossings("progress_cal (NEW)",          cross_cal)
    _print_crossings("progress_cal_gated_lateral",  cross_cal_gated)
    print()

    print("=== Phase 3 v2 separation acceptance ===")
    print(f"  (require min gap of {args.min_gap} steps between adjacent thresholds 0.10->0.25, 0.25->0.50, 0.50->0.75)")
    accept_results = {}
    for label, table in [
        ("progress_raw", cross_raw),
        ("progress_gated_lateral", cross_lat),
        ("progress_gated_tactile", cross_tac),
        ("progress_gated_both", cross_both),
        ("progress_cal", cross_cal),
        ("progress_cal_gated_lateral", cross_cal_gated),
    ]:
        ok, gaps, reason = separation_check(table, min_gap=args.min_gap)
        accept_results[label] = {"ok": bool(ok), "gaps": gaps, "reason": reason}
        print(f"  {label:32s}  ok={ok}   gaps={gaps}   {reason or ''}")
    print()

    out_path = (
        Path(args.out_json)
        if args.out_json is not None
        else run_dir / "aperture_rim_analysis.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asset_id": prim["asset_id"],
        "mesh_json": str(args.mesh_json),
        "run_dir": str(run_dir),
        "env_idx": int(args.env_idx),
        "n_steps": int(plug_pose_t.shape[0]),
        "lateral_admission_m": float(lat_admit),
        "tactile_min": float(args.tactile_min),
        "min_gap_steps": int(args.min_gap),
        "diag_summary": {
            "d_signed_m_min": float(d_signed.min()),
            "d_signed_m_max": float(d_signed.max()),
            "lateral_dist_m_min": float(lateral.min()),
            "lateral_dist_m_max": float(lateral.max()),
            "axis_alignment_min": float(align.min()),
            "axis_alignment_max": float(align.max()),
            "tactile_max_min": float(tactile_t.min()),
            "tactile_max_max": float(tactile_t.max()),
        },
        "calibrated_interval": af,
        "progress_cal_max": float(progress_cal.max()),
        "first_crossings": {
            "progress_raw": cross_raw,
            "progress_gated_lateral": cross_lat,
            "progress_gated_tactile": cross_tac,
            "progress_gated_both": cross_both,
            "progress_cal": cross_cal,
            "progress_cal_gated_lateral": cross_cal_gated,
        },
        "separation_acceptance": accept_results,
        "phase3_overall_accept_any": any(v["ok"] for v in accept_results.values()),
    }
    out_path.write_text(json.dumps(payload, indent=2, default=float))
    print(f"Saved analysis JSON: {out_path}")


if __name__ == "__main__":
    main()
