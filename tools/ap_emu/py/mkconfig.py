"""mkconfig.py <launcher folder> <out.yaml> <sdl lib dir> [<game folder>] - the
rig's config.yaml.  <game folder> is where the game runs (and its assets/
lives) when that is not the launcher's folder.

procgame reads ../local_config/config.yaml (relative to the folder the game
starts in) ahead of ./config.yaml and ~/.pyprocgame/config.yaml, so the rig
writes its own there and never edits the game's.  It starts from the title's
shipped config.yaml when there is one (Houdini and Oktoberfest ship their
developers' desktop config: asset paths, key map) and sets what makes it run
on a PC: the game's FakePinPROC, the desktop (pySDL2) display in a window at
0,0, the machine's 1366x768 LCD unless the title says otherwise.
"""
import os
import sys
import yaml

src = os.path.join(sys.argv[1], "config.yaml")
cfg = {}
if os.path.exists(src):
    cfg = yaml.safe_load(open(src)) or {}
cfg.update({
    "pinproc_class": "procgame.fakepinproc.FakePinPROC",
    "use_desktop": True,
    "use_virtual_dmd_only": True,
    "dmd_fullscreen": False,
    "dmd_window_border": False,
    "screen_position_x": 0,
    "screen_position_y": 0,
    "PYSDL2_DLL_PATH": sys.argv[3],
})
# Asset folders, for a title that ships no config.yaml (the machine's lived
# outside the package): where this build keeps them, the way Houdini's own
# config.yaml says it - SkeletonGame's defaults (assets/fonts/, assets/sound/)
# are not where AP put them.
here = sys.argv[4] if len(sys.argv) > 4 else sys.argv[1]


def first(*subs):
    for s in subs:
        if os.path.isdir(os.path.join(here, s)):
            return "./" + s + "/"
    return None


for key, subs in (("dmd_path", ("assets/dmd", "assets/screen")),
                  ("sound_path", ("assets/sound", "assets/sounds")),
                  ("hdfont_dir", ("assets/dmd/fonts", "assets/screen/fonts", "assets/fonts")),
                  ("hdfont_path", ("assets/dmd/fonts", "assets/screen/fonts", "assets/fonts")),
                  ("font_path", ("assets/dmd/fonts", "assets/screen/fonts", "assets/fonts")),
                  ("lampshow_path", ("assets/lampshows",))):
    if key not in cfg and first(*subs):
        cfg[key] = first(*subs)

# The dot-grid picture the desktop draws the DMD through: on the machine
# config it points at assets/dmd/ (LoV ships none and dies on "./").
grid = cfg.get("dmd_grid_path")
if not (grid and os.path.isdir(os.path.join(here, grid))):
    dmd = os.path.join(here, "assets", "dmd")
    if os.path.isdir(dmd) and any(f.startswith("dmdgrid") for f in os.listdir(dmd)):
        cfg["dmd_grid_path"] = "./assets/dmd/"
    else:
        # None in the build (Hot Wheels): draw without the dot filter.
        cfg["dmd_dot_filter"] = False
# The OSC switch-matrix server is the developers' desktop input; it binds a
# fixed port (9000), so a second slot's game dies on it.  sw.py is the input.
cfg.setdefault("default_modes", {})
cfg["default_modes"]["osc_input"] = False
# An A/V-controller title (AP_AVC=1: its launcher sets USING_AVCONTROLLER)
# hands the screen and sound to apiav: SkeletonGame does that when its own HD
# display is off.
if os.environ.get("AP_AVC") == "1":
    # The stock modes draw on that HD display; AP's own (ApiLib) replace them.
    for mode in ("dmd", "score_display", "bonus_tally", "service_mode", "attract"):
        cfg["default_modes"][mode] = False
    # The desktop window then only shows the boot splash, over apiav's screen:
    # park it off the display (the desktop itself stays - it owns SDL).
    cfg["screen_position_x"] = 4000
# A visible run (AP_VISIBLE=1) is a window on somebody's desktop: framed, so
# it can be moved; the machine's (and a hidden run's) is borderless at 0,0.
if os.environ.get("AP_VISIBLE") == "1":
    cfg["dmd_window_border"] = True
cfg.setdefault("dmd_dots_w", 1366)
cfg.setdefault("dmd_dots_h", 768)
cfg.setdefault("desktop_dmd_scale", 1)
cfg.setdefault("dmd_framerate", 30)          # read with no default in places (LoV)
out = sys.argv[2]
if not os.path.isdir(os.path.dirname(out)):
    os.makedirs(os.path.dirname(out))
with open(out, "w") as f:
    yaml.safe_dump(cfg, f, default_flow_style=False)
print("%s (%s)" % (out, "from the title's config.yaml" if os.path.exists(src) else "rig defaults"))
