#!/usr/bin/env bash
# run_aperture_rim_pipeline.sh
# End-to-end pipeline: Phase 1 mesh inspection -> Phase 2 calibration ->
# Phase 3 offline analysis -> Phase 4 partial-stop runs at 25/50/75/100% with
# frame dump + ffmpeg encoding to mp4.

set -euo pipefail

if [[ $# -lt 3 ]]; then
    echo "Usage: $0 ASSET_ID CHECKPOINT_PATH NORMALIZATION_PATH" >&2
    exit 2
fi

ASSET_ID="$1"
CHECKPOINT="$2"
NORMALIZATION="$3"

SEED="${SEED:-41}"
N_STEPS_CALIB="${N_STEPS_CALIB:-240}"
N_STEPS_STOP="${N_STEPS_STOP:-240}"
TARGETS="${TARGETS:-0.25 0.50 0.75 1.00}"
FPS="${FPS:-12}"
CAM_OFFSET="${CAM_OFFSET:--0.32,0.00,0.028}"
CAM_TARGET="${CAM_TARGET:-0.0,0.0,0.033}"
CAM_W="${CAM_W:-640}"
CAM_H="${CAM_H:-480}"
CAM_FOV="${CAM_FOV:-45}"
FRAME_EVERY="${FRAME_EVERY:-1}"
SKIP_PHASE1="${SKIP_PHASE1:-0}"
SKIP_PHASE2="${SKIP_PHASE2:-0}"
SKIP_PHASE3="${SKIP_PHASE3:-0}"
SKIP_PHASE4="${SKIP_PHASE4:-0}"

REPO="/root/vt-refine"
MESH_JSON="${REPO}/log/aperture_rim_calib/${ASSET_ID}_mesh_primitives.json"
CALIB_NAME="${ASSET_ID}_calib_seed${SEED}_nostop_${N_STEPS_CALIB}"
DEMO_VIDEO_DIR="${REPO}/log/aperture_rim_demo_videos/${ASSET_ID}"

mkdir -p "${DEMO_VIDEO_DIR}"

cd "${REPO}"

export DPPO_DATA_DIR="${DPPO_DATA_DIR:-${REPO}/data}"
export DPPO_LOG_DIR="${DPPO_LOG_DIR:-${REPO}/log}"
export DPPO_WANDB_ENTITY="${DPPO_WANDB_ENTITY:-local}"
export WANDB_MODE="${WANDB_MODE:-offline}"
export ALOHA_DEMO_CAMERA="${ALOHA_DEMO_CAMERA:-1}"

banner() {
    echo
    echo "================================================================="
    echo "  $*"
    echo "================================================================="
}

extract_run_dir() {
    local log_file="$1"
    local name_pattern="$2"
    grep -oE "${REPO}/log/aloha-eval/${name_pattern}/[0-9_-]+_${SEED}" "${log_file}" \
        | tail -1
}

if [[ "${SKIP_PHASE1}" != "1" ]]; then
    banner "Phase 1: mesh inspection for asset ${ASSET_ID}"
    LOG_P1="/tmp/aperture_rim_phase1_${ASSET_ID}.log"
    python3 dppo/scripts/inspect_aperture_rim_mesh.py --asset "${ASSET_ID}" 2>&1 \
        | tee "${LOG_P1}"

    if [[ ! -f "${MESH_JSON}" ]]; then
        echo "[ERROR] Phase 1 did not produce ${MESH_JSON}" >&2
        exit 3
    fi

    python3 - <<PYACCEPT
import json
with open("${MESH_JSON}") as f:
    d = json.load(f)
acc = d.get("phase1_acceptance", {})
ok = all(acc.values())
print()
print("=== Phase 1 acceptance gate ===")
for k, v in acc.items():
    print(f"  {k}: {v}")
print(f"  OVERALL: {ok}")
if not ok:
    raise SystemExit(
        "Phase 1 acceptance NOT met. Refer to the WARNING block in the log "
        "and consider switching Phase 4 to a raycast-into-mesh design."
    )
PYACCEPT
fi

CALIB_LOG="/tmp/aperture_rim_phase2_${ASSET_ID}.log"
if [[ "${SKIP_PHASE2}" != "1" ]]; then
    banner "Phase 2: calibration trajectory for asset ${ASSET_ID} (seed=${SEED})"

    python3 dppo/script/run.py \
        --config-name=eval_pre_tactile_stop \
        --config-path=../cfg/aloha/eval/${ASSET_ID}_stop_probe \
        ++_target_=agent.eval.eval_diffusion_calibration_log_agent.EvalPCDiffusionCalibrationLogAgent \
        name="${CALIB_NAME}" \
        base_policy_path="${CHECKPOINT}" \
        normalization_path="${NORMALIZATION}" \
        env.specific.normalization_path="${NORMALIZATION}" \
        env.specific.automate_asset_id="${ASSET_ID}" \
        env.n_envs=1 \
        render_num=0 \
        ++env.save_video=false \
        seed="${SEED}" \
        act_steps=1 \
        plan_act_steps=8 \
        n_steps="${N_STEPS_CALIB}" \
        target_progress=1.0 \
        disable_stop_when_target_one=true \
        hold_mode=current_joint_state \
        ++drive_mode=policy \
        2>&1 | tee "${CALIB_LOG}"
fi

CALIB_RUN_DIR=$(extract_run_dir "${CALIB_LOG}" "${CALIB_NAME}" || true)
if [[ -z "${CALIB_RUN_DIR}" || ! -d "${CALIB_RUN_DIR}" ]]; then
    CALIB_RUN_DIR=$(ls -dt "${REPO}/log/aloha-eval/${CALIB_NAME}"/*/ 2>/dev/null | head -1 | sed 's:/$::')
fi
if [[ -z "${CALIB_RUN_DIR}" || ! -f "${CALIB_RUN_DIR}/calibration.npz" ]]; then
    echo "[ERROR] Phase 2 did not produce a calibration.npz under ${CALIB_RUN_DIR}" >&2
    exit 4
fi
echo "[INFO] Phase 2 run dir: ${CALIB_RUN_DIR}"

ANALYSIS_JSON="${CALIB_RUN_DIR}/aperture_rim_analysis.json"
if [[ "${SKIP_PHASE3}" != "1" ]]; then
    banner "Phase 3: offline aperture-rim analysis"
    python3 dppo/scripts/analyze_aperture_rim_progress.py \
        --mesh-json "${MESH_JSON}" \
        --run-dir   "${CALIB_RUN_DIR}" \
        --out-json  "${ANALYSIS_JSON}" \
        2>&1 | tee "/tmp/aperture_rim_phase3_${ASSET_ID}.log"
fi
if [[ ! -f "${ANALYSIS_JSON}" ]]; then
    echo "[ERROR] Phase 3 did not produce ${ANALYSIS_JSON}" >&2
    exit 5
fi

python3 - <<PYREPORT
import json
with open("${ANALYSIS_JSON}") as f:
    a = json.load(f)
sep = a.get("separation_acceptance", {})
print()
print("=== Phase 3 separation acceptance summary ===")
for k, v in sep.items():
    print(f"  {k:32s}  ok={v.get('ok')}  gaps={v.get('gaps')}")
print(f"  overall_accept_any: {a.get('phase3_overall_accept_any')}")
PYREPORT

if [[ "${SKIP_PHASE4}" != "1" ]]; then
    for T in ${TARGETS}; do
        TLABEL=$(python3 -c "print(f'{int(round(float(${T})*100)):03d}')")
        STOP_NAME="${ASSET_ID}_aperture_rim_p${TLABEL}_seed${SEED}"
        STOP_LOG="/tmp/aperture_rim_phase4_${ASSET_ID}_p${TLABEL}.log"
        FRAME_DIR="${REPO}/log/aperture_rim_frames/${ASSET_ID}/p${TLABEL}_seed${SEED}"

        banner "Phase 4: target_progress=${T}  (label=p${TLABEL})  asset=${ASSET_ID}"

        rm -rf "${FRAME_DIR}"
        mkdir -p "${FRAME_DIR}"
        export ALOHA_DEMO_FRAME_DIR="${FRAME_DIR}"
        export ALOHA_DEMO_FRAME_EVERY="${FRAME_EVERY}"
        export ALOHA_DEMO_CAMERA_OFFSET="${CAM_OFFSET}"
        export ALOHA_DEMO_CAMERA_TARGET_OFFSET="${CAM_TARGET}"
        export ALOHA_DEMO_CAMERA_WIDTH="${CAM_W}"
        export ALOHA_DEMO_CAMERA_HEIGHT="${CAM_H}"
        export ALOHA_DEMO_CAMERA_FOV="${CAM_FOV}"

        python3 dppo/script/run.py \
            --config-name=eval_pre_tactile_stop \
            --config-path=../cfg/aloha/eval/${ASSET_ID}_stop_probe \
            ++_target_=agent.eval.eval_diffusion_aperture_rim_stop_agent.EvalPCDiffusionApertureRimStopAgent \
            name="${STOP_NAME}" \
            base_policy_path="${CHECKPOINT}" \
            normalization_path="${NORMALIZATION}" \
            env.specific.normalization_path="${NORMALIZATION}" \
            env.specific.automate_asset_id="${ASSET_ID}" \
            env.n_envs=1 \
            render_num=0 \
            ++env.save_video=false \
            seed="${SEED}" \
            act_steps=1 \
            plan_act_steps=8 \
            n_steps="${N_STEPS_STOP}" \
            target_progress="${T}" \
            disable_stop_when_target_one=true \
            hold_mode=current_joint_state \
            ++drive_mode=policy \
            +mesh_primitives_path="${MESH_JSON}" \
            +analysis_path="${ANALYSIS_JSON}" \
            2>&1 | tee "${STOP_LOG}"

        unset ALOHA_DEMO_FRAME_DIR
        unset ALOHA_DEMO_FRAME_EVERY
        unset ALOHA_DEMO_CAMERA_OFFSET
        unset ALOHA_DEMO_CAMERA_TARGET_OFFSET
        unset ALOHA_DEMO_CAMERA_WIDTH
        unset ALOHA_DEMO_CAMERA_HEIGHT
        unset ALOHA_DEMO_CAMERA_FOV

        STOP_RUN_DIR=$(extract_run_dir "${STOP_LOG}" "${STOP_NAME}" || true)
        if [[ -z "${STOP_RUN_DIR}" ]]; then
            STOP_RUN_DIR=$(ls -dt "${REPO}/log/aloha-eval/${STOP_NAME}"/*/ 2>/dev/null | head -1 | sed 's:/$::')
        fi
        echo "[INFO] Phase 4 (p${TLABEL}) run dir: ${STOP_RUN_DIR}"

        N_FRAMES=$(ls "${FRAME_DIR}"/frame_*.png 2>/dev/null | wc -l || echo 0)
        if [[ "${N_FRAMES}" -gt 10 ]]; then
            OUT_MP4="${DEMO_VIDEO_DIR}/p${TLABEL}_seed${SEED}.mp4"
            ffmpeg -y -framerate "${FPS}" -start_number 0 \
                -i "${FRAME_DIR}/frame_%06d.png" \
                -c:v libx264 -pix_fmt yuv420p \
                "${OUT_MP4}" 2> "/tmp/ffmpeg_${ASSET_ID}_p${TLABEL}.log" \
                && echo "[INFO] wrote ${OUT_MP4} (${N_FRAMES} frames @ ${FPS}fps)" \
                || echo "[WARN] ffmpeg failed; see /tmp/ffmpeg_${ASSET_ID}_p${TLABEL}.log"
        else
            echo "[WARN] only ${N_FRAMES} frames in ${FRAME_DIR}; skipping mp4 encode"
        fi
    done
fi

banner "Pipeline complete for ${ASSET_ID}"
echo "Phase 1 mesh JSON:    ${MESH_JSON}"
echo "Phase 2 calibration:  ${CALIB_RUN_DIR}/calibration.npz"
echo "Phase 3 analysis:     ${ANALYSIS_JSON}"
echo "Phase 4 demo videos:  ${DEMO_VIDEO_DIR}/"
ls -la "${DEMO_VIDEO_DIR}/" 2>/dev/null || true
