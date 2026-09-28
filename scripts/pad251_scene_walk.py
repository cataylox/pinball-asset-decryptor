"""PAD-251: print a scene.radium's tree as plugins/stern/scene_tree.py reads it.

    python scripts/pad251_scene_walk.py <repo> <scene.radium> [--library]

One line per staged node, indented by depth: its components, keyframes (frame + v/h), first
tracks (@frame (tx,ty s scale)), colour steps, events, and for a group its labels.
"""
import sys

sys.path.insert(0, sys.argv[1])
from pinball_decryptor.plugins.stern import scene_tree as T  # noqa: E402


def line(n, depth):
    comps = ",".join(c.obj.kind for c in n.components)
    kf = "".join("%d%s" % (f, "v" if v else "h") for f, v in n.keyframes)
    tr = " ".join("@%d(%.0f,%.0f s%.2f)" % (k, m[12], m[13], m[0]) for k, m in n.tracks[:3])
    extra = ""
    for c in n.components:
        b = c.obj.body
        if c.obj.kind == "Text":
            extra += ' "%s"' % b["text"].decode("latin1")
        elif c.obj.kind == "Bitmap":
            extra += " %dx%d tex%d" % (b["w"], b["h"], b["tex"])
        elif c.obj.kind in ("Sprite", "StreamingFlipbook") and b["labels"]:
            extra += " labels=%s" % b["labels"]
    if n.colors:
        extra += " colours=%d" % len(n.colors)
    if n.events:
        extra += " events=%s" % n.events
    return "%s%s [%s] kf=%s %s%s" % ("  " * depth, n.name, comps, kf, tr, extra)


if __name__ == "__main__":
    sc = T.parse(open(sys.argv[2], "rb").read())
    print("stage %s  root frames %d  labels %s" % (sc.stage[:3], sc.root["frames"],
                                                   sc.root["labels"]))
    for n, _parent, depth in sc.walk(library="--library" in sys.argv):
        print(line(n, depth))
