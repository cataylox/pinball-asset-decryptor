#!/bin/bash
# build.sh [<build>] - developers: rebuild pfshim.so (ARM hard-float, for
# the machine's glibc 2.15).  Compiled against the machine's own headers and
# libraries - the carved rootfs, mounted read-only for the build - since a
# modern cross toolchain's glibc symbols would not load there.  Needs
# gcc-arm-linux-gnueabihf.  Run as root (the loop mount).
set -e
. "$(dirname "$0")/cgcpfpath.sh"
BUILD=${1:-$(ls -1td "$CGCPF_CACHE"/*/ 2>/dev/null | head -1)}
case "$BUILD" in /*) ;; *) BUILD=$CGCPF_CACHE/$BUILD ;; esac
[ -f "${BUILD%/}/rootfs.img" ] || { echo "build.sh: no prepared build (prepare.py)" >&2; exit 2; }
M=$(mktemp -d)
cat > "$M.sh" <<IN
set -e
mount -o loop,ro "${BUILD%/}/rootfs.img" "$M"
L=$M/lib/arm-linux-gnueabihf
arm-linux-gnueabihf-gcc -nostdinc -isystem $M/usr/include -isystem $M/usr/include/arm-linux-gnueabihf \
    -isystem \$(arm-linux-gnueabihf-gcc -print-file-name=include) -I$M/usr/include/libdrm \
    -O2 -Wall -shared -fPIC -fno-stack-protector -U_FORTIFY_SOURCE -U_FILE_OFFSET_BITS -U_TIME_BITS \
    -nostdlib -o "$CGCPF_SHIM.tmp" "$CGCPF_TOOLS/pfshim.c" \$L/libc.so.6 \$L/libdl.so.2 \$L/libpthread.so.0 -lgcc
IN
unshare -m --propagation private bash "$M.sh"
rmdir "$M"; rm -f "$M.sh"
mv "$CGCPF_SHIM.tmp" "$CGCPF_SHIM"
echo "$CGCPF_SHIM"
