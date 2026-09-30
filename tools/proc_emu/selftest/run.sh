#!/bin/bash
# selftest/run.sh - prove both levels of the fake P-ROC against the real
# open-source stack.  Needs selftest/build_real.sh run first for each Python.
#
#   probe.py   the same pinproc session on {stub, real pypinproc+libpinproc+
#              fakeftdi} x {Python 2.7, Python 3}, each on a fresh board:
#              every run must print identical lines
#   probe.c    a native libpinproc program (AAIW's shape) on fakeftdi
#   demo       pyprocgame boots demo_game.py to attract, reads the trough,
#              takes the start button and a flipper (stub and real, Python 2.7:
#              upstream pyprocgame never finished its Python 3 port; the 3.x
#              titles ship their own framework and prove it in their tickets)
#
# Env: PY2 (default $PROC_ROOT/py27/bin/python2.7), PY3 (default python3).
# Prints `VERDICT <check> pass|fail ...`; exit 0 only if all pass.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../procpath.sh"
PY2=${PY2:-$PROC_ROOT/py27/bin/python2.7}
PY3=${PY3:-python3}
REAL=$PROC_ROOT/real
OUT=$PROC_RIG/selftest
YAML=$HERE/machine.yaml
mkdir -p "$OUT"
bash "$PROC_TOOLS/build.sh" >/dev/null || exit 4
FAIL=0
verdict() { echo "VERDICT $1 $2 ${3:-}"; [ "$2" = pass ] || FAIL=1; }
fresh() { bash "$PROC_TOOLS/hw.sh" --yaml "$YAML" "$@" >/dev/null || { echo "board did not start" >&2; exit 5; }; }

pyver() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])'; }

run_probe() {   # <stub|real> <python>
    local mode=$1 py=$2 ver; ver=$(pyver "$py")
    fresh
    if [ "$mode" = real ]; then
        PYTHONPATH=$REAL/py$ver bash "$PROC_TOOLS/run_py.sh" --real -- "$py" "$HERE/probe.py"
    else
        bash "$PROC_TOOLS/run_py.sh" -- "$py" "$HERE/probe.py"
    fi > "$OUT/probe-$mode-$ver.txt" 2> "$OUT/probe-$mode-$ver.err"
}

REF=
for py in "$PY2" "$PY3"; do
    command -v "$py" >/dev/null || { verdict "probe-$py" fail "no such python"; continue; }
    ver=$(pyver "$py")
    for mode in stub real; do
        if [ $mode = real ] && [ ! -f "$REAL/py$ver/pinproc.so" ]; then
            verdict "probe-$mode-$ver" fail "not built: selftest/build_real.sh $py"
            continue
        fi
        run_probe $mode "$py"
        f=$OUT/probe-$mode-$ver.txt
        if ! tail -1 "$f" | grep -qx done; then
            verdict "probe-$mode-$ver" fail "did not finish: $(tail -2 "$OUT/probe-$mode-$ver.err" | tr '\n' ' ')"
        elif [ -z "$REF" ]; then
            REF=$f
            verdict "probe-$mode-$ver" pass "reference, $(wc -l < "$f") lines"
        elif cmp -s "$REF" "$f"; then
            verdict "probe-$mode-$ver" pass "identical to $(basename "$REF")"
        else
            verdict "probe-$mode-$ver" fail "differs from $(basename "$REF"): $(diff "$REF" "$f" | head -4 | tr '\n' ' ')"
        fi
    done
done

# ---- native libpinproc (AAIW's shape)
fresh
if gcc -O2 -w -I"$PROC_ROOT/src/libpinproc/include" "$HERE/probe.c" -L"$REAL/lib" -lpinproc \
        -Wl,-rpath,"$REAL/lib" -Wl,--allow-shlib-undefined -o "$OUT/probe_c" 2> "$OUT/probe_c.build"; then
    if bash "$PROC_TOOLS/run_py.sh" --real -- "$OUT/probe_c" "bash $PROC_TOOLS/ctl.sh" > "$OUT/probe_c.txt" 2>&1; then
        verdict probe-c pass "$(grep -c '^probe.c: ok' "$OUT/probe_c.txt") steps ok"
    else
        verdict probe-c fail "$(grep FAIL "$OUT/probe_c.txt" | head -2 | tr '\n' ' ')"
    fi
else
    verdict probe-c fail "build: $(head -3 "$OUT/probe_c.build" | tr '\n' ' ')"
fi

# ---- pyprocgame boots a game to attract and takes switches
PG=$PROC_ROOT/src/pyprocgame-py2
for py in "$PY2"; do
    command -v "$py" >/dev/null || continue
    ver=$(pyver "$py")
    for mode in stub real; do
        [ $mode = real ] && [ ! -f "$REAL/py$ver/pinproc.so" ] && continue
        fresh
        log=$OUT/demo-$mode-$ver.txt
        extra=$PG; [ $mode = real ] && extra=$REAL/py$ver:$PG
        flag=; [ $mode = real ] && flag=--real
        PYTHONPATH=$extra bash "$PROC_TOOLS/run_py.sh" $flag -- "$py" "$HERE/demo_game.py" "$YAML" > "$log" 2>&1 &
        gp=$!
        ok=0
        for _ in $(seq 1 100); do grep -q "^DEMO attract" "$log" && { ok=1; break; }; sleep 0.1; done
        if [ $ok = 1 ]; then
            bash "$PROC_TOOLS/ctl.sh" tap startButton 100 >/dev/null
            bash "$PROC_TOOLS/ctl.sh" sw flipperLwL 1 >/dev/null
            sleep 0.3
            bash "$PROC_TOOLS/ctl.sh" sw flipperLwL 0 >/dev/null
            sleep 0.5
        fi
        kill $gp 2>/dev/null; wait $gp 2>/dev/null
        blog=$(bash "$PROC_TOOLS/ctl.sh" log 200)
        att=$(grep -m1 "^DEMO attract" "$log")
        if [ $ok = 1 ] && grep -q "^DEMO start pressed" "$log" \
            && echo "$blog" | grep -q '"action": "pulse 20ms", "by": "host"' \
            && echo "$blog" | grep -q '"by": "rule sw0 closed"'; then
            verdict "demo-$mode-$ver" pass "$att; start -> trough coil pulsed; flipper rule fired"
        else
            verdict "demo-$mode-$ver" fail "${att:-no attract}: $(grep -iE 'error|Traceback' "$log" | head -2 | tr '\n' ' ')"
        fi
    done
done
bash "$PROC_TOOLS/killgame.sh" >/dev/null
exit $FAIL
