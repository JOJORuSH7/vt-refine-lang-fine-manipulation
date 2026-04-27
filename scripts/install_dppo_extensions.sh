#!/bin/bash
# =====================================================================
# install_dppo_extensions.sh
#   Drop the four files under dppo_extensions/ into a target vt-refine
#   clone at their matching paths. Refuses to overwrite existing files.
#
# Usage:
#   bash scripts/install_dppo_extensions.sh /path/to/vt-refine
# =====================================================================

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/vt-refine"
    exit 1
fi

TARGET="$1"
if [ ! -d "$TARGET/dppo" ]; then
    echo "ERROR: $TARGET does not look like a vt-refine clone"
    echo "       (no $TARGET/dppo directory found)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXT_DIR="$REPO_ROOT/dppo_extensions"

if [ ! -d "$EXT_DIR" ]; then
    echo "ERROR: cannot find $EXT_DIR"
    echo "       (this script must be run from the repo it ships with)"
    exit 1
fi

EXT_PY="."; EXT_PY="${EXT_PY}py"

FILES=(
    "agent/eval/eval_diffusion_aperture_rim_stop_agent${EXT_PY}"
    "agent/eval/eval_diffusion_calibration_log_agent${EXT_PY}"
    "scripts/inspect_aperture_rim_mesh${EXT_PY}"
    "scripts/analyze_aperture_rim_progress${EXT_PY}"
)

echo "==== install_dppo_extensions ===="
echo "  source: $EXT_DIR"
echo "  target: $TARGET/dppo"
echo ""

INSTALLED=0
SKIPPED=0
for rel in "${FILES[@]}"; do
    src="$EXT_DIR/$rel"
    dst="$TARGET/dppo/$rel"

    if [ ! -f "$src" ]; then
        echo "  [missing] source not found: $src"
        continue
    fi

    if [ -f "$dst" ]; then
        echo "  [skip]    target exists: $dst"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  [ok]      $rel"
    INSTALLED=$((INSTALLED + 1))
done

echo ""
echo "Installed $INSTALLED file(s); skipped $SKIPPED already-present file(s)."
if [ "$SKIPPED" -gt 0 ]; then
    echo ""
    echo "If you want to overwrite existing files, remove them first or"
    echo "patch them by hand. We do not silently overwrite to avoid"
    echo "clobbering local edits."
fi
