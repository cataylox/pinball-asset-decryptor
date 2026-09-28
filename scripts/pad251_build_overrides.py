"""PAD-251 emulator proof: an override set carrying Scenes-window tree edits on the stock
language screen (762a9b99) of Godzilla LE 1.16.

    python build_ov.py <repo> <project> <out_dir> [none]
"""
import json
import os
import sys

REPO, PROJ, OUT = sys.argv[1:4]
sys.path.insert(0, REPO)
from pinball_decryptor.plugins.stern import engine, scene_edit as X  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
trees = json.load(open(os.path.join(PROJ, "images", "scene_textures", "scene_tree.json")))
card_path = [k for k in trees if "762a9b99" in k][0]
man = trees[card_path]
idx = X._man_index(man)
by = {}
for nid, (n, _k) in idx.items():
    by.setdefault(n["name"], []).append(nid)
print(sorted(by))
ops = []
if "none" not in sys.argv:
    instr = by["LanguageInstructions_Instance"][0]
    lang = by["LanguageName_Instance"][0]
    group = by["LanguageText"][0]
    ops = [
        {"op": "move", "node": instr, "dx": 0, "dy": -260},        # instruction line up
        {"op": "scale", "node": lang, "s": 1.6, "px": 156, "py": 24},  # JAPANESE bigger
        {"op": "visible", "node": by["Line1_Instance"][0], "on": False},  # Tokyo line hidden
        {"op": "add_picture", "parent": None, "index": 99, "id": X.FIRST_ADDED_ID,
         "name": "PAD251_Picture", "image": "scene_textures/radimg_62x90_1c1433fb.png",
         "w": 62, "h": 90, "x": 1200, "y": 60},                    # a lock icon, top right
        {"op": "add_text", "parent": group, "index": 99, "id": X.FIRST_ADDED_ID + 2,
         "name": "PAD251_Text", "text": "FLAGS 0 0 RED", "x": 300, "y": -330,
         "like": instr, "rgba": [1.0, 0.2, 0.2, 1.0], "flags": [0, 0]},
        {"op": "add_text", "parent": group, "index": 99, "id": X.FIRST_ADDED_ID + 4,
         "name": "PAD251_Text2", "text": "FLAGS 1 0 RED", "x": 300, "y": -430,
         "like": instr, "rgba": [1.0, 0.2, 0.2, 1.0], "flags": [1, 0]},
        {"op": "add_text", "parent": group, "index": 99, "id": X.FIRST_ADDED_ID + 6,
         "name": "PAD251_Text3", "text": "FLAGS 1 1 RED", "x": 300, "y": -530,
         "like": instr, "rgba": [1.0, 0.2, 0.2, 1.0], "flags": [1, 1]},
        {"op": "add_text", "parent": group, "index": 99, "id": X.FIRST_ADDED_ID + 8,
         "name": "PAD251_Text4", "text": "FLAGS 0 1 RED", "x": 300, "y": -630,
         "like": instr, "rgba": [1.0, 0.2, 0.2, 1.0], "flags": [0, 1]},
        {"op": "tint", "node": X.FIRST_ADDED_ID + 2, "mul": [1.0, 0.2, 0.2, 1.0]},
        {"op": "tint", "node": X.FIRST_ADDED_ID, "mul": [0.2, 1.0, 0.2, 1.0]},
        {"op": "tint", "node": by["LanguageName_Instance"][0], "mul": [0.3, 0.6, 1.0, 1.0]},
    ]
X.save(PROJ, {card_path: ops} if ops else {})
logs = []
os.makedirs(OUT, exist_ok=True)
res = engine.write_overrides(CARD, PROJ, OUT, log=lambda m, l="info": logs.append((l, m)))
for l, m in logs:
    if l != "debug":
        print(l, m[:260])
print("RESULT", res)
