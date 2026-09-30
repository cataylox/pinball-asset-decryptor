#!/bin/bash
# cache.sh --list | --drop <name>... - the Emulate AP tab's Cache window: what
# the rig keeps in the app's Linux, and deleting it.  As root.
#
#   --list    one line per entry, key=value, then a `disk=` line:
#               entry=<name> kind=build|envs kb=<size> used=<epoch> src=<.pkg or "">
#             `used` is when a game last started from it (run_game.sh touches
#             <build>/used) - or, before it ever has, when it was unpacked.
#               disk=<free kb> <total kb>
#             A build is an unpacked .pkg ($AP_CACHE/<name>, prepare.py);
#             `envs` is the Python/GStreamer setup.sh downloaded (~1 GB).
#   --drop    delete those entries.  One a running game uses is refused
#             (`refused=<name> in use`); `envs` is refused while any game
#             runs.  A deleted build is unpacked again on its next Start, the
#             envs downloaded again - nothing is lost.
# Last line of --drop is `dropped=<count>`.
. "$(dirname "$0")/appath.sh"

in_use() {          # the builds running games use, one per line
    local r p
    for r in "$AP_ROOT"/rig*/; do
        p=$(cat "$r/game.pid" 2>/dev/null)
        [ -n "$p" ] && kill -0 "$p" 2>/dev/null && basename "$(cat "$r/build" 2>/dev/null)"
    done
}

case "${1:-}" in
    --list)
        for b in "$AP_CACHE"/*/; do
            [ -f "$b/launcher" ] || continue
            n=$(basename "$b")
            echo "entry=$n kind=build kb=$(du -sk "$b" 2>/dev/null | cut -f1)" \
                "used=$(stat -c %Y "$b/used" 2>/dev/null || stat -c %Y "$b/launcher")" \
                "src=$(cat "$b/pkg" 2>/dev/null)"
        done
        if [ -d "$AP_PY" ] || [ -d "$AP_ROOT/mamba" ]; then
            kb=$(du -sck "$AP_PY" "$AP_PY3" "$AP_AV" "$AP_ROOT/mamba" "$AP_ROOT/bin" 2>/dev/null | tail -1 | cut -f1)
            echo "entry=envs kind=envs kb=$kb used=$(stat -c %Y "$AP_PY/.ready" 2>/dev/null || echo 0) src="
        fi
        mkdir -p "$AP_ROOT"
        echo "disk=$(df -Pk "$AP_ROOT" | awk 'NR==2 {print $4, $2}')"
        ;;
    --drop)
        shift
        used=$(in_use)
        n=0
        for e in "$@"; do
            case "$e" in */*|.|..|"") echo "refused=$e not a cache entry"; continue ;; esac
            if [ "$e" = envs ]; then
                [ -n "$used" ] && { echo "refused=envs in use"; continue; }
                rm -rf "$AP_PY" "$AP_PY3" "$AP_AV" "$AP_ROOT/mamba" "$AP_ROOT/bin"
            else
                [ -d "$AP_CACHE/$e" ] || { echo "refused=$e not a cache entry"; continue; }
                echo "$used" | grep -qx "$e" && { echo "refused=$e in use"; continue; }
                rm -rf --one-file-system "$AP_CACHE/$e"
            fi
            echo "dropped $e"
            n=$((n + 1))
        done
        echo "dropped=$n"
        ;;
    *) echo "usage: cache.sh --list | --drop <name>..." >&2; exit 2 ;;
esac
