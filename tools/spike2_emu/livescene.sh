#!/bin/bash
# livescene.sh <card path> <new file> - hand a RUNNING game a scene edited on the Scenes tab,
# "on the fly" (PAD-251).
#
#   livescene.sh /godzilla_le/assets/lcd/demand_loaded/762a.../scene.radium /mnt/c/.../new.radium
#
# WHY THIS WORKS AT ALL. run_game.sh binds each file of the override set over the card's copy
# (overrides.sh stages the set on the Linux disk first). A bind mount follows the INODE, so
# bytes written INTO the staged file are what the guest reads the next time it opens it - and
# a scene the game loads on demand (lcd/demand_loaded) is opened every time it is shown:
# measured on Godzilla LE 1.16, the language screen was read again at each game start and
# drew the new bytes. A scene it loads once at boot (lcd/auto_loaded: the HUD, Battle Select)
# is never read again, so it changes at the next Start; the Scenes tab says which is which.
#
# IN PLACE, never mv or cp --remove-destination: a new inode would leave the mount on the old
# one and the game would never see the edit.
#
# AND THE NEXT START MUST NOT TRUST THIS FILE. overrides.sh brings a stage forward by
# replaying a build's byte ranges over the generation it holds; a file changed here is no
# longer that generation. So every file written here is listed in override.live beside the
# stage, and overrides.sh copies each listed one back from the set before it decides anything.
#
# Exit 0 written; 2 bad arguments; 3 the running set does not hold that scene (nothing is
# bound over the card's copy, so there is nothing to write into - the next Start includes it);
# 4 the write failed.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)
. "$SELF/padpath.sh"
STAGE=${PAD_SLOTDIR:-$PAD_HOME}/override
LIVE=${PAD_SLOTDIR:-$PAD_HOME}/override.live

REL=${1:-}; SRC=${2:-}
REL=${REL#/}
[ -n "$REL" ] && [ -f "$SRC" ] || { echo "[live] usage: livescene.sh <card path> <file>" >&2; exit 2; }
case $REL in *..*) echo "[live] refusing $REL" >&2; exit 2 ;; esac
DST=$STAGE/$REL
[ -f "$DST" ] || { echo "[live] the running game's set does not hold $REL" >&2; exit 3; }

grep -qxF "$REL" "$LIVE" 2>/dev/null || printf '%s\n' "$REL" >> "$LIVE"
cat "$SRC" > "$DST" || { echo "[live] could not write $DST" >&2; exit 4; }
echo "[live] $REL: $(stat -c %s "$DST") bytes handed to the running game"
