#!/bin/bash
# shot.sh <out.png> [--scale N] - a picture of this slot's game screen (the
# 1280x768 panel, from the frame buffer file the game draws into).
. "$(dirname "$0")/cgcpath.sh"
OUT=${1:?usage: shot.sh <out.png> [--scale N]}
shift
cgc_game_alive || { echo "shot.sh: rig $CGC_SLOT not running" >&2; exit 1; }
python3 "$CGC_TOOLS/cgcshot.py" "$CGC_RIG/fb" "$OUT" "$@"
