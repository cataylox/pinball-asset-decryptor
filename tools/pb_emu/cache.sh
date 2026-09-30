#!/bin/bash
# cache.sh --list | --drop <name>... - the Emulate PB tab's Cache window
# (tools/ap_emu/cache.sh's protocol): what the rig keeps in the app's Linux,
# and deleting it.  As root.
#
#   --list    one line per entry, key=value, then a `disk=` line:
#               entry=<name> kind=build|setup kb=<size> used=<epoch> src=<updates>
#             a build is a game unpacked from its updates (`used` is when a
#             game last started from it - or, before it ever has, when it was
#             unpacked); `setup` is the one-time libraries (setup.sh)
#               disk=<free kb> <total kb>
#   --drop    delete those entries.  One a running game uses is refused
#             (`refused=<name> in use`; the setup is in use while any game
#             runs).  A deleted build is unpacked again on its next Start,
#             the setup installed again - nothing is lost (settings and high
#             scores live in $PB_ROOT/nv<slot>, not in the cache).
# Last line of --drop is `dropped=<count>`.
. "$(dirname "$0")/pbpath.sh"

in_use() {          # the builds running games use, one per line (+ "setup")
    local r p any=0
    for r in "$PB_ROOT"/rig*/; do
        p=$(cat "$r/game.pid" 2>/dev/null)
        if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
            basename "$(cat "$r/build" 2>/dev/null)"
            any=1
        fi
    done
    [ $any = 1 ] && echo setup
}

case "${1:-}" in
    --list)
        for b in "$PB_CACHE"/*/; do
            [ -f "$b/.complete" ] || continue
            n=$(basename "$b")
            used=$(stat -c %Y "$b/.used" 2>/dev/null || stat -c %Y "$b/.complete")
            src=$(xargs -r -d '\n' -n1 basename < "$b/.pad_sources" 2>/dev/null | paste -sd+ -)
            echo "entry=$n kind=build kb=$(du -sk "$b" 2>/dev/null | cut -f1) used=$used src=$src"
        done
        if [ -d "$PB_ENV" ]; then
            kb=$(du -sk "$PB_ENV" "$PB_ROOT/mamba" "$PB_ROOT/bin" 2>/dev/null | awk '{s += $1} END {print s}')
            echo "entry=setup kind=setup kb=$kb used=$(stat -c %Y "$PB_ENV/.ready" 2>/dev/null || echo 0) src="
        fi
        mkdir -p "$PB_ROOT"
        echo "disk=$(df -Pk "$PB_ROOT" | awk 'NR==2 {print $4, $2}')"
        ;;
    --drop)
        shift
        used=$(in_use)
        n=0
        for e in "$@"; do
            case "$e" in */*|.|..|"") echo "refused=$e not a cache entry"; continue ;; esac
            echo "$used" | grep -qx "$e" && { echo "refused=$e in use"; continue; }
            if [ "$e" = setup ]; then
                [ -d "$PB_ENV" ] || { echo "refused=$e not a cache entry"; continue; }
                rm -rf --one-file-system "$PB_ENV" "$PB_ROOT/mamba" "$PB_ROOT/gst-registry.bin"
            else
                [ -d "$PB_CACHE/$e" ] || { echo "refused=$e not a cache entry"; continue; }
                rm -rf --one-file-system "$PB_CACHE/$e"
            fi
            echo "dropped $e"
            n=$((n + 1))
        done
        echo "dropped=$n"
        ;;
    *) echo "usage: cache.sh --list | --drop <name>..." >&2; exit 2 ;;
esac
