#!/bin/bash
# setup.sh - the libraries Predator's programs link that PAD-Runtime (Ubuntu
# 24.04) lacks, in $PB_ENV.  Idempotent: a finished env (.ready) is left alone.
#
# The machine runs PB's own Yocto build ("pb-os", glibc 2.40); the update
# carries only /opt/game.  pinprog needs GNU Pth (libpth.so.20, dropped from
# Ubuntu) and SDL2_mixer; vidprog needs SDL2_image/_ttf, GStreamer (appsink,
# with the H.264 decoders its .mp4 animations need) and libxml2.  Both need at
# most GLIBC_2.39, so Ubuntu's libc runs them.  The SDL/GStreamer set comes
# from conda-forge (micromamba, as tools/ap_emu/setup.sh does), Pth from
# Debian's libpth20 package (the last one built, 2.0.7-22).
set -eu
. "$(dirname "$0")/pbpath.sh"
[ -f "$PB_ENV/.ready" ] && { echo "setup.sh: $PB_ENV ready"; exit 0; }
mkdir -p "$PB_ROOT/bin"
MM=$PB_ROOT/bin/micromamba
if [ ! -x "$MM" ]; then
    curl -fsSL -o "$PB_ROOT/mm.tar.bz2" https://micro.mamba.pm/api/micromamba/linux-64/latest
    # PAD-Runtime has no bzip2 binary; python's tarfile reads it.
    python3 -c "import tarfile,sys; tarfile.open(sys.argv[1]).extract('bin/micromamba', sys.argv[2])" \
        "$PB_ROOT/mm.tar.bz2" "$PB_ROOT"
    rm -f "$PB_ROOT/mm.tar.bz2"
fi
MAMBA_ROOT_PREFIX=$PB_ROOT/mamba "$MM" create -y -p "$PB_ENV" -c conda-forge \
    sdl2 sdl2_mixer sdl2_image sdl2_ttf libxml2 \
    gstreamer gst-plugins-base gst-plugins-good gst-libav
# GNU Pth: the .so out of Debian's package (ar archive, data.tar.xz).
PTH_DEB=libpth20_2.0.7-22_amd64.deb
T=$(mktemp -d)
curl -fsSL -o "$T/$PTH_DEB" "http://deb.debian.org/debian/pool/main/p/pth/$PTH_DEB"
# PAD-Runtime has no xz binary; python's tarfile reads it.
(cd "$T" && ar x "$PTH_DEB" && python3 -c "import tarfile,glob; tarfile.open(glob.glob('data.tar.*')[0]).extractall('.', filter='tar')")
cp -a "$T"/usr/lib/x86_64-linux-gnu/libpth.so.20* "$PB_ENV/lib/"
rm -rf "$T"
# The libxml2 the game was linked against has symbol versions (LIBXML2_2.4.30);
# check every library both programs need resolves from the env.
for b in pinprog vidprog; do
    f=$(ls "$PB_CACHE"/*/"$b" 2>/dev/null | head -1)
    [ -n "$f" ] || continue
    miss=$(LD_LIBRARY_PATH=$PB_ENV/lib ldd "$f" | grep "not found" || true)
    [ -z "$miss" ] || { echo "setup.sh: $b still misses:"; echo "$miss"; exit 1; }
done
touch "$PB_ENV/.ready"
echo "setup.sh: $PB_ENV ready"
