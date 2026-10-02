#!/bin/bash
# cache.sh --list | --drop <name>... - the Emulate PB tab's Cache window for
# this rig (tools/ap_emu/cache.sh's protocol, as tools/pb_emu/cache.sh): what
# it keeps in the app's Linux, and deleting it.  As root.  (PAD-315)
#
#   --list    one line per entry, key=value, then a `disk=` line:
#               entry=<name> kind=os|update kb=<size> used=<epoch> src=<file>
#             `os` is a machine's root partition restored from its Clonezilla
#             ISO (os-<iso>), `update` an update unpacked (upd-<upd>); `used`
#             is when a game last started on it, else when it was made
#               disk=<free kb> <total kb>
#   --drop    delete those entries, and the builds (prepare.sh's small
#             build-* stacks) that use them.  One a running game uses is
#             refused (`refused=<name> in use`).  A deleted entry is made
#             again on its next Start - nothing is lost (settings and high
#             scores live in $PBIO_ROOT/nv<slot>, not in the cache).
# Last line of --drop is `dropped=<count>`.
. "$(dirname "$0")/pbiopath.sh"

in_use() {          # the cache entries running games use, one per line
    local r p
    for r in "$PBIO_ROOT"/rig*/; do
        p=$(cat "$r/game.pid" 2>/dev/null)
        if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
            sed -n "s|^$PBIO_CACHE/\([^/]*\)/.*|\1|p" "$(cat "$r/build" 2>/dev/null)/layers" 2>/dev/null
        fi
    done | sort -u
}

case "${1:-}" in
    --list)
        for d in "$PBIO_CACHE"/os-*/ "$PBIO_CACHE"/upd-*/; do
            [ -d "$d" ] || continue
            n=$(basename "$d")
            case "$n" in
                os-*) [ -f "$d/root.img" ] || continue; kind=os; mark=$d/root.img ;;
                *) [ -d "$d/tree/game" ] || continue; kind=update; mark=$d/tree ;;
            esac
            used=$(stat -c %Y "$d/.used" 2>/dev/null || stat -c %Y "$mark")
            # du counts the restored image's blocks, not its mounted view
            echo "entry=$n kind=$kind kb=$(du -sk -x "$d" 2>/dev/null | cut -f1) used=$used src=$(cat "$d/source" 2>/dev/null)"
        done
        mkdir -p "$PBIO_ROOT"
        echo "disk=$(df -Pk "$PBIO_ROOT" | awk 'NR==2 {print $4, $2}')"
        ;;
    --drop)
        shift
        used=$(in_use)
        n=0
        for e in "$@"; do
            case "$e" in os-*|upd-*) ;; *) echo "refused=$e not a cache entry"; continue ;; esac
            case "$e" in */*|*..*) echo "refused=$e not a cache entry"; continue ;; esac
            [ -d "$PBIO_CACHE/$e" ] || { echo "refused=$e not a cache entry"; continue; }
            echo "$used" | grep -qx "$e" && { echo "refused=$e in use"; continue; }
            if [ -d "$PBIO_CACHE/$e/mnt" ]; then
                mountpoint -q "$PBIO_CACHE/$e/mnt" && umount "$PBIO_CACHE/$e/mnt" 2>/dev/null
                mountpoint -q "$PBIO_CACHE/$e/mnt" && { echo "refused=$e in use"; continue; }
            fi
            for b in "$PBIO_CACHE"/build-*/; do
                grep -q "^$PBIO_CACHE/$e/" "$b/layers" 2>/dev/null && rm -rf --one-file-system "$b"
            done
            rm -rf --one-file-system "${PBIO_CACHE:?}/$e"
            echo "dropped $e"
            n=$((n + 1))
        done
        echo "dropped=$n"
        ;;
    *) echo "usage: cache.sh --list | --drop <name>..." >&2; exit 2 ;;
esac
