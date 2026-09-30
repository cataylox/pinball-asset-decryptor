#!/bin/bash
# setup.sh - build the environment an apiav-era American Pinball title runs
# on, in $AV_ENV.  Idempotent: a finished env (its .ready stamp) is left alone.
#
# The .pkg carries the game's Python source, its procgame/ and ApiLib/, and
# the `apiav` binary - no interpreter, no libraries.  The machine's OS (an
# Ubuntu 24.04-class build: apiav needs GLIBC_2.38) gave the game Python 3.12
# with PyYAML, requests, ecdsa, segno, oscpy, and gave apiav SDL2 (+image,
# ttf) and GStreamer 1.x.  PAD-Runtime has the right glibc and Python but none
# of the libraries, so they come from conda-forge (micromamba, no root beyond
# /var/tmp; nothing is installed into the distro).  pinproc is proc_emu's.
#
# The game also sets the en_US.UTF-8 locale (score digit grouping) and dies
# without it; PAD-Runtime has only C.UTF-8 and no locale sources, so the
# sources come out of Ubuntu's `locales` .deb (unpacked here, not installed)
# and localedef compiles the one locale into $AV_ENV/locale (LOCPATH).
#
# gst-plugins-bad is for its codecalpha plugin (vp9alphadecodebin): the
# attract title and many overlays are transparent VP9 webm ("transparent":
# true in the defs), and without it apiav draws them as nothing at all.
set -eu
. "$(dirname "$0")/avpath.sh"
[ -f "$AV_ENV/.ready" ] && { echo "setup.sh: $AV_ENV ready"; exit 0; }
mkdir -p "$AV_ROOT"
MM=$AV_ROOT/bin/micromamba
if [ ! -x "$MM" ]; then
    curl -fsSL -o "$AV_ROOT/mm.tar.bz2" https://micro.mamba.pm/api/micromamba/linux-64/latest
    # PAD-Runtime has no bzip2 binary; python's tarfile reads it.
    python3 -c "import tarfile,sys; tarfile.open(sys.argv[1]).extract('bin/micromamba', sys.argv[2])" \
        "$AV_ROOT/mm.tar.bz2" "$AV_ROOT"
    rm -f "$AV_ROOT/mm.tar.bz2"
fi
[ -x "$AV_ENV/bin/python3" ] || MAMBA_ROOT_PREFIX=$AV_ROOT/mamba "$MM" create -y -p "$AV_ENV" -c conda-forge \
    python=3.12 pyyaml requests ecdsa segno pip openssl \
    sdl2 sdl2_image sdl2_ttf gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav
"$AV_ENV/bin/pip" install -q oscpy
"$AV_ENV/bin/python" -c "import yaml, requests, ecdsa, segno, oscpy"

if [ ! -f "$AV_ENV/locale/en_US.UTF-8/LC_CTYPE" ]; then
    T=$AV_ROOT/locales.tmp
    rm -rf "$T"; mkdir -p "$T"
    POOL=http://archive.ubuntu.com/ubuntu/pool/main/g/glibc
    V=$(dpkg-query -W -f='${Version}' libc-bin)
    # The distro's exact build, else the newest of its glibc on the mirror
    # (superseded builds leave the pool; the locale sources do not change).
    DEB=$(curl -fsSL "$POOL/" | grep -o "locales_${V%%-*}-[^\"]*_all\.deb" | sort -uV | tail -1)
    curl -fsSL -o "$T/locales.deb" "$POOL/locales_${V}_all.deb" 2>/dev/null         || curl -fsSL -o "$T/locales.deb" "$POOL/$DEB"
    dpkg-deb -x "$T/locales.deb" "$T/x"
    mkdir -p "$AV_ENV/locale"
    I18NPATH=$T/x/usr/share/i18n localedef -i en_US -f UTF-8 "$AV_ENV/locale/en_US.UTF-8"
    rm -rf "$T"
fi
LOCPATH=$AV_ENV/locale "$AV_ENV/bin/python" -c "import locale; locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')"
touch "$AV_ENV/.ready"
echo "setup.sh: $AV_ENV ready"
