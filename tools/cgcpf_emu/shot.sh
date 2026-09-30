#!/bin/bash
# shot.sh [--front] <out.png> - the picture on this slot's game's HDMI output
# now (shot.py: the three buffers laid over each other, or --front alone).
. "$(dirname "$0")/cgcpfpath.sh"
OUT=${*: -1}; [ $# -ge 1 ] || { echo "usage: shot.sh [--front] <out.png>" >&2; exit 2; }
cgcpf_game_alive || { echo "shot.sh: rig $CGCPF_SLOT not running" >&2; exit 1; }
python3 "$CGCPF_TOOLS/shot.py" "$@"
