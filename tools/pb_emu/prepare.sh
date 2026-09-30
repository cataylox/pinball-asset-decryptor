#!/bin/bash
# prepare.sh <full.upd> [<delta.upd>...] - unpack a Pinball Brothers FAST
# update (and the deltas that follow it, in order) into the build cache the
# rig runs from, and print the build's path.
#
#   stdout:  build=<path>      last line on success
#   exit:    0 ok, 2 bad args, 3 no space, 4 not a title this rig runs,
#            5 unpack failed
#
# A .upd is a plain gzip+tar of the machine's /opt/game (pinprog, vidprog,
# audio/, media/); a delta carries only what changed, so Predator 1.0.1 is
# pbpp_predator_game_1_0.upd with pbpp_predator_game_1_0_1.upd over it.  The
# build is named after the LAST file and keyed by every file's size + mtime,
# so the same set starts at once the next time.  The .upd files are only
# read.
#
# The machine's OS is PB's own Yocto build, whose loader is
# /lib/ld-linux-x86-64.so.2; Ubuntu's is /lib64/..., so both programs get
# that one path patched (patchelf, from setup.sh's env).  Nothing else in
# them is touched.
#
# Alien, Queen and ABBA are not FAST machines (PB's own Heighway-lineage I/O
# boards): refused with exit 4 - tools/pbio_emu (PAD-272) is theirs.
set -u
. "$(dirname "$0")/pbpath.sh"
[ $# -ge 1 ] || { echo "usage: prepare.sh <full.upd> [<delta.upd>...]" >&2; exit 2; }
for f in "$@"; do
    [ -f "$f" ] || { echo "prepare.sh: no such file: $f" >&2; exit 2; }
done
[ -x "$PB_ENV/bin/patchelf" ] || { echo "prepare.sh: no patchelf in $PB_ENV (setup.sh)" >&2; exit 2; }

last=${!#}
name=$(basename "$last" .upd | sed -e 's/^pbpp_//' -e 's/_game_/_/' | tr -c 'A-Za-z0-9_\n-' '_')
key=$(for f in "$@"; do stat -c '%s-%Y' "$f"; done | md5sum | cut -c1-8)
DEST=$PB_CACHE/$name-$key
if [ -f "$DEST/.complete" ]; then
    touch "$DEST/.complete"
    echo "build=$DEST"
    exit 0
fi

# Which machine: Predator's update is /opt/game with pinprog; the Heighway
# titles are game/<name>/.
title=$(python3 - "$1" <<'EOF'
import sys, tarfile
try:
    with tarfile.open(sys.argv[1], "r:gz") as t:
        for m in t:
            n = m.name.lstrip("./")
            if n == "opt/game/pinprog":
                print("predator"); break
            if n.startswith("game/"):
                print("heighway:" + n.split("/")[1]); break
except (tarfile.TarError, OSError, EOFError) as e:
    print("error:%s" % e)
EOF
)
case "$title" in
    predator) ;;
    heighway:*) echo "prepare.sh: ${title#heighway:} runs on Pinball Brothers' own I/O boards, not FAST - not this rig (PAD-272)" >&2; exit 4 ;;
    error:*) echo "prepare.sh: $1 is not a readable update (${title#error:})" >&2; exit 5 ;;
    *) echo "prepare.sh: $1 is not a Pinball Brothers FAST update" >&2; exit 4 ;;
esac

need=0
for f in "$@"; do need=$((need + $(stat -c %s "$f") / 1024 + 1)); done
mkdir -p "$PB_CACHE"
free=$(df -Pk "$PB_CACHE" | awk 'NR==2 {print $4}')
if [ "$free" -lt "$need" ]; then
    echo "prepare.sh: need about $((need / 1024 / 1024)) GB free in $PB_CACHE, have $((free / 1024 / 1024)) GB" >&2
    exit 3
fi

rm -rf "$DEST.tmp"
mkdir -p "$DEST.tmp"
# `progress <pct>` lines (of every file's bytes together) for the app's footer
total=0
for f in "$@"; do total=$((total + $(stat -c %s "$f"))); done
done_b=0
for f in "$@"; do
    python3 - "$f" "$DEST.tmp" "$done_b" "$total" <<'EOF' || { rm -rf "$DEST.tmp"; echo "prepare.sh: unpacking $f failed" >&2; exit 5; }
import sys, tarfile
src, dest = sys.argv[1], sys.argv[2]
base, total = int(sys.argv[3]), max(1, int(sys.argv[4]))


class Counted:
    """The raw .upd, counting what the gzip stream has read of it."""
    def __init__(self, f):
        self.f, self.said = f, -1

    def read(self, n=-1):
        b = self.f.read(n)
        pct = int((base + self.f.tell()) * 100 / total)
        if pct != self.said:
            self.said = pct
            print("progress %d" % pct, flush=True)
        return b


with open(src, "rb") as raw, tarfile.open(fileobj=Counted(raw), mode="r|gz") as t:
    for m in t:
        n = m.name
        while n.startswith("./"):
            n = n[2:]
        if not n.startswith("opt/game/"):
            continue
        m.name = n[len("opt/game/"):]
        if not m.name:
            continue
        t.extract(m, dest, filter="tar")
EOF
    done_b=$((done_b + $(stat -c %s "$f")))
done
[ -f "$DEST.tmp/pinprog" ] && [ -f "$DEST.tmp/vidprog" ] ||
    { rm -rf "$DEST.tmp"; echo "prepare.sh: no pinprog/vidprog in the update" >&2; exit 5; }
for b in pinprog vidprog; do
    "$PB_ENV/bin/patchelf" --set-interpreter /lib64/ld-linux-x86-64.so.2 "$DEST.tmp/$b" ||
        { rm -rf "$DEST.tmp"; echo "prepare.sh: patching $b failed" >&2; exit 5; }
    chmod 755 "$DEST.tmp/$b"
done
echo "$title" > "$DEST.tmp/.pad_title"
printf '%s\n' "$@" > "$DEST.tmp/.pad_sources"
chmod -R a+rX "$DEST.tmp"
mv "$DEST.tmp" "$DEST"
touch "$DEST/.complete"
echo "build=$DEST"
