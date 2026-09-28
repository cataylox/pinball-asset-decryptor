"""Walk every scene.radium on a card under the grammar; count EXACT / SHORT / STOPPED."""
import os
import sys
import time

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pinball_decryptor.plugins.stern import engine  # noqa: E402
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader  # noqa: E402
import pad251_scene_walk as walk  # noqa: E402

raw = sys.argv[2]
t0 = time.time()
exact, short, stopped = [], [], []
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
            w = walk.Walk(data)
            tag = path.split("/")[-2][:8]
            try:
                res = w.run()
                (exact if res["end"] == len(data) else short).append(
                    (tag, len(data), len(w.nodes), res["end"]))
            except Exception as e:
                stopped.append((tag, len(data), len(w.nodes), w.r.o, repr(e)[:90], dict(w.poly)))
print("scenes %d: EXACT %d, SHORT %d, STOPPED %d  (%.0f s)" % (
    len(exact) + len(short) + len(stopped), len(exact), len(short), len(stopped), time.time() - t0))
for s in short:
    print("SHORT", s)
for s in stopped:
    print("STOP ", s)
print("nodes walked in exact scenes:", sum(n for _t, _l, n, _e in exact))
