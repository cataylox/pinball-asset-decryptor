#!/bin/bash
# Rebuild the checked-in pbioshim.so (developers only - users never build:
# the app ships the .so next to this script).
#
# The shim runs INSIDE the machine's own root (Buildroot, glibc 2.30), not on
# the host, so after linking we PROVE no symbol asks for a newer version
# than GLIBC_2.30.  dlsym is the catch: glibc 2.34 moved it into libc.so.6
# as dlsym@GLIBC_2.34, which 2.30 does not have; there it is libdl.so.2's
# dlsym@GLIBC_2.2.5.  So the shim links against a stub libdl.so.2 that
# exports exactly that version (built here, thrown away), and needs
# libdl.so.2 as the machine has it.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/pbioshim.so}
command -v gcc >/dev/null || { echo "build.sh: no gcc (apt-get install -y build-essential)" >&2; exit 4; }
STUB=$(mktemp -d)
trap 'rm -rf "$STUB"' EXIT
printf 'GLIBC_2.2.5 { global: dlsym; local: *; };\n' > "$STUB/v.map"
printf 'void *dlsym(void *h, const char *s) { (void)h; (void)s; return 0; }\n' > "$STUB/dl.c"
gcc -shared -fPIC -o "$STUB/libdl.so.2" -Wl,-soname,libdl.so.2 \
    -Wl,--version-script="$STUB/v.map" "$STUB/dl.c"
ln -s libdl.so.2 "$STUB/libdl.so"
gcc -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -D_FORTIFY_SOURCE=0 \
    -fno-stack-protector -o "$OUT.tmp" "$HERE/pbioshim.c" \
    -L"$STUB" -Wl,--no-as-needed -ldl
BAD=$(objdump -T "$OUT.tmp" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV |
      awk -F. '$2 > 30' || true)
if [ -n "$BAD" ]; then
    echo "build.sh: shim needs a glibc newer than 2.30: $BAD" >&2
    objdump -T "$OUT.tmp" | grep -E "$(echo $BAD | tr ' ' '|')" >&2
    rm -f "$OUT.tmp"
    exit 5
fi
objdump -T "$OUT.tmp" | grep -q 'GLIBC_2.2.5.*dlsym' ||
    { echo "build.sh: dlsym is not libdl's GLIBC_2.2.5" >&2; objdump -T "$OUT.tmp" >&2; rm -f "$OUT.tmp"; exit 5; }
strip --strip-unneeded "$OUT.tmp"
mv -f "$OUT.tmp" "$OUT"
echo "built $OUT ($(stat -c%s "$OUT") bytes); needs: $(objdump -p "$OUT" | awk '/NEEDED/ {print $2}' | tr '\n' ' ')glibc versions: $(objdump -T "$OUT" | grep -oE 'GLIBC_2\.[0-9.]+' | sort -uV | tr '\n' ' ')"
