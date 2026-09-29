#!/bin/bash
# Rebuild the checked-in bofhwshim.so (developers only - users never build:
# the app ships the .so next to this script).
#
# The game runs on the host distro's glibc, not a chroot, so the shim links
# against the host.  It must still load on any glibc the game loads on
# (the game itself needs 2.33 for stat64), so after linking we PROVE no symbol
# asks for a newer version than GLIBC_2.34 - the one dlsym carries since libdl
# moved into libc.  glibc 2.38+ would otherwise sneak in __isoc23_* redirects
# for plain strtol-style calls.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/bofhwshim.so}
command -v gcc >/dev/null || { echo "build.sh: no gcc (apt-get install -y build-essential)" >&2; exit 4; }
gcc -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -D_FORTIFY_SOURCE=0 \
    -fno-stack-protector -o "$OUT.tmp" "$HERE/bofhwshim.c" -ldl
BAD=$(objdump -T "$OUT.tmp" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV |
      awk -F. '$2 > 34' || true)
if [ -n "$BAD" ]; then
    echo "build.sh: shim needs a glibc newer than 2.34: $BAD" >&2
    objdump -T "$OUT.tmp" | grep -E "$(echo $BAD | tr ' ' '|')" >&2
    rm -f "$OUT.tmp"
    exit 5
fi
strip --strip-unneeded "$OUT.tmp"
mv -f "$OUT.tmp" "$OUT"
echo "built $OUT ($(stat -c%s "$OUT") bytes); glibc versions: $(objdump -T "$OUT" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV | tr '\n' ' ')"
