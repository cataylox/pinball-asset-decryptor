#!/bin/bash
# status.sh - this slot's run as key=value lines (run as root: the game's
# state is read out of its memory).
#   running=0|1  build=<name>  state=attract|game|search|<n>  credits=<n>
#   xfers=<board exchanges>  cab_reads=<cabinet bus reads>  closed=<switches>
. "$(dirname "$0")/cgcpfpath.sh"
if ! cgcpf_game_alive; then echo running=0; exit 0; fi
echo running=1
echo "build=$(basename "$(cat "$CGCPF_RIG/build" 2>/dev/null)")"
s=$(cgcpf_peek $CGCPF_STATE_ADDR)
case "$s" in 1) s=attract ;; 2) s=game ;; 4) s=search ;; esac
echo "state=$s"
echo "credits=$(cgcpf_peek $CGCPF_CREDITS_ADDR)"
python3 "$CGCPF_TOOLS/sw.py" state | python3 -c '
import json, sys
s = json.load(sys.stdin)
print("xfers=%d" % s["xfers"])
print("cab_reads=%d" % s["cab_reads"])
print("closed=%s" % ",".join(s["closed"]))'
