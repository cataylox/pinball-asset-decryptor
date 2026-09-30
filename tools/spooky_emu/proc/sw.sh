#!/bin/bash
# sw.sh <command...> - this slot's switches and board state, through
# tools/proc_emu's ctl socket (procctl.py): the same board the game runs on.
#   sw.sh tap startButton 150                          press for 150 ms
#   sw.sh sw flipperLwL 1 | sw.sh sw flipperLwL 0      hold / release (active)
#   sw.sh state | switches | drivers | log 20 | leds
# Switch names are the title's machine yaml's (run_game.sh names it).
. "$(dirname "$0")/sppath.sh"
PATH=$SPP_PY3/bin:$PATH PAD_SLOT=$SPP_SLOT exec bash "$SPP_PROC/ctl.sh" "$@"
