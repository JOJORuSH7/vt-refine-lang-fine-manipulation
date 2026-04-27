#!/usr/bin/env bash
# Natural language command -> Router -> target_progress -> Phase 4 demo
#
# Usage:
#   bash scripts/run_with_text_command.sh "insert a little bit"
#   bash scripts/run_with_text_command.sh "halfway"
#
# Env:
#   ROUTER_SEMANTIC_BACKEND=auto|embedding|offline  (default: auto)
#   SEED=41
#   ASSET=00581
#   CKPT=...
#   NORM=...

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 \"<natural language command>\"" >&2
    exit 2
fi

CMD="$1"

ASSET="${ASSET:-00581}"
CKPT="${CKPT:-/root/vt-refine/log/aloha-finetune/00581_0.01_ft_tactile_ta16_td100_tdf5/2026-04-25_18-51-11_42/checkpoint/state_100.pt}"
NORM="${NORM:-/root/vt-refine/data/aloha-00581/normalization.pth}"
SEED="${SEED:-41}"
N_STEPS="${N_STEPS:-240}"
ROUTER_SEMANTIC_BACKEND="${ROUTER_SEMANTIC_BACKEND:-auto}"

REPO=/root/vt-refine
cd "${REPO}"

# Step A: Route the text command -> target_progress
echo "==============================================================="
echo "  Step A: routing command via Day 9 Router"
echo "==============================================================="
echo "  user input:   '${CMD}'"
echo "  backend:      ${ROUTER_SEMANTIC_BACKEND}"

ROUTE_RESULT=$(
    ROUTER_SEMANTIC_BACKEND="${ROUTER_SEMANTIC_BACKEND}" \
    python3 -c "
from router.router import route_instruction
import json, sys
r = route_instruction(sys.argv[1])
print(json.dumps({'p_star': r.p_star, 'mode': r.mode, 'reason': r.reason, 'candidates': r.candidates}))
" "${CMD}"
)

TARGET_PROGRESS=$(echo "${ROUTE_RESULT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"p_star\"]:.4f}')")
ROUTE_MODE=$(echo "${ROUTE_RESULT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['mode'])")
ROUTE_REASON=$(echo "${ROUTE_RESULT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['reason'])")

echo "  ---> p_star      = ${TARGET_PROGRESS}"
echo "       mode        = ${ROUTE_MODE}"
echo "       reason      = ${ROUTE_REASON}"
echo ""

# Step B: Run Phase 4 v3 stop agent with that target_progress
TLABEL=$(python3 -c "print(f'{int(round(${TARGET_PROGRESS}*100)):03d}')")

CMD_SLUG=$(python3 -c "
import re, sys
s = sys.argv[1].lower()
s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
print(s[:48])
" "${CMD}")

NAME="${ASSET}_textcmd_${CMD_SLUG}_p${TLABEL}_seed${SEED}"
LOG="/tmp/textcmd_${CMD_SLUG}_p${TLABEL}.log"
FRAME_DIR="${REPO}/log/aperture_rim_frames/${ASSET}_textcmd/${CMD_SLUG}_p${TLABEL}"
DEMO_DIR="${REPO}/log/aperture_rim_demo_videos/${ASSET}_textcmd"
mkdir -p "${DEMO_DIR}"
OUT_MP4="${DEMO_DIR}/${CMD_SLUG}__p${TLABEL}__seed${SEED}.mp4"

echo "==============================================================="
echo "  Step B: running Phase 4 v3 stop agent"
echo "==============================================================="
echo "  target_progress = ${TARGET_PROGRESS}"
echo "  name            = ${NAME}"
echo "  output mp4      = ${OUT_MP4}"
echo ""

rm -rf "${FRAME_DIR}"; mkdir -p "${FRAME_DIR}"

export ALOHA_DEMO_CAMERA=1
export ALOHA_DEMO_FRAME_DIR="${FRAME_DIR}"
export ALOHA_DEMO_FRAME_EVERY=1
export ALOHA_DEMO_CAMERA_OFFSET="0.30,0.00,0.00"
export ALOHA_DEMO_CAMERA_TARGET_OFFSET="0.0,0.0,0.04"
export ALOHA_DEMO_CAMERA_WIDTH=640
export ALOHA_DEMO_CAMERA_HEIGHT=480
export ALOHA_DEMO_CAMERA_FOV=45
export DPPO_DATA_DIR="${DPPO_DATA_DIR:-/root/vt-refine/data}"
export DPPO_LOG_DIR="${DPPO_LOG_DIR:-/root/vt-refine/log}"
export DPPO_WANDB_ENTITY="${DPPO_WANDB_ENTITY:-local}"
export WANDB_MODE="${WANDB_MODE:-offline}"

python3 dppo/script/run.py \
    --config-name=eval_pre_tactile_stop \
    --config-path=../cfg/aloha/eval/${ASSET}_stop_probe \
    ++_target_=agent.eval.eval_diffusion_aperture_rim_stop_agent.EvalPCDiffusionApertureRimStopAgent \
    name="${NAME}" \
    base_policy_path="${CKPT}" \
    normalization_path="${NORM}" \
    env.specific.normalization_path="${NORM}" \
    env.specific.automate_asset_id="${ASSET}" \
    env.n_envs=1 \
    render_num=0 \
    ++env.save_video=false \
    seed="${SEED}" \
    act_steps=1 \
    plan_act_steps=8 \
    n_steps="${N_STEPS}" \
    target_progress="${TARGET_PROGRESS}" \
    disable_stop_when_target_one=true \
    hold_mode=current_joint_state \
    ++drive_mode=policy \
    2>&1 | tee "${LOG}"

unset ALOHA_DEMO_CAMERA ALOHA_DEMO_FRAME_DIR ALOHA_DEMO_FRAME_EVERY \
      ALOHA_DEMO_CAMERA_OFFSET ALOHA_DEMO_CAMERA_TARGET_OFFSET \
      ALOHA_DEMO_CAMERA_WIDTH ALOHA_DEMO_CAMERA_HEIGHT ALOHA_DEMO_CAMERA_FOV

N_FRAMES=$(ls "${FRAME_DIR}"/frame_*.png 2>/dev/null | wc -l || echo 0)
if [[ "${N_FRAMES}" -gt 10 ]]; then
    ffmpeg -y -loglevel error -framerate 12 -start_number 0 \
        -i "${FRAME_DIR}/frame_%06d.png" \
        -c:v libx264 -preset veryfast -pix_fmt yuv420p \
        "${OUT_MP4}"
    echo ""
    echo "==============================================================="
    echo "  Done."
    echo "    text command:  '${CMD}'"
    echo "    routed to:     p* = ${TARGET_PROGRESS}  (${ROUTE_MODE})"
    echo "    demo video:    ${OUT_MP4}"
    echo "    frames:        ${N_FRAMES}"
    echo "==============================================================="
else
    echo "[WARN] only ${N_FRAMES} frames produced; mp4 not encoded"
fi
