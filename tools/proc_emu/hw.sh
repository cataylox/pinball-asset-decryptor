#!/bin/bash
# hw.sh [prochw.py options] - (re)start this slot's emulated P3-ROC and wait
# for its sockets.  Typical: hw.sh --yaml <game>/config/machine.yaml
# Prints `fpga=<socket>` and `ctl=<socket>`; exit 1 if it did not come up.
set -u
. "$(dirname "$0")/procpath.sh"
if proc_hw_alive; then kill "$(proc_hw_pid)" 2>/dev/null; sleep 0.2; fi
mkdir -p "$PROC_RIG"
chmod 777 "$PROC_ROOT" "$PROC_RIG" 2>/dev/null
rm -f "$PROC_FPGA" "$PROC_CTL"
setsid python3 "$PROC_TOOLS/prochw.py" --dir "$PROC_RIG" "$@" \
    >> "$PROC_RIG/prochw.out" 2>&1 < /dev/null &
echo $! > "$PROC_RIG/prochw.pid"
for _ in $(seq 1 50); do
    if [ -S "$PROC_FPGA" ] && [ -S "$PROC_CTL" ]; then
        echo "fpga=$PROC_FPGA"
        echo "ctl=$PROC_CTL"
        exit 0
    fi
    proc_hw_alive || break
    sleep 0.1
done
echo "hw.sh: prochw.py did not come up:" >&2
tail -5 "$PROC_RIG/prochw.out" >&2
exit 1
