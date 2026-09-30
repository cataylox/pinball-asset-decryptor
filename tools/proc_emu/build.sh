#!/bin/bash
# build.sh - build fakeftdi.c into $PROC_LIB/libftdi1.so.2 when the source is
# newer (the rig builds it on demand; nothing binary is checked in).
set -eu
. "$(dirname "$0")/procpath.sh"
command -v gcc >/dev/null || { echo "build.sh: no gcc (apt-get install -y build-essential)" >&2; exit 4; }
mkdir -p "$PROC_LIB"
if [ ! -f "$PROC_FTDI" ] || [ "$PROC_TOOLS/fakeftdi.c" -nt "$PROC_FTDI" ]; then
    gcc -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -fvisibility=hidden \
        -Wl,-soname,libftdi1.so.2 -o "$PROC_FTDI.tmp" "$PROC_TOOLS/fakeftdi.c"
    mv -f "$PROC_FTDI.tmp" "$PROC_FTDI"
    ln -sf libftdi1.so.2 "$PROC_LIB/libftdi1.so"
    echo "built $PROC_FTDI"
fi
