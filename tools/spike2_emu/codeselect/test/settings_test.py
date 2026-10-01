#!/usr/bin/env python3
"""QEMU=qemu-arm-static settings_test.py ROOT BIN T [FONT]

PAD-307: the SETTINGS tile and its Color correction screen, driven through the
rig's keyboard file the way padglhost presses buttons - by name (the cab[]
bytes at 1068), so no switch table is needed.

  1. walk  - the tile is the last card; START on it opens Settings, START again
             opens Color correction on the first adjustable image; a middle-
             shades value is changed (+2 steps), saved for THIS game, and the
             values file holds exactly that line; BACK, BACK TO THE GAMES, and
             the countdown - which never runs inside Settings - boots the card
             the menu opened on, never the tile.
  2. all   - "Save for every game" puts one set on both adjustable images.
  3. hold  - a flipper HELD while a value is being changed repeats the step.
  4. idle  - nothing pressed inside Settings: it closes by itself
             (PAD_SETTINGS_IDLE_MS) and the countdown boots a game.
  5. apply - --apply-color writes a copy of a program whose pad_cp numbers are
             the saved ones (the same template shader_profile.py writes), refuses
             one whose pad_cp is in the old shape, and says "nothing to do" for
             an image with no line.

The emulator comes from the environment ($QEMU), never argv: the rig's teardown
does pkill -f 'arm-binfmt|qemu-arm' and this script's command line must not
match it."""
import os
import re
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmedia  # noqa: E402

MAGIC = 0x53444150
OFF_CAB = 1068
CAB_IDX = {"left": 0, "right": 1, "start": 2, "action": 3, "select": 4,
           "plus": 5, "minus": 6, "back": 7}

CONF = """image=p3|STERN STOCK|original Stern code|art0.png||
image=p7:img1|TMNT 1987|upscaled cartoon retheme|art1.png|anim1.gif|
image=p7:img2|TMNT 1987 BW|black and white edition|art0.png||
color_profile=1|1.10 1.20 1.35|1.00 1.00 1.00|0.00 0.00 0.00|0.90|Recommended
color_profile=2|1.00 1.00 1.00|1.00 1.00 1.00|0.00 0.00 0.00|0.00|Black and white
default=1
timeout=4
"""

# the template every pad_cp is written in (shader_profile.py TUNABLE_TEMPLATE)
TEMPLATE = ("c=mix(vec3(dot(c,vec3(0.299,0.587,0.114))),c,########);"
            "c=pow(clamp(c*vec3(########,########,########),0.0,1.0),"
            "vec3(########,########,########));"
            "c=vec3(########,########,########)+(vec3(1.0)-vec3(########,########,########))*c;")


def fail(msg, *more):
    print("settings_test: FAIL %s" % msg)
    for m in more:
        print(m)
    raise SystemExit(1)


def pad_cp(sat, gain, gamma, lift):
    out = TEMPLATE
    for v in (sat,) + gain + gamma + lift + lift:
        out = out.replace("#" * 8, "%.6f" % v, 1)
    return ("highp vec4 pad_cp(highp vec4 f){highp float a=f.a;highp vec3 c=clamp(f.rgb,0.0,1.0);"
            + out + "return vec4(c,a);}")


def main():
    root, binp, t = sys.argv[1:4]
    qemu = os.environ.get("QEMU", "qemu-arm-static")
    font = sys.argv[4] if len(sys.argv) > 4 and os.path.isfile(sys.argv[4]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    t = os.path.join(t, "settings")
    os.makedirs(t, exist_ok=True)
    media = os.path.join(t, "media")
    mkmedia.make(media)
    conf = os.path.join(t, "settings.conf")
    with open(conf, "w") as f:
        f.write(CONF)
    no_list = os.path.join(t, "no_such_table_dir", "switch_list.txt")

    def run(name, presses, env=None, hold=None, timeout=4, wait=0.0):
        """presses: button names (or (name, hold seconds)); returns (rc, out, err, values)"""
        values = os.path.join(t, name + ".color")
        choice = os.path.join(t, name + ".choice")
        last = os.path.join(t, name + ".last")
        for p in (values, choice, last):
            if os.path.exists(p):
                os.unlink(p)
        sw = os.path.join(t, name + ".padsw")
        with open(sw, "wb") as f:
            f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.Popen([qemu, "-L", root, binp, "--headless", os.path.join(t, name + ".ppm"),
                              "--conf", conf, "--input", "padsw", "--padsw", sw, "--tables", no_list,
                              "--timeout", str(timeout), "--out", choice, "--last", last,
                              "--log", os.path.join(t, name + ".log"), "--font", font, "--no-invert",
                              "--media", media, "--audio", "none", "--color-file", values],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
        time.sleep(1.2)
        for press in presses:
            button, held = (press, 0.15) if isinstance(press, str) else press
            with open(sw, "r+b") as f:
                f.seek(OFF_CAB + CAB_IDX[button])
                f.write(b"\x01")
            time.sleep(held)
            with open(sw, "r+b") as f:
                f.seek(OFF_CAB + CAB_IDX[button])
                f.write(b"\x00")
            time.sleep(0.45)
        time.sleep(wait)
        try:
            o, err = p.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            p.kill()
            o, err = p.communicate()
            fail("(%s) codeselect did not exit" % name, o, err)
        vals = open(values).read() if os.path.exists(values) else None
        ch = open(choice).read().strip() if os.path.exists(choice) else None
        return p.returncode, o, err, vals, ch

    def lines_of(vals):
        return [ln for ln in (vals or "").splitlines() if ln and not ln.startswith("#")]

    # 1. walk: card 1 (the default) -> RIGHT RIGHT = the tile (card 4 of 4)
    walk = ["right", "right", "start",          # the tile opens Settings
            "start",                            # Color correction, on image 1
            "right", "right",                   # GAME, START FROM, -> MIDDLE SHADES red
            "start", "right", "right", "start",  # +2 steps: 1.10 -> 1.20
            "left", "left", "left", "left", "left",   # 2 -> 1 -> 0 -> 12 -> 11 -> 10 = SAVE
            "start",
            "right", "right", "start",          # 10 -> 12 = BACK (nothing unsaved)
            "right", "start"]                   # BACK TO THE GAMES
    rc, o, e, vals, ch = run("walk", walk)
    for want in ("[select] settings: open",
                 "[select] settings: color correction, 2 adjustable images, on image 1 (TMNT 1987)",
                 "[select] color: image 1 (TMNT 1987) saved: 1.2000 1.2000 1.3500|1.0000 1.0000 1.0000|"
                 "0.0000 0.0000 0.0000|0.9000",
                 "[select] settings: left color correction",
                 "[select] settings: back to the games",
                 "[select] settings: closed"):
        if want not in o:
            fail("(walk) no %r" % want, o, e)
    if "countdown expired: booting card 2 (the settings tile is highlighted" not in e:
        fail("(walk) the countdown did not boot the card the menu opened on", o, e)
    if rc != 0 or ch != "1" or "[select] chose 1 TMNT 1987" not in o:
        fail("(walk) rc %s choice %r" % (rc, ch), o, e)
    if lines_of(vals) != ["p7:img1|1.2000 1.2000 1.3500|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.9000"]:
        fail("(walk) the values file holds %r" % vals)

    # 2. all: START FROM -> Black and white (3 steps: As built, Recommended, No change, B&W),
    # then SAVE FOR EVERY GAME
    allg = ["right", "right", "start", "start",
            "right", "start", "right", "right", "right", "start",   # START FROM -> Black and white
            "left", "left", "left",            # 1 -> 0 -> 12 -> 11 = SAVE FOR EVERY GAME
            "start",
            "right", "start",                  # 12 = BACK
            "right", "start"]
    rc, o, e, vals, ch = run("all", allg)
    got = sorted(lines_of(vals))
    want = ["p7:img1|1.0000 1.0000 1.0000|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.0000"]
    # image 2 was BUILT black and white: its line is dropped, it boots as built
    if got != want:
        fail("(all) the values file holds %r, expected %r" % (got, want), o, e)
    if "image 2 (TMNT 1987 BW) saved: 1.0000 1.0000 1.0000|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.0000 " \
       "(as built: no line in the values file)" not in o:
        fail("(all) image 2 not saved as built", o)

    # 3. hold: change the red middle shades and HOLD the right flipper 1.5 s
    hold = ["right", "right", "start", "start", "right", "right", "start",
            ("right", 1.5), "start",
            "left", "left", "left", "left", "left", "start",          # SAVE
            "right", "right", "start", "right", "start"]
    rc, o, e, vals, ch = run("hold", hold)
    m = re.search(r"saved: (\d\.\d+) ", o)
    if not m:
        fail("(hold) nothing saved", o, e)
    if float(m.group(1)) < 1.10 + 5 * 0.05 - 1e-6:
        fail("(hold) a 1.5 s hold moved red only to %s (expected at least 5 steps)" % m.group(1), o)

    # 4. idle: into Color correction, change something, then press nothing
    rc, o, e, vals, ch = run("idle", ["right", "right", "start", "start", "right", "right", "start", "right"],
                             env={"PAD_SETTINGS_IDLE_MS": "3000"}, wait=6)
    if "[select] settings: nothing pressed for 3 s: back to the games, unsaved changes dropped" not in o:
        fail("(idle) Settings did not close by itself", o, e)
    if rc != 0 or ch != "1" or vals is not None:
        fail("(idle) rc %s choice %r values %r" % (rc, ch, vals), o, e)

    # 5. apply: a synthetic program with three pad_cp in the template, one stock string
    prog = os.path.join(t, "game")
    blob = (b"\x7fELF" + b"\x00" * 60 + b"stock text void main(){}\x00" * 50
            + b"".join(pad_cp(0.9, (1.0, 1.0, 1.0), (1.1, 1.2, 1.35), (0.0, 0.0, 0.0)).encode()
                       + b"\x00" * 7 for _k in range(3)) + b"tail" * 64)
    with open(prog, "wb") as f:
        f.write(blob)
    os.chmod(prog, 0o755)
    values = os.path.join(t, "apply.color")
    with open(values, "w") as f:
        f.write("p7:img1|1.30 1.20 1.35|0.95 1 1|0.02 0.02 0.02|1.10\n")
    out = os.path.join(t, "game.out")

    def apply(image, program=prog):
        if os.path.exists(out):
            os.unlink(out)
        r = subprocess.run([qemu, "-L", root, binp, "--apply-color", "--conf", conf, "--image", str(image),
                            "--program", program, "--to", out, "--color-file", values],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.returncode, r.stdout

    rc, o = apply(1)
    if rc != 0 or "3 color function(s) rewritten" not in o:
        fail("(apply) rc %d" % rc, o)
    new = open(out, "rb").read()
    if len(new) != len(blob) or (os.stat(out).st_mode & 0o777) != 0o755:
        fail("(apply) the copy is %d bytes mode %o" % (len(new), os.stat(out).st_mode & 0o777))
    expect = blob.replace(pad_cp(0.9, (1.0, 1.0, 1.0), (1.1, 1.2, 1.35), (0, 0, 0)).encode(),
                          pad_cp(1.1, (0.95, 1.0, 1.0), (1.3, 1.2, 1.35), (0.02, 0.02, 0.02)).encode())
    if new != expect:
        fail("(apply) the copy differs from the expected bytes")
    rc, o = apply(2)
    if rc != 1 or "nothing set on this machine" not in o or os.path.exists(out):
        fail("(apply) image 2 with no line: rc %d" % rc, o)
    rc, o = apply(0)
    if rc != 1 or "no adjustable color profile" not in o:
        fail("(apply) image 0: rc %d" % rc, o)
    # the v1.60 shape (no lift statement): refused, nothing left behind
    old = os.path.join(t, "game.old")
    with open(old, "wb") as f:
        f.write(blob.replace(b"c=vec3(0.000000,0.000000,0.000000)+(vec3(1.0)-vec3(0.000000,0.000000,0.000000))*c;",
                             b"", 1))
    rc, o = apply(1, old)
    if rc != 2 or "in the adjustable shape" not in o or os.path.exists(out):
        fail("(apply) the old shape: rc %d" % rc, o)
    print("settings_test: OK (walk, save for every game, a held flipper, the idle exit, --apply-color)")


if __name__ == "__main__":
    main()
