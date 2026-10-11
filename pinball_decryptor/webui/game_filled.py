"""The lines of text the game writes itself as it plays, so new words for them in a scene would
never show (DragonRR, PAD-513: "Where it would be pointless to change the text in the scene ...
please don't allow the user to edit the text in the scene in those instances").

Only the PROVEN rule locks a line: the game finds a box by its path from the screen's root to
write in it, so a box whose path the game program points at is written by the game
(``engine.program_node_paths``, emulator-proven on stock Godzilla LE 1.16).  A project whose card
has not been read for those paths locks nothing: the older word-matching marks are guesses, and
a guess must not stop an edit that would show.
"""

import json
import os

LOCKED_NOTE = ("The game writes this line itself as it plays (in the player's language), so "
               "words typed here would never show on the machine. Change the game's own line "
               "instead: it is a game program row on the Text tab.")

_memo = {}


def _stamp(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def known_paths(assets_dir):
    """The node paths the game program points at (``engine.program_node_paths``), or None."""
    if not assets_dir:
        return None
    try:
        from ..plugins.stern import engine
        return engine.program_node_paths(assets_dir)
    except Exception:                                   # noqa: BLE001
        return None


def locked_lines(assets_dir):
    """``{scene card path: frozenset of manifest originals}``: a scene's lines of text every box
    of which the game writes (a line some box keeps as its own words is not locked: new words
    show there).  Empty without the program's node paths.  Cached until the reading or the
    scene trees change."""
    if not assets_dir:
        return {}
    from ..core import text_manifest
    tree_file = os.path.join(assets_dir, "images", "scene_textures", "scene_tree.json")
    modes_file = os.path.join(assets_dir, text_manifest.RELDIR, "program_modes.json")
    key = (os.path.normcase(os.path.abspath(assets_dir)), _stamp(tree_file), _stamp(modes_file))
    got = _memo.get(key[0])
    if got and got[0] == key:
        return got[1]
    out = {}
    known = known_paths(assets_dir)
    if known:
        from .text_scenes_tree import _kind_of, _text_of, _walk_man
        try:
            with open(tree_file, encoding="utf-8") as f:
                trees = json.load(f)
        except (OSError, ValueError):
            trees = {}
        for card, man in trees.items():
            parent, names, lines = {}, {}, {}
            for n, p, _depth in _walk_man(man):
                parent[n["id"]] = p["id"] if p else None
                names[n["id"]] = n.get("name") or ""
                if _kind_of(man, n) != "Text":
                    continue
                words = _text_of(man, n, "Text")
                if not (words or "").strip():
                    continue
                parts, cur = [], n["id"]
                while cur is not None:
                    parts.append(names[cur])
                    cur = parent.get(cur)
                orig = text_manifest.escape_cell(words)
                lines.setdefault(orig, []).append(".".join(reversed(parts)) in known)
            done = frozenset(o for o, filled in lines.items() if all(filled))
            if done:
                out[card] = done
    _memo[key[0]] = (key, out)
    return out


def is_locked(assets_dir, row):
    """Is manifest *row* a scene line the game writes in every box (see :func:`locked_lines`)?"""
    path = row.get("path") or ""
    if not path.lower().endswith(".radium"):
        return False
    return row.get("original") in locked_lines(assets_dir).get(path, ())
