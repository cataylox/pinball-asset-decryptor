#!/usr/bin/env python3
"""pfart.py <game binary> <out.webp|png> - pull the playfield drawing out of
a Barrels of Fun build.

Every title's service menu draws its switch test over
``assets/images/service_menu/service_switch_test_background.png`` and puts a
marker on it at each switch's (x_position, y_position) from its own switch
table - the same numbers gen_profile.py copies into the profile.  So the
picture and the coordinates agree by construction: they are one screen of the
game's own.  (Found on Winchester, 2026-09-28: the game's CAD drawing of the
playfield, 305x698, every switch where it belongs.)

The texture ships imported (``.ctex``, a GST2-wrapped WebP or PNG); this
writes the image inside it.  Dune's PCK directory is AES-encrypted; without
pycryptodome (the app's Linux has none) pck_directory falls back to a pure
Python AES, which is slow but runs once per build: prepare.sh caches the
result beside the build.

Exit 0 and prints the path written; 1 when the build carries no such picture
(the switch window then shows the markers on a plain field).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))   # the repo / {app}

from pinball_decryptor.plugins.bof import pck_directory          # noqa: E402
from pinball_decryptor.plugins.bof.source_converter import _decode_ctex  # noqa: E402

WANT = b"/service_switch_test_background.png-"


def main(binary, out):
    d = pck_directory.read(binary)
    if d is None:
        print("pfart.py: no PCK directory in %s" % binary, file=sys.stderr)
        return 1
    for path, e in d.by_path().items():
        if WANT in path and path.endswith(b".ctex"):
            with open(binary, "rb") as f:
                f.seek(d.pck_off + d.base + e["ofs"])
                ext, data = _decode_ctex(f.read(e["size"]))
            if not ext:
                break
            root = os.path.splitext(out)[0]
            dest = root + ext
            with open(dest + ".tmp", "wb") as g:
                g.write(data)
            os.replace(dest + ".tmp", dest)
            print(dest)
            return 0
    print("pfart.py: no switch-test playfield picture in this build",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
