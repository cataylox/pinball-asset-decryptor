#!/bin/bash
# setup.sh - build the Python 2.7 every American Pinball title runs on, in
# $AP_PY.  Idempotent: a finished env (its .ready stamp) is left alone.
#
# AP's .pkg carries the game and its procgame/ but no interpreter or native
# library: the machine's OS provided Python 2.7, pySDL2 + SDL2_mixer/ttf/
# image, PyYAML, numpy, PIL, pyOSC (the OSC switch input mode) and OpenCV
# 2.4 (cv2.VideoCapture plays the movies; conda-forge's py27 OpenCV is 4.2,
# so aprun.py stands the 2.4 `cv2.cv` names in).
# Ubuntu 24.04 has no Python 2, so this takes them from conda-forge's
# archived py27 builds (micromamba, no root needed beyond /var/tmp).
# The P-ROC module is ours (py/pinproc.py), not pypinproc.
set -eu
. "$(dirname "$0")/appath.sh"
[ -f "$AP_PY/.ready" ] && { echo "setup.sh: $AP_PY ready"; exit 0; }
mkdir -p "$AP_ROOT"
MM=$AP_ROOT/bin/micromamba
if [ ! -x "$MM" ]; then
    curl -fsSL -o "$AP_ROOT/mm.tar.bz2" https://micro.mamba.pm/api/micromamba/linux-64/latest
    # PAD-Runtime has no bzip2 binary; python's tarfile reads it.
    python3 -c "import tarfile,sys; tarfile.open(sys.argv[1]).extract('bin/micromamba', sys.argv[2])" \
        "$AP_ROOT/mm.tar.bz2" "$AP_ROOT"
    rm -f "$AP_ROOT/mm.tar.bz2"
fi
MAMBA_ROOT_PREFIX=$AP_ROOT/mamba "$MM" create -y -p "$AP_PY" -c conda-forge \
    python=2.7 pyyaml numpy pillow pyserial opencv sdl2 sdl2_mixer sdl2_image sdl2_ttf pip openssl font-ttf-dejavu-sans-mono
"$AP_PY/bin/pip" install -q "pysdl2==0.9.11" "pyOSC==0.3.5b5294"
PYSDL2_DLL_PATH=$AP_PY/lib "$AP_PY/bin/python" -c \
    "import cv2, yaml, numpy, PIL.Image, OSC, serial, sdl2, sdl2.sdlmixer, sdl2.sdlttf, sdl2.sdlimage"
# apiav (the A/V controller of Hot Wheels on) is native: GStreamer with the
# MP4/H.264 decoders its videos need, and SDL2.  Its own env - the py27 one
# pins an old GStreamer for OpenCV.
MAMBA_ROOT_PREFIX=$AP_ROOT/mamba "$MM" create -y -p "$AP_AV" -c conda-forge     gstreamer gst-plugins-base gst-plugins-good gst-libav sdl2 sdl2_image sdl2_ttf
# Galactic Tank Force's 2026 build is Python 3.14 (its bytecode's magic) and
# draws through apiav, so it needs only PyYAML and oscpy beside the stdlib.
MAMBA_ROOT_PREFIX=$AP_ROOT/mamba "$MM" create -y -p "$AP_PY3" -c conda-forge python=3.14 pyyaml pip
"$AP_PY3/bin/pip" install -q oscpy
"$AP_PY3/bin/python3" -c "import yaml, oscpy"
touch "$AP_PY/.ready"
echo "setup.sh: $AP_PY ready"
