"""PAD-251: parse every scene.radium on a card with plugins/stern/scene_tree.py and write it
back; count the scenes that walk EXACT and round-trip byte for byte, list the rest.

    python scripts/pad251_scene_census.py <repo> <card.raw> [--dump <dir>]
"""
import os
import sys
import time

sys.path.insert(0, sys.argv[1])
from pinball_decryptor.plugins.stern import engine, scene_tree  # noqa: E402
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader  # noqa: E402

raw = sys.argv[2]
dump = sys.argv[sys.argv.index("--dump") + 1] if "--dump" in sys.argv else None
t0 = time.time()
ok, differ, stopped = [], [], []
with open(raw, "rb") as f:
    for off, size in engine._linux_partitions(raw):
        try:
            r = Ext4Reader(f, off, size)
            files = list(r.iter_regular_files(min_size=32))
        except Exception:
            continue
        for path, _ino, node in files:
            if not path.endswith("scene.radium"):
                continue
            data = r.read_file_bytes(node)
            tag = "/".join(path.split("/")[-3:-1])
            try:
                sc = scene_tree.parse(data)
            except Exception as e:
                stopped.append((tag, len(data), repr(e)[:110]))
                if dump:
                    open(os.path.join(dump, tag.replace("/", "_") + ".radium"), "wb").write(data)
                continue
            back = scene_tree.serialize(sc)
            (ok if back == data else differ).append((tag, len(data), len(sc.walk())))
print("scenes %d: ROUND-TRIP %d, DIFFER %d, STOPPED %d  (%.0f s)" % (
    len(ok) + len(differ) + len(stopped), len(ok), len(differ), len(stopped), time.time() - t0))
for s in differ:
    print("DIFFER", s)
for s in stopped:
    print("STOP  ", s)
