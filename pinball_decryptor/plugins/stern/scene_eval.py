"""What a Spike 2 scene DRAWS at a given moment: its timeline evaluated (PAD-251).

:mod:`scene_tree` reads the file; this module turns the tree into (1) a compact JSON-able
MANIFEST the extract stores in the project folder (a project keeps pictures as PNGs, never the
scene files, so the Scenes window works from this) and (2) a DRAW LIST for one moment: every
picture and line of text on the glass, in draw order, with its absolute transform and tint.

THE TIMELINE (measured on Godzilla's Battle Select, ``tests/test_stern_scene_eval.py``):

* Every Sprite (the root included) has a frame count and a timeline; frames count from 1.
* A node is drawn at frame *f* when its last keyframe at or before *f* says visible (none yet:
  not drawn) - and so are all its ancestors.
* Its transform is its last track at or before *f* (none yet: the first).  Animations are
  baked one key per frame (Battle Select's zooming map carries a track per frame), so holding
  the last key is the reading; tweening between keys is not assumed.
* Its colour transform (``mul`` r g b a, ``add`` r g b a) is chosen the same way; it composes
  down the tree like the transform: ``mul = mul_parent * mul``, ``add = add * mul_parent +
  add_parent``.  A fade is a colour track (the tiles' 0 -> 0.25 -> ... -> 1.0).
* A nested Sprite runs its own timeline.  The game's code SEEKS a sprite that carries labels
  (``CharacterSelect_Instance``: one 15-frame state per kaiju; each tile: Locked / Completed /
  a city) and the rest play from their first visible frame, looping.  So a labelled sprite is
  held at frame 1 unless the caller pins it (``pins={node id: frame}``), and an unlabelled one
  plays.  Which state the code shows is not in the file - that is what the Scenes window's
  label picker is for.
* Draw order is file order, depth first: a later sibling draws over an earlier one.

A transform here is the 2-D affine ``(a, b, c, d, tx, ty)``: ``x' = a x + c y + tx`` and
``y' = b x + d y + ty`` (the track's column-major 4x4 at [0], [1], [4], [5], [12], [13]).
"""
from __future__ import annotations

import os

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
NO_TINT = ((1.0, 1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 0.0))
MANIFEST_VERSION = 2


# ---------------------------------------------------------------------------------------------
# the manifest (a scene_tree.Scene -> plain JSON)
# ---------------------------------------------------------------------------------------------
def _affine(m):
    return [round(float(m[i]), 5) for i in (0, 1, 4, 5, 12, 13)]


def _text(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin1")


def manifest(scene, tex2rel=None, font_of=None, asset2rel=None):
    """The JSON form of *scene* for the project folder.

    *tex2rel* maps a texture's block ``data_off`` to the PNG rel the extract wrote for it
    (``radium_images.txt``), *font_of* maps a Text's font SIZE id to ``(font key, px)`` as
    :mod:`fontrender` names fonts, *asset2rel* maps a flipbook frame's ``scene.assets`` path
    (relative to the scene's folder, e.g. ``16.asset``) to its extracted PNG rel.  Missing
    entries leave the element in the tree without a picture (``image: None``)."""
    tex2rel = tex2rel or {}
    font_of = font_of or {}
    asset2rel = asset2rel or {}
    objects = {}

    def image_of(tid):
        t = scene.textures.get(tid)
        return tex2rel.get(t["data_off"]) if t else None

    def obj(o):
        if o is None:
            return None
        key = str(o.id)
        if key in objects:
            return o.id
        objects[key] = None                         # placeholder: a Sprite's kids may recurse
        b = o.body
        k = o.kind
        if k in ("Sprite", "StreamingFlipbook"):
            out = {"kind": k, "name": b["name"], "frames": b["frames"],
                   "labels": [[n, f] for n, f in b["labels"]],
                   "kids": [node(n) for n in b["kids"]]}
            if k == "StreamingFlipbook":
                out.update(w=b["w"], h=b["h"], seq=[
                    None if fr is None else {
                        "w": fr.body["w"], "h": fr.body["h"], "index": fr.body["index"],
                        "m": _affine(fr.body["m"]),
                        "asset": scene.assets.get(fr.body["asset"], ("", 0))[0],
                        "image": asset2rel.get(scene.assets.get(fr.body["asset"], ("",))[0])}
                    for fr in b["seq"]])
        elif k == "Bitmap":
            out = {"kind": k, "w": b["w"], "h": b["h"], "tex": b["tex"],
                   "image": image_of(b["tex"])}
        elif k == "Text":
            key_px = font_of.get(b["font"])
            size = scene.font_sizes.get(b["font"]) or {}
            out = {"kind": k, "text": _text(b["text"]), "rect": [round(v, 3) for v in b["rect"]],
                   "rgba": [round(v, 4) for v in b["rgba"]], "align": b["align"],
                   "spacing": [round(v, 3) for v in b["spacing"]], "font_id": b["font"],
                   "font_name": b["fonts"][0][0] if b["fonts"] else "",
                   "font": key_px[0] if key_px else "", "font_px": key_px[1] if key_px else 0,
                   "ascent": round(size.get("ascent", 0.0), 3),
                   "line": round(size.get("line", 0.0), 3),
                   # a styled game-font VARIANT (GameFont_Primary ...) draws its atlas's own
                   # colours: the Text's rgba is ignored (emulator, every flag combination);
                   # the node's colour track still tints it
                   "styled": bool(size.get("variant"))}
        elif k == "Shape":
            out = {"kind": k, "rect": [round(v, 3) for v in b["rect"]],
                   "fill": obj(b["bitmap"])}
        elif k == "Video":
            out = {"kind": k, "name": b["name"], "w": b["w"], "h": b["h"],
                   "clips": [c for c, _i in b["clips"]]}
        elif k == "Spine":
            out = {"kind": k, "name": b["name"]}
        else:
            out = {"kind": k}
        objects[key] = out
        return o.id

    def node(n):
        return {"id": n.id, "name": n.name,
                "kf": [[f, v] for f, v in n.keyframes],
                "col": [[f, [round(x, 5) for x in m], [round(x, 5) for x in a]]
                        for f, m, a in n.colors],
                "tr": [[f, _affine(m)] for f, m in n.tracks],
                "comps": [[c.start, obj(c.obj)] for c in n.components]}

    root = {"frames": scene.root["frames"],
            "labels": [[n, f] for n, f in scene.root["labels"]],
            "kids": [node(n) for n in scene.root["kids"]]}
    w, h, fps, rgba = scene.stage
    return {"v": MANIFEST_VERSION, "stage": [w, h, fps, list(rgba)], "root": root,
            "objects": objects}


def font_sizes(scene, data, images, tables, off2rel):
    """``{font size id: (fontrender key, px)}``: each size object of the scene's fonts
    matched to the glyph table that follows it (:func:`radium.parse_glyph_tables`), named the
    way the extract names it (the stem of the table's first atlas PNG)."""
    from . import radium as _radium
    by_off = sorted((t["table_off"], t) for t in tables or ())
    out = {}
    for sid, info in scene.font_sizes.items():
        after = [t for off, t in by_off if off >= info["offset"]]
        if not after:
            continue
        t = after[0]
        atl = next((g["atlas"]["data_off"] for g in t["glyphs"] if g.get("atlas")), None)
        rel = off2rel.get(atl) if atl is not None else None
        if not rel:
            continue
        out[sid] = (os.path.splitext(os.path.basename(rel))[0], _radium.table_size_px(t))
    return out


# ---------------------------------------------------------------------------------------------
# the timeline
# ---------------------------------------------------------------------------------------------
def _at(entries, f, first_if_none=False):
    """The entry of *entries* (``[[frame, value], ...]``, frame-sorted as stored) in force at
    frame *f*: the last whose frame is <= f."""
    got = None
    for e in entries:
        if e[0] <= f:
            got = e
        else:
            break
    if got is None and first_if_none and entries:
        got = entries[0]
    return got


def visible_at(node, f):
    e = _at(node["kf"], f)
    return bool(e and e[1])


def transform_at(node, f):
    e = _at(node["tr"], f, first_if_none=True)
    return tuple(e[1]) if e else IDENTITY


def tint_at(node, f):
    e = _at(node["col"], f)
    return (tuple(e[1]), tuple(e[2])) if e else NO_TINT


def compose(p, m):
    """Parent affine *p* then local *m*: the local's frame expressed on the glass."""
    a, b, c, d, tx, ty = p
    a2, b2, c2, d2, tx2, ty2 = m
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * tx2 + c * ty2 + tx, b * tx2 + d * ty2 + ty)


def compose_tint(p, t):
    (pm, pa), (m, a) = p, t
    return (tuple(pm[i] * m[i] for i in range(4)),
            tuple(a[i] * pm[i] + pa[i] for i in range(4)))


def first_visible(node):
    for f, v in node["kf"]:
        if v:
            return f
    return 1


def draw_list(man, frame=None, pins=None, hidden=(), origin=(0.0, 0.0), matrix=None,
              worlds=None, _settled=None):
    """Every picture and line of text *man* draws at root frame *frame* (default:
    :func:`default_frame`), in draw order.  *pins* ``{node id: frame}`` seeks a nested sprite
    (what the game's code does with labels); *hidden* node ids are not drawn (what code
    hides).

    Each draw is a dict: ``kind`` (``bitmap`` / ``text`` / ``flip`` / ``video`` / ``spine``),
    ``node`` (id), ``path`` (names from the root), ``m`` (affine on the glass), ``mul`` /
    ``add`` (tint), and the element's own fields (``image``, ``w``, ``h`` for pictures;
    ``text``, ``rect``, ``align``, ``rgba``, ``font``, ``font_px``, ``spacing`` for text).

    *worlds*, when a dict, receives ``{node id: (parent affine, node affine)}`` for every node
    drawn at that moment - what an editor needs to turn a drag on the glass into the node's own
    units (:func:`to_parent`)."""
    if frame is None:
        frame = default_frame(man)
    # a labelled sprite's resting frame is found by drawing it (settled_frame), and nested
    # labelled sprites would be re-settled at every level: one memo per call keeps it linear
    settled = {} if _settled is None else _settled
    pins = pins or {}
    hidden = set(hidden or ())
    objects = man["objects"]
    out = []
    base = (tuple(matrix) if matrix is not None and len(matrix) == 6
            else (1.0, 0.0, 0.0, 1.0, float(origin[0]), float(origin[1])))

    def run(kids, f, world, tint, path):
        for n in kids:
            if n["id"] in hidden or not visible_at(n, f):
                continue
            w = compose(world, transform_at(n, f))
            t = compose_tint(tint, tint_at(n, f))
            if worlds is not None:
                worlds[n["id"]] = (world, w)
            here = path + [n["name"]]
            for start, oid in n["comps"]:
                o = objects.get(str(oid))
                if o is None or start > f:
                    continue
                emit(n, o, w, t, here, f)

    def local_frame(n, o, f):
        frames = max(1, int(o.get("frames") or 1))
        if n["id"] in pins:
            return max(1, min(frames, int(pins[n["id"]])))
        if o.get("labels"):
            key = (id(o), tuple(round(v, 1) for v in w_of[n["id"]]))
            if key not in settled:
                settled[key] = settled_frame(man, o, world=w_of[n["id"]], _settled=settled)
            return settled[key]
        return (f - first_visible(n)) % frames + 1

    w_of = {}

    def emit(n, o, w, t, path, f):
        k = o["kind"]
        common = {"node": n["id"], "path": path, "m": w, "mul": t[0], "add": t[1]}
        if k in ("Sprite", "StreamingFlipbook"):
            w_of[n["id"]] = w
            lf = local_frame(n, o, f)
            if k == "StreamingFlipbook" and o.get("seq"):
                fr = o["seq"][(lf - 1) % len(o["seq"])]
                if fr is not None:
                    out.append(dict(common, kind="flip", m=compose(w, tuple(fr["m"])),
                                    image=fr.get("image"), w=fr["w"], h=fr["h"]))
            run(o.get("kids") or (), lf, w, t, path)
        elif k == "Bitmap":
            out.append(dict(common, kind="bitmap", image=o.get("image"), w=o["w"], h=o["h"]))
        elif k == "Shape":
            fill = objects.get(str(o.get("fill"))) if o.get("fill") is not None else None
            x, y, rw, rh = o["rect"]
            if fill is not None and fill.get("w") and fill.get("h"):
                sx, sy = rw / float(fill["w"]), rh / float(fill["h"])
                out.append(dict(common, kind="bitmap", image=fill.get("image"),
                                w=fill["w"], h=fill["h"],
                                m=compose(w, (sx, 0.0, 0.0, sy, x, y))))
        elif k == "Text":
            out.append(dict(common, kind="text", text=o["text"], rect=o["rect"],
                            align=o["align"], rgba=o["rgba"], font=o.get("font", ""),
                            font_px=o.get("font_px", 0), font_name=o.get("font_name", ""),
                            spacing=o.get("spacing", [0, 0]), ascent=o.get("ascent", 0),
                            line=o.get("line", 0), styled=o.get("styled", False)))
        elif k == "Video":
            out.append(dict(common, kind="video", name=o["name"], w=o["w"], h=o["h"]))
        elif k == "Spine":
            out.append(dict(common, kind="spine", name=o["name"]))

    run(man["root"]["kids"], frame, base, NO_TINT, [])
    return out


def on_glass(d, stage):
    """True when draw *d* lands (at least its centre) on the stage and is not transparent."""
    if d["mul"][3] <= 0.99:
        return False
    a, b, c, dd, tx, ty = d["m"]
    if d["kind"] == "text":
        L, T, R, B = (list(d.get("rect") or (0, 0, 0, 0)) + [0] * 4)[:4]
        cx, cy = (L + R) / 2.0, (T + B) / 2.0
    else:
        cx, cy = float(d.get("w") or 0) / 2.0, float(d.get("h") or 0) / 2.0
    x, y = a * cx + c * cy + tx, b * cx + dd * cy + ty
    return 0 <= x <= stage[0] and 0 <= y <= stage[1]


def _score(man, drawn):
    stage = man.get("stage") or (1360, 768)
    return sum(1 for d in drawn if on_glass(d, stage))


_SETTLE_TRIES = 40


def settled_frame(man, o, world=None, _settled=None):
    """The frame a labelled sprite rests on when nothing seeks it: within its FIRST label's
    span, the frame where the most of its elements are fully drawn (Battle Select's kaiju
    picker: frame 4, ``Ebirah_FadeIn_End``, not frame 1 where the tile is still transparent)."""
    labels = sorted(f for _n, f in o.get("labels") or ())
    if not labels:
        return 1
    lo = labels[0]
    hi = next((f for f in labels if f > lo), int(o.get("frames") or lo) + 1)
    best, best_n = lo, -1
    span = list(range(lo, max(lo + 1, hi)))
    if len(span) > _SETTLE_TRIES:
        # a long first span (a 2,460-frame idle loop) is sampled, not walked frame by frame
        step = len(span) / float(_SETTLE_TRIES)
        span = sorted({span[int(i * step)] for i in range(_SETTLE_TRIES)})
    for f in span:
        sub = {"objects": man["objects"], "stage": man.get("stage"),
               "root": {"kids": o.get("kids") or (), "frames": 1, "labels": []}}
        n = _score(sub, draw_list(sub, f, origin=world or (0.0, 0.0), matrix=world,
                                  _settled=_settled))
        if n > best_n:
            best, best_n = f, n
    return best


def invert(m):
    a, b, c, d, tx, ty = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(ia * tx + ic * ty), -(ib * tx + id_ * ty))


def apply(m, x, y):
    a, b, c, d, tx, ty = m
    return a * x + c * y + tx, b * x + d * y + ty


def to_parent(parent, dx, dy):
    """A move of (dx, dy) on the glass in the units of a node whose parent is drawn by
    *parent*: the parent's linear part inverted (its translation cancels)."""
    inv = invert(parent)
    if inv is None:
        return dx, dy
    a, b, c, d, _tx, _ty = inv
    return a * dx + c * dy, b * dx + d * dy


def outline(d):
    """The four corners of draw *d* on the glass (a picture's box, a text's rect)."""
    if d["kind"] == "text":
        L, T, R, B = (list(d.get("rect") or (0, 0, 0, 0)) + [0] * 4)[:4]
    else:
        L, T, R, B = 0.0, 0.0, float(d.get("w") or 0), float(d.get("h") or 0)
    return [apply(d["m"], x, y) for x, y in ((L, T), (R, T), (R, B), (L, B))]


def label_frames(man):
    """``{label: frame}`` of the root timeline, frame-ordered."""
    return dict(sorted(((n, f) for n, f in man["root"]["labels"]), key=lambda kv: kv[1]))


def seekable(man):
    """Every nested sprite the game's code can seek, as ``[(node id, path, [(label,
    frame)], frames)]`` in draw order: what the Scenes window offers per sprite."""
    out = []
    objects = man["objects"]

    def run(kids, path):
        for n in kids:
            here = path + [n["name"]]
            for _s, oid in n["comps"]:
                o = objects.get(str(oid)) or {}
                if o.get("kind") in ("Sprite", "StreamingFlipbook"):
                    if o.get("labels"):
                        out.append((n["id"], here, [tuple(x) for x in o["labels"]],
                                    o.get("frames", 1)))
                    run(o.get("kids") or (), here)

    run(man["root"]["kids"], [])
    return out


def default_frame(man):
    """The root frame a still preview shows: the first frame at which the most elements are
    on the glass - a screen's resting state, after its fade-in and before its fade-out (Battle
    Select: frame 45, ``OverlayFadeIn_End``).  Only frames where some node changes are tried."""
    frames = max(1, int(man["root"].get("frames") or 1))
    cands = {1}
    for _l, f in man["root"]["labels"]:
        cands.add(f)
    for n in man["root"]["kids"]:
        for f, _v in n["kf"]:
            cands.add(f)
        for e in n["col"]:
            cands.add(e[0])
    best, best_n = 1, -1
    settled = {}
    for f in sorted(c for c in cands if 1 <= c <= frames):
        score = _score(man, draw_list(man, f, _settled=settled))
        if score > best_n:
            best, best_n = f, score
    return best
