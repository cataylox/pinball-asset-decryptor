"""PAD-251 spike (PROVEN, keep): walk a whole stock scene.radium under the cereal grammar
scene_write.py documents (what the GAME reads, per tools/spike2_emu/modes/scenelog.c), plus
the two structures it never had to emit: the per-node COLOUR track and the Shape class.
Walks 156 of 194 scenes on Godzilla LE 1.16 / Pro 1.15 EXACT to the last byte (4 s a card;
scripts/pad251_scene_census.py).  Prints the node tree with keyframes, tracks and labels.

    python scripts/pad251_scene_walk.py <repo> <scene.radium> [--tree]
"""
import struct
import sys

sys.path.insert(0, sys.argv[1])
from pinball_decryptor.plugins.stern import scene_write as SW  # noqa: E402

FLAG = 0x80000000


class R:
    def __init__(self, d):
        self.d, self.o = d, 0

    def u8(self):
        v = self.d[self.o]
        self.o += 1
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def u64(self):
        v = struct.unpack_from("<Q", self.d, self.o)[0]
        self.o += 8
        return v

    def f32s(self, n):
        v = struct.unpack_from("<%df" % n, self.d, self.o)
        self.o += 4 * n
        return v

    def string(self):
        n = self.u64()
        if n > 1 << 20:
            raise ValueError("string of %d at 0x%x" % (n, self.o - 8))
        s = self.d[self.o:self.o + n]
        self.o += n
        return s.decode("latin1")


class Walk:
    def __init__(self, d):
        self.r = R(d)
        self.d = d
        self.poly = {}        # poly id -> class name
        self.objs = {}        # object id -> (kind, dict)
        self.nodes = []
        self.textures = {}

    def poly_id(self):
        v = self.r.u32()
        if v & FLAG:
            name = self.r.string()
            self.poly[v & ~FLAG] = name
            return v & ~FLAG, name
        return v, self.poly.get(v, "?%d" % v)

    def texture(self):
        v = self.r.u32()
        if v & FLAG:
            tid = v & ~FLAG
            at = self.r.o
            w, h, fmt = self.r.u32(), self.r.u32(), self.r.u32()
            self.r.string()
            n = self.r.u32()
            data_off = self.r.o
            self.r.o += n
            self.textures[tid] = dict(w=w, h=h, fmt=fmt, data_off=data_off, len=n, at=at)
            return tid, True
        return v, False

    def body(self, cls, oid):
        r = self.r
        if cls == "Bitmap":
            sym = r.u32(); name = r.string(); w, h = r.u32(), r.u32()
            tid, new = self.texture()
            return dict(sym=sym, name=name, w=w, h=h, tex=tid, new=new)
        if cls == "Text":
            sym = r.u32(); name = r.string()
            rect = r.f32s(4); rgba = r.f32s(4)
            f1, f2 = r.u8(), r.u8()
            align = r.u32(); spacing = r.f32s(2)
            text = r.string(); font = r.u32()
            n = r.u64()
            fonts = [(r.string(), r.u32()) for _ in range(n)]
            n2 = r.u64()
            tails = [(r.u32(), r.u8(), r.u32()) for _ in range(n2)]
            return dict(sym=sym, name=name, rect=rect, rgba=rgba, align=align, spacing=spacing,
                        text=text, font=font, fonts=fonts, tails=tails, flags=(f1, f2))
        if cls == "Sprite":
            sym = r.u32(); name = r.string(); frames = r.u32()
            n = r.u64()
            kids = [self.node() for _ in range(n)]
            z = r.u64()
            nl = r.u64()
            labels = [(r.string(), r.u32()) for _ in range(nl)]
            return dict(sym=sym, name=name, frames=frames, kids=kids, z=z, labels=labels)
        if cls == "Shape":
            sym = r.u32(); name = r.string(); geom = r.f32s(5)
            v = r.u32()
            if v & FLAG:
                b = self.body("Bitmap", v & ~FLAG)
                self.objs[v & ~FLAG] = ("Bitmap", b)
            else:
                b = self.objs.get(v, ("Bitmap", None))[1]
            return dict(sym=sym, name=name, geom=geom, bitmap=b)
        if cls == "Video":
            from pinball_decryptor.plugins.stern import video_bank as VB
            rr = VB._Reader(self.d); rr.o = r.o
            ids = []
            name, w, h, vm = VB._video(rr, {}, ids)
            r.o = rr.o
            return dict(name=name, w=w, h=h, clips=len(vm.entries))
        raise ValueError("no body walker for class %r at 0x%x" % (cls, r.o))

    def component(self):
        r = self.r
        start = r.u32()
        pid, cls = self.poly_id()
        v = r.u32()
        oid = v & ~FLAG
        if v & FLAG:
            b = self.body(cls, oid)
            self.objs[oid] = (cls, b)
            return dict(start=start, cls=cls, oid=oid, new=True, body=b)
        return dict(start=start, cls=cls, oid=oid, new=False, body=self.objs.get(oid, (cls, None))[1])

    def node(self):
        r = self.r
        at = r.o
        v = r.u32()
        ptr = v & ~FLAG
        name = r.string()
        flag = r.u32()
        nk = r.u64()
        kf = [struct.unpack_from("<IB", self.d, r.o + 5 * i) for i in range(nk)]
        r.o += 5 * nk
        nl = r.u64()
        colors = []          # colour-transform track: (frame, mul rgba, add rgba)
        for _ in range(nl):
            fr = r.u32(); m = r.f32s(4); a = r.f32s(4); colors.append((fr, m, a))
        nt = r.u64()
        tracks = []
        for _ in range(nt):
            key = r.u32(); m = r.f32s(16); tracks.append((key, m))
        nc = r.u64()
        comps = [self.component() for _ in range(nc)]
        fm = r.u64()
        if fm:
            raise ValueError("node %s at 0x%x has a frame map of %d" % (name, at, fm))
        nd = dict(at=at, ptr=ptr, name=name, flag=flag, kf=kf, tracks=tracks, colors=colors, comps=comps, end=r.o)
        self.nodes.append(nd)
        return nd

    def run(self):
        r = self.r
        assert r.u8() == 1
        n = r.u64()
        lib = []
        for i in range(n):
            at = r.o
            key = r.u32()
            pid, cls = self.poly_id()
            if cls == "Font":
                # scene_write._walk_font walks from the entry's key
                k, span, face, end, w = SW._walk_font(self.d, at, variants=True)
                r.o = end
                lib.append(("Font", face, at))
                continue
            v = r.u32(); oid = v & ~FLAG
            if v & FLAG:
                b = self.body(cls, oid)
                self.objs[oid] = (cls, b)
            lib.append((cls, oid, at))
        z1 = r.u64()
        if z1:
            raise ValueError("library tail is %d, not 0, at 0x%x" % (z1, r.o - 8))
        stage_at = r.o
        w, h = r.u32(), r.u32(); fps = r.f32s(1)[0]; rgba = r.f32s(4)
        root = self.body("Sprite", 0)
        return dict(lib=lib, stage=(w, h, fps, rgba, stage_at), root=root, end=r.o)


def show(nd, depth, out):
    comps = ",".join("%s%s" % (c["cls"], "" if c["new"] else "*") for c in nd["comps"])
    vis = "".join("%d%s" % (f, "v" if v else "h") for f, v in nd["kf"])
    tr = " ".join("@%d(%.0f,%.0f s%.2f)" % (k, m[12], m[13], m[0]) for k, m in nd["tracks"][:3])
    extra = ""
    for c in nd["comps"]:
        b = c["body"]
        if c["cls"] == "Text" and b:
            extra += ' "%s"' % b["text"]
        if c["cls"] == "Bitmap" and b:
            extra += " %dx%d tex%d" % (b["w"], b["h"], b["tex"])
        if c["cls"] == "Sprite" and b and b["labels"]:
            extra += " labels=%s" % [(n, f) for n, f in b["labels"]]
    out.append("%s%s [%s] kf=%s %s%s" % ("  " * depth, nd["name"], comps, vis, tr, extra))
    for c in nd["comps"]:
        if c["cls"] == "Sprite" and c["new"]:
            for k in c["body"]["kids"]:
                show(k, depth + 1, out)


if __name__ == "__main__":
    d = open(sys.argv[2], "rb").read()
    w = Walk(d)
    try:
        res = w.run()
        print("WALKED to 0x%x of 0x%x  (%s)" % (res["end"], len(d), "EXACT" if res["end"] == len(d) else "SHORT"))
        print("library:", [(e[0], e[1]) for e in res["lib"]])
        print("stage:", res["stage"][:3], "root frames", res["root"]["frames"], "labels", res["root"]["labels"])
        print("nodes", len(w.nodes), "textures", len(w.textures), "poly", w.poly)
        if "--tree" in sys.argv:
            out = []
            for k in res["root"]["kids"]:
                show(k, 0, out)
            print("\n".join(out))
    except Exception as e:
        print("STOPPED at 0x%x of 0x%x: %r" % (w.r.o, len(d), e))
        print("nodes so far", len(w.nodes), "poly", w.poly)
        for nd in w.nodes[-3:]:
            print("  last node", nd["name"], hex(nd["at"]))
