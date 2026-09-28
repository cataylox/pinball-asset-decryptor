#!/bin/bash
# PAD-251 emulator proof: boot Godzilla LE 1.16 HIDDEN (Xvfb, no window on the desktop) with
# an override set (scripts/pad251_build_overrides.py), coin up, press START and grab the
# framebuffer (glshot.sh) every second while the language screen is up: shot_3..shot_5.
#   wsl -e bash <repo>/scripts/pad251_emu_run.sh <override dir> <out dir>      (WSL paths)
set -u
RIG=$(cd "$(dirname "$0")/../tools/spike2_emu" && pwd)
OV=$1
OUT=$2
mkdir -p "$OUT"
command -v Xvfb >/dev/null || { echo "no Xvfb"; exit 3; }
. "$RIG/padpath.sh"
echo "ROOT=$ROOT"
rm -f "$ROOT/dump/padgl"
PAD_HIDDEN=1 PAD_PLAYFIELD=0 PAD_OVERRIDE_DIR="$OV" \
  PAD_CARD=/mnt/d/Pinball/images/Stern/spike2/godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw \
  bash "$RIG/watch.sh" 4 > "$OUT/watch.log" 2>&1 &
WPID=$!
for i in $(seq 1 240); do
    [ -e "$ROOT/dump/padgl" ] && break
    sleep 1
done
[ -e "$ROOT/dump/padgl" ] || { echo "no padgl after 240 s"; tail -30 "$OUT/watch.log"; kill $WPID; exit 4; }
echo "padgl up after $i s"
sleep 50
bash "$RIG/glshot.sh" "$OUT/attract.png" >/dev/null 2>&1
python3 "$RIG/plunge.py" coin >> "$OUT/plunge.log" 2>&1; sleep 2; python3 "$RIG/plunge.py" coin >> "$OUT/plunge.log" 2>&1; sleep 2
python3 "$RIG/plunge.py" start >> "$OUT/plunge.log" 2>&1
for k in $(seq 1 14); do
    sleep 1
    bash "$RIG/glshot.sh" "$OUT/shot_$k.png" >/dev/null 2>&1
done
bash "$RIG/killgame.sh" >/dev/null 2>&1
kill $WPID 2>/dev/null
sleep 3
bash "$RIG/alive.sh" 2>/dev/null | head -5
echo done
