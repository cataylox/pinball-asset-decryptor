#!/bin/bash
# run_py.sh [--real] [--detach] -- <command...>
#
# Run a pyprocgame / SkeletonGame / libpinproc program against this slot's
# emulated board (start it first with hw.sh).
#   default  the pure-Python pinproc (pystub/) first on PYTHONPATH - works on
#            Python 2.7 and 3.x with nothing built
#   --real   the program's own pypinproc / libpinproc, with fakeftdi preloaded
#            in place of libftdi1 (what a native title such as AAIW needs)
#   --detach return at once; killgame.sh stops it (pid in $PROC_RIG/game.pid)
# Output goes to the terminal, or to $PROC_RIG/game.log with --detach.
set -u
. "$(dirname "$0")/procpath.sh"
REAL=0; DETACH=0
while [ $# -gt 0 ]; do
    case "$1" in
        --real) REAL=1 ;;
        --detach) DETACH=1 ;;
        --) shift; break ;;
        *) echo "run_py.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
[ $# -gt 0 ] || { echo "usage: run_py.sh [--real] [--detach] -- <command...>" >&2; exit 2; }
proc_hw_alive || { echo "run_py.sh: no board on slot $PROC_SLOT (run hw.sh first)" >&2; exit 3; }
export PROC_EMU_FPGA=$PROC_FPGA PAD_SLOT=$PROC_SLOT
if [ $REAL = 1 ]; then
    bash "$PROC_TOOLS/build.sh" >/dev/null || exit 4
    export LD_PRELOAD=$PROC_FTDI${LD_PRELOAD:+:$LD_PRELOAD}
else
    export PYTHONPATH=$PROC_STUB${PYTHONPATH:+:$PYTHONPATH}
fi
if [ $DETACH = 1 ]; then
    setsid "$@" > "$PROC_RIG/game.log" 2>&1 < /dev/null &
    echo $! > "$PROC_RIG/game.pid"
    # A title's own launcher can post under its own name (PROC_NO_BOARD=1
    # here); a bare program shows as the program, so a hidden run is never
    # invisible.
    [ "${PROC_NO_BOARD:-0}" = 1 ] || rigboard_post proc "$PROC_SLOT" "$!" "$(basename "$1")" "${PAD_TITLE:-}" \
        "$([ "${PAD_HIDDEN:-0}" = 1 ] && echo 0 || echo 1)" "${PAD_AUDIO:-0}"
    echo "game=$!"
    exit 0
fi
exec "$@"
