#!/bin/bash
# selftest/build_real.sh <python>... - build the REAL open-source P-ROC stack
# against fakeftdi, for the self-test's "real" runs:
#   $PROC_ROOT/real/lib/libpinproc.so        libpinproc (the protocol's author)
#   $PROC_ROOT/real/py<X.Y>/pinproc.so       pypinproc for each <python>
#                                            (3.x: py3port.py first - upstream
#                                            pypinproc is Python 2 only)
#   $PROC_ROOT/src/pyprocgame-py2            pyprocgame for the demo game
# Sources are fetched once, at pinned revisions, into $PROC_ROOT/src.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../procpath.sh"
SRC=$PROC_ROOT/src
REAL=$PROC_ROOT/real
LIBPINPROC_REV=286c56694dae9f068e6ba14f8f625026f15e54c7    # preble/libpinproc dev
PYPINPROC_REV=a4e1b97706be22511e9b9722448b5a866958de2f     # preble/pypinproc master
PYPROCGAME_REV=47de6ca^1   # preble/pyprocgame: the last Python 2 commit (its
                           # later Python 3 port was never finished upstream)

bash "$PROC_TOOLS/build.sh" >/dev/null
mkdir -p "$SRC" "$REAL/lib"

fetch() {       # <github repo> <dir> <rev>
    [ -d "$SRC/$2/.git" ] || git clone -q "https://github.com/$1" "$SRC/$2"
    git -C "$SRC/$2" checkout -q "$3"
}
fetch preble/libpinproc libpinproc "$LIBPINPROC_REV"
fetch preble/pypinproc pypinproc "$PYPINPROC_REV"
fetch preble/pyprocgame pyprocgame master
rm -rf "$SRC/pyprocgame-py2"
git -C "$SRC/pyprocgame" archive --prefix=pyprocgame-py2/ "$PYPROCGAME_REV" | tar -x -C "$SRC"

L=$SRC/libpinproc
g++ -shared -fPIC -O2 -w -I"$L/include" -I"$L/src" -I"$HERE/include" \
    "$L/src/PRDevice.cpp" "$L/src/PRHardware.cpp" "$L/src/pinproc.cpp" \
    -L"$PROC_LIB" -l:libftdi1.so.2 -Wl,-soname,libpinproc.so \
    -o "$REAL/lib/libpinproc.so"
echo "built $REAL/lib/libpinproc.so"

for PY in "$@"; do
    VER=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    INC=$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')
    B=$REAL/py$VER/build
    rm -rf "$B" && mkdir -p "$B"
    cp "$SRC/pypinproc/"*.cpp "$SRC/pypinproc/"*.c "$SRC/pypinproc/"*.h "$B/"
    case $VER in 3.*) python3 "$HERE/py3port.py" "$B" ;; esac
    gcc -c -fPIC -O2 -w -I"$INC" -o "$B/dmd.o" "$B/dmd.c"
    g++ -shared -fPIC -O2 -w -fpermissive -I"$INC" -I"$L/include" \
        "$B/pypinproc.cpp" "$B/dmdutil.cpp" "$B/dmd.o" \
        -L"$REAL/lib" -lpinproc -Wl,-rpath,"$REAL/lib" -o "$REAL/py$VER/pinproc.so"
    echo "built $REAL/py$VER/pinproc.so"
done
