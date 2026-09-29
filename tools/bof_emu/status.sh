#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app.
# Never prose: the app parses it (webui/rig.parse_status).
#   wsl=1                 always (the app's "WSL answered")
#   running=0|1
#   title= pid= rss_kb= uptime_s= display= visible=0|1     (while running)
#   art=<the playfield drawing, Linux path, may be empty>  slot=
#   hw=<bofhw.py state JSON, one line>                      (while running)
. "$(dirname "$0")/bofpath.sh"
echo "wsl=1"
if bof_game_alive; then
    P=$(bof_game_pid)
    echo "running=1"
    echo "title=$(cat "$BOF_RIG/title" 2>/dev/null)"
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$BOF_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$BOF_RIG/visible" 2>/dev/null)"
    echo "art=$(ls "$(dirname "$(cat "$BOF_RIG/binary" 2>/dev/null)")"/pfart.webp "$(dirname "$(cat "$BOF_RIG/binary" 2>/dev/null)")"/pfart.png 2>/dev/null | head -1)"
    echo "slot=$BOF_SLOT"
    echo "hw=$(python3 "$BOF_TOOLS/bofctl.py" --slot "$BOF_SLOT" state 2>/dev/null)"
else
    echo "running=0"
fi
