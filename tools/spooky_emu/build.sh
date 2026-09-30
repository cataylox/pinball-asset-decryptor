#!/bin/bash
# Rebuild the checked-in spkshim.so and lib/libXinerama.so.1 (developers
# only: both ship beside this script).  Proves no symbol asks for a glibc newer than 2.34, as
# tools/bof_emu/build.sh does for its shim.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/spkshim.so}
command -v gcc >/dev/null || { echo "build.sh: no gcc (apt-get install -y build-essential)" >&2; exit 4; }
gcc -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -D_FORTIFY_SOURCE=0 \
    -fno-stack-protector -o "$OUT.tmp" "$HERE/spkshim.c" -ldl
BAD=$(objdump -T "$OUT.tmp" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV |
      awk -F. '$2 > 34' || true)
if [ -n "$BAD" ]; then
    echo "build.sh: shim needs a glibc newer than 2.34: $BAD" >&2
    rm -f "$OUT.tmp"
    exit 5
fi
strip --strip-unneeded "$OUT.tmp"
mv -f "$OUT.tmp" "$OUT"
echo "built $OUT ($(stat -c%s "$OUT") bytes); glibc versions: $(objdump -T "$OUT" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV | tr '\n' ' ')"

# Looney Tunes' Godot needs a libXinerama to exist (xinerama_stub.c).
mkdir -p "$HERE/lib"
gcc -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -Wl,-soname,libXinerama.so.1 \
    -o "$HERE/lib/libXinerama.so.1.tmp" "$HERE/xinerama_stub.c"
strip --strip-unneeded "$HERE/lib/libXinerama.so.1.tmp"
mv -f "$HERE/lib/libXinerama.so.1.tmp" "$HERE/lib/libXinerama.so.1"
echo "built $HERE/lib/libXinerama.so.1"
