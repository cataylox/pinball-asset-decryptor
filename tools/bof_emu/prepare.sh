#!/bin/bash
# prepare.sh <game.fun> - decrypt a BoF update file into the build cache and
# print the game binary's path.  The passphrase comes in BOF_PASS (the app
# knows it per title; it is never written to disk or a command line).
#
#   stdout:  progress <0-100>   while decrypting (repeatable)
#            binary=<path>      last line on success
#   exit:    0 ok, 2 bad args, 3 no space, 4 decrypt failed, 5 no binary
#
# A build is cached by the .fun's size + mtime, so emulating the same file
# again starts at once, and a rebuilt mod (new mtime) is never confused with
# the old one.  Only BOF_CACHE_KEEP builds are kept (each is 2-4 GB); the
# oldest idle ones go first.  The .fun itself is only ever read.
set -u
. "$(dirname "$0")/bofpath.sh"
FUN=${1:-}
[ -f "$FUN" ] || { echo "prepare.sh: no such file: $FUN" >&2; exit 2; }
[ -n "${BOF_PASS:-}" ] || { echo "prepare.sh: BOF_PASS not set" >&2; exit 2; }
KEEP=${BOF_CACHE_KEEP:-2}

size=$(stat -c %s "$FUN")
mtime=$(stat -c %Y "$FUN")
name=$(basename "$FUN" .fun | tr -c 'A-Za-z0-9_\n-' '_')
DEST="$BOF_CACHE/$name-$size-$mtime"
mkdir -p "$BOF_CACHE"

find_bin() { find "$1" -maxdepth 2 -name '*.x86_64' -type f 2>/dev/null | head -1; }

# The playfield drawing for the switch window (pfart.py), cached with the
# build.  Best effort: a build without one still runs.
art() {         # <build dir>
    { [ -e "$1/pfart.webp" ] || [ -e "$1/pfart.png" ]; } && return 0
    python3 "$BOF_TOOLS/pfart.py" "$(find_bin "$1")" "$1/pfart.webp" \
        > /dev/null 2> "$1/pfart_error.txt" || true
}

if [ -f "$DEST/.complete" ]; then
    touch "$DEST/.complete"
    art "$DEST"         # a build unpacked before the switch window existed
    echo "binary=$(find_bin "$DEST")"
    exit 0
fi

# Evict the oldest complete builds beyond KEEP-1 (this one makes KEEP), never
# one a live rig is running.
live=$(cat "$BOF_ROOT"/rig*/binary 2>/dev/null)
ls -1t "$BOF_CACHE"/*/.complete 2>/dev/null | tail -n +"$KEEP" | while read -r c; do
    d=$(dirname "$c")
    case "$live" in *"$d"*) continue ;; esac
    rm -rf "$d"
done
rm -rf "$BOF_CACHE"/*.partial

need_kb=$(( size / 1024 * 11 / 10 ))
free_kb=$(df -Pk "$BOF_CACHE" | awk 'NR==2 {print $4}')
if [ "$free_kb" -lt "$need_kb" ]; then
    echo "prepare.sh: need $((need_kb / 1048576 + 1)) GB free in $BOF_CACHE, have $((free_kb / 1048576)) GB" >&2
    exit 3
fi

TMP="$DEST.partial"
rm -rf "$TMP"; mkdir -p "$TMP"
( gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 \
      --decrypt "$FUN" 3<<<"$BOF_PASS" | tar -xz -C "$TMP" 2>/dev/null ) &
job=$!
last=-1
while kill -0 $job 2>/dev/null; do
    got=$(du -sb "$TMP" 2>/dev/null | cut -f1)
    pct=$(( ${got:-0} * 100 / size )); [ $pct -gt 99 ] && pct=99
    [ $pct -ne $last ] && echo "progress $pct" && last=$pct
    sleep 1
done
wait $job; rc=$?
if [ $rc -ne 0 ]; then
    rm -rf "$TMP"
    echo "prepare.sh: could not decrypt $FUN (wrong title or damaged file)" >&2
    exit 4
fi
bin=$(find_bin "$TMP")
if [ -z "$bin" ]; then
    rm -rf "$TMP"
    echo "prepare.sh: $FUN holds no game binary (*.x86_64)" >&2
    exit 5
fi
chmod 755 "$bin"
echo "progress 99"
art "$TMP"
chmod -R a+rX "$TMP"
mv "$TMP" "$DEST"
touch "$DEST/.complete"
echo "progress 100"
echo "binary=$(find_bin "$DEST")"
