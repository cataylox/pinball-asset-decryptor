#!/bin/bash
# prepare.sh <update file> - unpack a Beetlejuice update (v<date>.beetlejuice:
# a GPG-SIGNED, not encrypted, tar.gz of the game folder - Spooky's, or one
# the Write tab built) into the build cache and print its name.
#
#   stdout:  progress <0-100>   while unpacking (repeatable)
#            build=<name>       last line on success (run_game.sh <name>)
#   exit:    0 ok, 2 bad args, 3 no space, 4 unpack failed or not
#            Beetlejuice, 5 no game in it
#
# The name is bj_<version.txt>, so the same update again starts at once.
# Only SPK_CACHE_KEEP builds are kept (each is ~5 GB); the oldest idle ones
# go first.  The update itself is only ever read.
set -u
. "$(dirname "$0")/spkpath.sh"
UPD=${1:-}
[ -f "$UPD" ] || { echo "prepare.sh: no such file: $UPD" >&2; exit 2; }
KEEP=${SPK_CACHE_KEEP:-2}
mkdir -p "$SPK_CACHE"

size=$(stat -c %s "$UPD")
# The signature's literal-data packet names no version; the file name does
# (v2026.09.15.11.beetlejuice), and version.txt inside says it again.
ver=$(basename "$UPD" | grep -oE 'v?[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{2}' | head -1)
ver=v${ver#v}
DEST=$SPK_CACHE/bj_$ver
if [ "$ver" != v ] && [ -x "$DEST/main.x86_64" ]; then
    touch "$DEST"
    echo "build=$(basename "$DEST")"
    exit 0
fi

live=$(cat "$SPK_ROOT"/rig*/build 2>/dev/null)
ls -1dt "$SPK_CACHE"/bj_* 2>/dev/null | grep -v '\.partial$' | tail -n +"$KEEP" | while read -r d; do
    case "$live" in *"$d"*) continue ;; esac
    rm -rf "$d"
done
rm -rf "$SPK_CACHE"/*.partial

need_kb=$(( size / 1024 * 25 / 10 ))
free_kb=$(df -Pk "$SPK_CACHE" | awk 'NR==2 {print $4}')
if [ "$free_kb" -lt "$need_kb" ]; then
    echo "prepare.sh: need $((need_kb / 1048576 + 1)) GB free in $SPK_CACHE, have $((free_kb / 1048576)) GB" >&2
    exit 3
fi

TMP=$SPK_CACHE/bj_unpack.partial
rm -rf "$TMP"; mkdir -p "$TMP"
GH=$(mktemp -d)
# No key to check the signature with: gpg still unwraps the data (and says
# "Can't check signature", which is fine - the game is Spooky's as shipped).
# A plain tar.gz (gzip magic 1f8b) is taken as it is.
if [ "$(head -c 2 "$UPD" | od -An -tx1 | tr -d ' ')" = 1f8b ]; then
    ( tar -xzf "$UPD" -C "$TMP" ) &
else
    ( gpg --homedir "$GH" --batch --quiet -d "$UPD" 2>/dev/null | tar -xz -C "$TMP" ) &
fi
job=$!
last=-1
while kill -0 $job 2>/dev/null; do
    got=$(du -sb "$TMP" 2>/dev/null | cut -f1)
    pct=$(( ${got:-0} * 100 / (size * 22 / 10) )); [ $pct -gt 99 ] && pct=99
    [ $pct -ne $last ] && echo "progress $pct" && last=$pct
    sleep 1
done
wait $job; rc=$?
rm -rf "$GH"
if [ $rc -ne 0 ]; then
    rm -rf "$TMP"
    echo "prepare.sh: could not unpack $UPD (not a Beetlejuice update, or damaged)" >&2
    exit 4
fi
if [ ! -x "$TMP/main.x86_64" ] || [ ! -f "$TMP/UnityPlayer.so" ]; then
    rm -rf "$TMP"
    echo "prepare.sh: no Unity game (main.x86_64) in $UPD" >&2
    exit 5
fi
# Beetlejuice only, for now: its game code names its modes (BeetleSnakeMode).
# Scooby-Doo and Halloween are Unity games too; neither has been tried.
if ! grep -aq BeetleSnakeMode "$TMP/main_Data/Managed/Assembly-CSharp.dll" 2>/dev/null; then
    rm -rf "$TMP"
    echo "prepare.sh: $(basename "$UPD") is not a Beetlejuice update (the only Spooky game this emulator runs so far)" >&2
    exit 4
fi
v=$(tr -d '\r\n ' < "$TMP/version.txt" 2>/dev/null)
DEST=$SPK_CACHE/bj_${v:-$ver}
rm -rf "$DEST"
mv "$TMP" "$DEST"
echo "progress 100"
echo "build=$(basename "$DEST")"
