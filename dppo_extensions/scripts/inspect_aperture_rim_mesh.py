#!/usr/bin/env python3
"""
inspect_aperture_rim_mesh.py — Phase 1 v2 of the aperture-rim plan.

Standalone, zero-simulation. Reads URDF + OBJ, applies URDF mesh scale, and
identifies plug shaft + socket bore + aperture rim primitives empirically
(NOT via np.argmax(extents), which is the bug in the previous leading-rim
agent on 00581: anisotropic plug scale (2.6, 2.6, 3.0) makes the hex-base
width in local X exceed the cylinder length in local Z, so argmax picks the
wrong axis).

Output:
  /root/vt-refine/log/aperture_rim_calib/<asset>_mesh_primitives.json
"""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def _tag_name(tag):
    return str(tag).split("}")[-1]


def _parse_scale(text, default=(1.0, 1.0, 1.0)):
    if text is None or str(text).strip() == "":
        return np.asarray(default, dtype=np.float64)
    vals = [float(v) for v in str(text).replace(",", " ").split()]
    if len(vals) == 1:
        return np.asarray([vals[0]] * 3, dtype=np.float64)
    if len(vals) == 3:
        return np.asarray(vals, dtype=np.float64)
    raise ValueError(f"Bad scale string: {text!r}")


def _candidate_mesh_paths(filename, urdf_path):
    raw = Path(filename)
    cleaned = filename.replace("../", "").lstrip("./").lstrip("/")
    base = urdf_path.parent
    automate = base.parent
    cands = [
        raw,
        base / filename,
        automate / cleaned,
        automate / "mesh" / raw.name,
        automate / "meshes" / raw.name,
    ]
    out, seen = [], set()
    for c in cands:
        try:
            cr = c.resolve()
        except Exception:
            cr = c
        if str(cr) not in seen:
            seen.add(str(cr))
            out.append(cr)
    return out


def _load_obj_vertices(mesh_path):
    verts = []
    with open(mesh_path, "r") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
                    except ValueError:
                        continue
    if not verts:
        raise RuntimeError(f"No 'v' lines in {mesh_path}")
    return np.asarray(verts, dtype=np.float64)


def load_urdf_vertices_scaled(urdf_path):
    urdf_path = Path(urdf_path)
    if not urdf_path.exists():
        raise FileNotFoundError(urdf_path)

    tree = ET.parse(str(urdf_path))
    root = tree.getroot()

    all_v = []
    records = []
    seen_files = set()

    for elem in root.iter():
        if _tag_name(elem.tag) != "mesh":
            continue
        filename = elem.attrib.get("filename") or elem.attrib.get("url")
        if not filename:
            continue
        scale = _parse_scale(elem.attrib.get("scale"))
        if filename in seen_files:
            continue
        seen_files.add(filename)

        found = None
        for cand in _candidate_mesh_paths(filename, urdf_path):
            if cand.exists():
                found = cand
                break
        if found is None:
            records.append({"filename": filename, "found": None, "scale": scale.tolist()})
            continue

        v = _load_obj_vertices(found)
        v_scaled = v * scale[None, :]
        all_v.append(v_scaled)
        records.append({
            "filename": filename,
            "found": str(found),
            "scale": scale.tolist(),
            "n": int(len(v)),
            "raw_xyz_min": v.min(0).tolist(),
            "raw_xyz_max": v.max(0).tolist(),
            "scaled_xyz_min": v_scaled.min(0).tolist(),
            "scaled_xyz_max": v_scaled.max(0).tolist(),
        })

    if not all_v:
        raise RuntimeError(f"No vertices loaded from {urdf_path}; records={records}")

    V = np.concatenate(all_v, axis=0)
    V = np.unique(V, axis=0)
    return V, records


def axial_radial(verts, axis_idx):
    axial = verts[:, axis_idx]
    other = [i for i in range(3) if i != axis_idx]
    med = np.median(verts[:, other], axis=0)
    dx = verts[:, other[0]] - med[0]
    dy = verts[:, other[1]] - med[1]
    radial = np.sqrt(dx * dx + dy * dy)
    return axial, radial, med


def cylinder_score(verts, axis_idx, inner_q=0.30):
    axial, r, med = axial_radial(verts, axis_idx)
    extent = float(axial.max() - axial.min())

    r_thresh = float(np.quantile(r, inner_q))
    inner_mask = r <= r_thresh + 1e-12
    n_inner = int(inner_mask.sum())
    if n_inner < 5:
        return {
            "axis_idx": axis_idx, "extent": extent, "n_inner": n_inner,
            "r_thresh_q30": r_thresh, "inner_r_mean": float("nan"),
            "inner_r_std": float("nan"), "rel_std": float("inf"),
            "inner_axial_extent": 0.0, "score": -float("inf"),
            "perp_center": med.tolist(),
        }

    inner_r = r[inner_mask]
    inner_axial = axial[inner_mask]
    inner_r_mean = float(inner_r.mean())
    inner_r_std = float(inner_r.std())
    rel_std = inner_r_std / max(inner_r_mean, 1e-9)
    inner_axial_extent = float(inner_axial.max() - inner_axial.min())

    score = inner_axial_extent / (rel_std + 0.05)

    return {
        "axis_idx": axis_idx, "extent": extent, "n_inner": n_inner,
        "r_thresh_q30": r_thresh, "inner_r_mean": inner_r_mean,
        "inner_r_std": inner_r_std, "rel_std": rel_std,
        "inner_axial_extent": inner_axial_extent, "score": float(score),
        "perp_center": med.tolist(),
    }


def inspect_plug(verts):
    scores = [cylinder_score(verts, i) for i in range(3)]
    best = max(scores, key=lambda s: s["score"])
    body_axis = int(best["axis_idx"])

    axial, r, perp_center = axial_radial(verts, body_axis)

    shaft_r_thresh = best["inner_r_mean"] + 1.0 * best["inner_r_std"] + 1e-4
    shaft_mask = r <= shaft_r_thresh
    n_shaft = int(shaft_mask.sum())
    if n_shaft < 5:
        return {
            "ok": False, "reason": "shaft_mask_too_small",
            "axis_scores": scores, "body_axis_idx": body_axis,
            "shaft_radius_threshold_m": float(shaft_r_thresh),
            "shaft_n_vertices": n_shaft,
            "perp_center_local": perp_center.tolist(),
        }

    shaft_axial = axial[shaft_mask]
    shaft_r = r[shaft_mask]
    s_min = float(shaft_axial.min())
    s_max = float(shaft_axial.max())
    s_len = s_max - s_min

    eps = max(0.05 * s_len, 1e-4)
    near_min = (shaft_axial - s_min) <= eps
    near_max = (s_max - shaft_axial) <= eps
    r_at_min = float(shaft_r[near_min].mean()) if near_min.sum() > 0 else float("inf")
    r_at_max = float(shaft_r[near_max].mean()) if near_max.sum() > 0 else float("inf")

    if r_at_min <= r_at_max:
        tip_axial = s_min
        base_axial = s_max
        tip_at_low = True
    else:
        tip_axial = s_max
        base_axial = s_min
        tip_at_low = False

    tip_local = [0.0, 0.0, 0.0]
    base_local = [0.0, 0.0, 0.0]
    other = [i for i in range(3) if i != body_axis]
    tip_local[other[0]] = float(perp_center[0])
    tip_local[other[1]] = float(perp_center[1])
    tip_local[body_axis] = float(tip_axial)
    base_local[other[0]] = float(perp_center[0])
    base_local[other[1]] = float(perp_center[1])
    base_local[body_axis] = float(base_axial)

    body_axis_local = [0.0, 0.0, 0.0]
    body_axis_local[body_axis] = 1.0 if tip_at_low else -1.0

    return {
        "ok": True,
        "axis_scores": scores,
        "body_axis_idx": body_axis,
        "body_axis_local_tip_to_base": body_axis_local,
        "perp_center_local": perp_center.tolist(),
        "shaft_radius_threshold_m": float(shaft_r_thresh),
        "shaft_axial_min_local": s_min,
        "shaft_axial_max_local": s_max,
        "shaft_length_m": float(s_len),
        "shaft_n_vertices": n_shaft,
        "shaft_total_vertices": int(verts.shape[0]),
        "shaft_tip_local": tip_local,
        "shaft_base_local": base_local,
        "tip_at_low_axial": bool(tip_at_low),
        "r_at_low_end": r_at_min,
        "r_at_high_end": r_at_max,
    }


def inspect_socket(verts, plug_shaft_radius=None):
    scores = [cylinder_score(verts, i) for i in range(3)]
    best = max(scores, key=lambda s: s["score"])
    bore_axis = int(best["axis_idx"])

    axial, r, perp_center = axial_radial(verts, bore_axis)

    _ = plug_shaft_radius  # accepted for API stability, not used (see comment)
    q30_thresh = best["inner_r_mean"] + 1.0 * best["inner_r_std"] + 1e-4
    bore_r_thresh = q30_thresh
    bore_mask = r <= bore_r_thresh

    n_bore = int(bore_mask.sum())
    if n_bore < 5:
        return {
            "ok": False, "reason": "bore_mask_too_small",
            "axis_scores": scores, "bore_axis_idx": bore_axis,
            "bore_radius_threshold_m": float(bore_r_thresh),
            "bore_n_vertices": n_bore,
            "perp_center_local": perp_center.tolist(),
        }

    bore_axial = axial[bore_mask]
    b_min = float(bore_axial.min())
    b_max = float(bore_axial.max())
    b_len = b_max - b_min

    eps = max(0.05 * b_len, 1e-4)
    outer_mask = ~bore_mask
    outer_axial = axial[outer_mask]
    if len(outer_axial) > 0:
        n_outer_near_low = int(np.sum(np.abs(outer_axial - b_min) <= eps * 3))
        n_outer_near_high = int(np.sum(np.abs(outer_axial - b_max) <= eps * 3))
    else:
        n_outer_near_low = 0
        n_outer_near_high = 0

    if n_outer_near_low <= n_outer_near_high:
        ap_axial = b_min
        back_axial = b_max
        aperture_at_low = True
    else:
        ap_axial = b_max
        back_axial = b_min
        aperture_at_low = False

    other = [i for i in range(3) if i != bore_axis]
    aperture_local = [0.0, 0.0, 0.0]
    back_local = [0.0, 0.0, 0.0]
    aperture_local[other[0]] = float(perp_center[0])
    aperture_local[other[1]] = float(perp_center[1])
    aperture_local[bore_axis] = float(ap_axial)
    back_local[other[0]] = float(perp_center[0])
    back_local[other[1]] = float(perp_center[1])
    back_local[bore_axis] = float(back_axial)

    bore_axis_local_aperture_to_back = [0.0, 0.0, 0.0]
    bore_axis_local_aperture_to_back[bore_axis] = (
        1.0 if aperture_at_low else -1.0
    )

    return {
        "ok": True,
        "axis_scores": scores,
        "bore_axis_idx": bore_axis,
        "bore_axis_local_aperture_to_back": bore_axis_local_aperture_to_back,
        "perp_center_local": perp_center.tolist(),
        "bore_radius_threshold_m": float(bore_r_thresh),
        "bore_axial_min_local": b_min,
        "bore_axial_max_local": b_max,
        "bore_length_m": float(b_len),
        "bore_n_vertices": n_bore,
        "bore_total_vertices": int(verts.shape[0]),
        "n_outer_near_low_axial": n_outer_near_low,
        "n_outer_near_high_axial": n_outer_near_high,
        "aperture_rim_local": aperture_local,
        "bore_back_local": back_local,
        "aperture_at_low_axial": bool(aperture_at_low),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asset", default="00581")
    p.add_argument(
        "--urdf-dir",
        default="/root/vt-refine/easysim-envs/src/easysim_envs/assets/automate_scaled/urdf",
    )
    p.add_argument(
        "--out-dir",
        default="/root/vt-refine/log/aperture_rim_calib",
    )
    args = p.parse_args()

    urdf_dir = Path(args.urdf_dir)
    plug_urdf = urdf_dir / f"{args.asset}_plug.urdf"
    socket_urdf = urdf_dir / f"{args.asset}_socket.urdf"

    print(f"=== Aperture-rim mesh inspection for asset {args.asset} ===")
    print(f"plug_urdf:   {plug_urdf}  exists={plug_urdf.exists()}")
    print(f"socket_urdf: {socket_urdf}  exists={socket_urdf.exists()}")
    print()

    plug_v, plug_records = load_urdf_vertices_scaled(plug_urdf)
    socket_v, socket_records = load_urdf_vertices_scaled(socket_urdf)

    plug_extents = (plug_v.max(0) - plug_v.min(0)).tolist()
    socket_extents = (socket_v.max(0) - socket_v.min(0)).tolist()

    print(f"[plug]   n_vertices_unique={len(plug_v)}")
    for rec in plug_records:
        print(f"  record: {rec}")
    print(f"[plug]   scaled_extents (X, Y, Z) = "
          f"{[f'{x:.5f}' for x in plug_extents]}")
    print()
    print(f"[socket] n_vertices_unique={len(socket_v)}")
    for rec in socket_records:
        print(f"  record: {rec}")
    print(f"[socket] scaled_extents (X, Y, Z) = "
          f"{[f'{x:.5f}' for x in socket_extents]}")
    print()

    print("=== Plug analysis ===")
    plug_info = inspect_plug(plug_v)
    print(f"  body_axis_idx (winning cylinder axis) = {plug_info.get('body_axis_idx')}")
    print(f"  axis_scores (compare to argmax-extent which was the bug):")
    for s in plug_info["axis_scores"]:
        print(f"    axis={s['axis_idx']}  total_extent={s['extent']:.5f}  "
              f"inner_axial_extent={s['inner_axial_extent']:.5f}  "
              f"n_inner={s['n_inner']}  inner_r_mean={s['inner_r_mean']:.5f}  "
              f"inner_r_std={s['inner_r_std']:.5f}  rel_std={s['rel_std']:.4f}  "
              f"score={s['score']:.3f}")
    if plug_info["ok"]:
        print(f"  shaft_length_m   = {plug_info['shaft_length_m']:.5f}")
        print(f"  shaft_radius_thr = {plug_info['shaft_radius_threshold_m']:.5f}")
        print(f"  shaft_n_vertices = {plug_info['shaft_n_vertices']} / "
              f"{plug_info['shaft_total_vertices']}")
        print(f"  shaft_tip_local  = {plug_info['shaft_tip_local']}")
        print(f"  shaft_base_local = {plug_info['shaft_base_local']}")
        print(f"  tip_at_low_axial = {plug_info['tip_at_low_axial']}")
        print(f"  body_axis_tip_to_base = {plug_info['body_axis_local_tip_to_base']}")
        print(f"  r_at_low_end={plug_info['r_at_low_end']:.5f}  "
              f"r_at_high_end={plug_info['r_at_high_end']:.5f}")
    else:
        print(f"  PLUG SHAFT NOT IDENTIFIED: {plug_info.get('reason')}")
    print()

    print("=== Socket analysis ===")
    plug_shaft_r = (
        plug_info["shaft_radius_threshold_m"] if plug_info.get("ok") else None
    )
    socket_info = inspect_socket(socket_v, plug_shaft_radius=plug_shaft_r)
    print(f"  bore_axis_idx (winning cylinder axis) = {socket_info.get('bore_axis_idx')}")
    print(f"  axis_scores:")
    for s in socket_info["axis_scores"]:
        print(f"    axis={s['axis_idx']}  total_extent={s['extent']:.5f}  "
              f"inner_axial_extent={s['inner_axial_extent']:.5f}  "
              f"n_inner={s['n_inner']}  inner_r_mean={s['inner_r_mean']:.5f}  "
              f"inner_r_std={s['inner_r_std']:.5f}  rel_std={s['rel_std']:.4f}  "
              f"score={s['score']:.3f}")
    if socket_info["ok"]:
        print(f"  bore_length_m      = {socket_info['bore_length_m']:.5f}")
        print(f"  bore_radius_thr    = {socket_info['bore_radius_threshold_m']:.5f}")
        print(f"  bore_n_vertices    = {socket_info['bore_n_vertices']} / "
              f"{socket_info['bore_total_vertices']}")
        print(f"  aperture_rim_local = {socket_info['aperture_rim_local']}")
        print(f"  bore_back_local    = {socket_info['bore_back_local']}")
        print(f"  aperture_at_low    = {socket_info['aperture_at_low_axial']}")
        print(f"  bore_axis_aperture_to_back = {socket_info['bore_axis_local_aperture_to_back']}")
        print(f"  n_outer_near_low={socket_info['n_outer_near_low_axial']}  "
              f"n_outer_near_high={socket_info['n_outer_near_high_axial']}")
    else:
        print(f"  SOCKET BORE NOT IDENTIFIED: {socket_info.get('reason')}")
    print()

    plug_ok = (
        plug_info.get("ok", False)
        and plug_info.get("shaft_length_m", 0.0) > 0.005
        and plug_info.get("shaft_n_vertices", 0) >= 50
    )
    socket_ok = (
        socket_info.get("ok", False)
        and socket_info.get("bore_length_m", 0.0) > 0.005
        and socket_info.get("bore_n_vertices", 0) >= 50
        and socket_info.get("bore_n_vertices", 0)
            < socket_info.get("bore_total_vertices", 1)
    )
    aperture_unambiguous = (
        socket_info.get("ok", False)
        and abs(
            socket_info.get("n_outer_near_low_axial", 0)
            - socket_info.get("n_outer_near_high_axial", 0)
        ) >= 5
    )
    print("=== Phase 1 v2 acceptance flags ===")
    print(f"  plug_shaft_identified (length>0.005m & n>=50): {plug_ok}")
    print(f"  socket_bore_identified (n>=50 & n<total)     : {socket_ok}")
    print(f"  aperture_unambiguous (|n_low-n_high|>=5)     : {aperture_unambiguous}")
    print(f"  argmax_extent_axis (the buggy old choice)    : "
          f"plug={int(np.argmax(plug_extents))}  socket={int(np.argmax(socket_extents))}")
    print(f"  cylinder_fit_axis (the new choice)           : "
          f"plug={plug_info.get('body_axis_idx')}  socket={socket_info.get('bore_axis_idx')}")
    print()

    payload = {
        "asset_id": args.asset,
        "plug_urdf": str(plug_urdf),
        "socket_urdf": str(socket_urdf),
        "plug_records": plug_records,
        "socket_records": socket_records,
        "plug_n_vertices_unique": int(len(plug_v)),
        "socket_n_vertices_unique": int(len(socket_v)),
        "plug_scaled_extents_xyz": plug_extents,
        "socket_scaled_extents_xyz": socket_extents,
        "argmax_extent_axis_plug": int(np.argmax(plug_extents)),
        "argmax_extent_axis_socket": int(np.argmax(socket_extents)),
        "plug": plug_info,
        "socket": socket_info,
        "phase1_acceptance": {
            "plug_shaft_identified": bool(plug_ok),
            "socket_bore_identified": bool(socket_ok),
            "aperture_unambiguous": bool(aperture_unambiguous),
        },
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{args.asset}_mesh_primitives.json"
    out_json.write_text(json.dumps(payload, indent=2, default=float))
    print(f"Saved JSON: {out_json}")

    if not (plug_ok and socket_ok and aperture_unambiguous):
        print()
        print("WARNING: Phase 1 v2 acceptance not met. Do NOT proceed to Phase 2/3/4")
        print("with this vertex-mask plan -- the geometry is not cleanly cylindrical")
        print("or aperture-end is ambiguous. Switch the Phase 4 design to")
        print("raycast-into-mesh instead.")


if __name__ == "__main__":
    main()
