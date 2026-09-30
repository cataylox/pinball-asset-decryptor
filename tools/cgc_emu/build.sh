#!/bin/bash
# build.sh [<sysroot>] - rebuild the checked-in cgcshim.so (developers only:
# the app ships the .so next to this script).
#
# The shim is loaded into the machine's own program, over the machine's own
# glibc (Debian 7: 2.13), so it links against THAT libc - a build's
# sysroot/ that prepare.sh made (default: the newest build) - and never
# the cross compiler's.  Afterwards we PROVE no symbol asks for a glibc
# version newer than 2.13.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/cgcpath.sh"
SR=${1:-$(ls -1td "$CGC_CACHE"/*/sysroot 2>/dev/null | head -1)}
OUT=$HERE/cgcshim.so
command -v arm-linux-gnueabihf-gcc >/dev/null ||
    { echo "build.sh: no arm-linux-gnueabihf-gcc (apt-get install -y gcc-arm-linux-gnueabihf)" >&2; exit 4; }
L=$SR/lib/arm-linux-gnueabihf
[ -f "$L/libc.so.6" ] || { echo "build.sh: no machine libc in $L (run prepare.sh on a card first)" >&2; exit 4; }
# Ubuntu's armhf headers default to 64-bit time_t (the t64 transition) and
# would redirect stat/nanosleep to __*_time64 symbols a 2.13 libc lacks;
# -z defs makes any such symbol a link error here, not a load error there.
arm-linux-gnueabihf-gcc -std=gnu17 -shared -fPIC -O2 -nostdlib \
    -U_FORTIFY_SOURCE -U_TIME_BITS -U_FILE_OFFSET_BITS \
    -fno-stack-protector -Wall -Wextra -Werror=implicit-function-declaration \
    -Wl,-soname,cgcshim.so -Wl,-z,defs -o "$OUT.tmp" "$HERE/cgcshim.c" \
    "$L/libc.so.6" "$L/libpthread.so.0" "$L/libdl.so.2" "$L/ld-linux-armhf.so.3" -lgcc || exit 1
BAD=$(arm-linux-gnueabihf-objdump -T "$OUT.tmp" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV |
      awk -F. '$2 > 13' || true)
if [ -n "$BAD" ]; then
    echo "build.sh: shim needs a glibc newer than the machine's 2.13: $BAD" >&2
    arm-linux-gnueabihf-objdump -T "$OUT.tmp" | grep -E "$(echo $BAD | tr ' ' '|')" >&2
    rm -f "$OUT.tmp"
    exit 5
fi
arm-linux-gnueabihf-strip --strip-unneeded "$OUT.tmp"
mv -f "$OUT.tmp" "$OUT"
echo "built $OUT ($(stat -c%s "$OUT") bytes); glibc versions: $(arm-linux-gnueabihf-objdump -T "$OUT" | grep -oE 'GLIBC_2\.[0-9]+' | sort -uV | tr '\n' ' ')"
