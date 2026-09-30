#!/bin/bash
# sw.sh <command...> - this slot's switches and board state, through
# tools/proc_emu's ctl socket (procctl.py): the same board the game runs on.
#   sw.sh sw startButton 1 | sw.sh sw startButton 0   hold / release (active)
#   sw.sh tap startButton 150                          press for 150 ms
#   sw.sh state | switches | drivers | log 20 | leds
# Switch names are the title's machine yaml's (<title>/config/<title>.yaml).
. "$(dirname "$0")/avpath.sh"
PATH=$AV_ENV/bin:$PATH PAD_SLOT=$AV_SLOT exec bash "$AV_PROC/ctl.sh" "$@"
