"""PAD-530: a mode's clip comes back after one of the game's (clip v2, James Bond 1.06).

Jim-Beam's own Bond mode plays a video as long as the mode. When the game put a short clip of its own on the one
video surface in the middle of it (Ball Lock, Extra Ball), the mode's video was gone for good and the game's main-play
video played for the rest of the mode. Now the runtime notes how far into the clip it was when the game's clip took the
surface, and once the game's clip is over (the game asks for its main-play video, or the surface is idle) puts it back
where it would be by then, with the surface's own seek - what the game does for its own film reels (PAD-456). The code
is lifted from the runtime and run over a fake surface whose clips have lengths and a position.
"""

import re

import pytest

from tests.test_spike2_mode_roster import RUNTIME, _host_run, _lift

PORTS = RUNTIME.parent / "ports"

PRELUDE = r"""
#include <stdio.h>
#include <string.h>
#define PM_CAN_CLIPS 0x4u
struct pm_mode { const char *name; };
static const struct pm_mode mode_a = { "A" }, mode_b = { "B" };
static const struct pm_mode *current, *running, *clip_owner;
static unsigned begun;
static unsigned can = PM_CAN_CLIPS;
static int clip_v2 = 1, clip_layer, clip_layer_in;
static struct { int on, seen; unsigned long started, last; } clip;
static volatile int disp_clip_ours, disp_clip_lost;
static char disp_clip_name[96];
static unsigned long now_ms = 1000;
static unsigned long pm_ms(void) { return now_ms; }
static void say(const char *f, ...) {}
static int str_eq(const char *a, const char *b) { return a && b && !strcmp(a, b); }
static const char *idle_text = "MainPlayLoop";
static const char *pm_port_text(const char *n) { return !strcmp(n, "backdrop_idle") ? idle_text : 0; }
static long pm_port_value(const char *n, long fallback) { return !strcmp(n, "surface_playing") ? 2 : fallback; }
static unsigned data(const char *n) { return 0; }
static void *clip_layer_video(void) { return 0; }
static void clip2_show(int on) {}
static char strs[8][96];
static int nstr;
static unsigned std_string(const char *s) { char *d = strs[nstr++ % 8]; strcpy(d, s); return (unsigned)(unsigned long)d; }

/* the bank's surface: one clip at a time, each with its length; the position runs from its play (or seek) */
static int surf_obj, other_obj;
static int state;                                  /* 2 = playing */
static char video[96];
static unsigned long played_at;
static long long offset;
static int seek_ok = 1;
static void *clip2_surface(void) { return &surf_obj; }
static long long length_of(const char *v)
{
    if (!strcmp(v, "PadMode_long_Clip")) return 40000;
    if (!strncmp(v, "MainPlayLoop", 12)) return 60000;
    if (!strcmp(v, "LeftRamp")) return 2000;
    if (!strcmp(v, "BondWomen_007_Loop")) return 8000;
    return 3000;
}
static long long position(void *s) { return state == 2 ? offset + (long long)(now_ms - played_at) : 0; }
static long long duration(void *s) { return state == 2 ? length_of(video) : 0; }
static void ck_seen(unsigned *r);
static void ck_play_seen(unsigned *r);
static int looping;
static int set_video(void *s, unsigned *str)
{
    static unsigned held;                          /* (a 32-bit game passes its own: low, as the hook's words are) */
    unsigned r[2];
    held = *str;
    r[0] = (unsigned)(unsigned long)s;
    r[1] = (unsigned)(unsigned long)&held;
    ck_seen(r);                                    /* the hook: it sees every ask, ours too */
    if (s != &surf_obj) return 1;
    strcpy(video, (const char *)(unsigned long)*str);
    state = 0;
    return strcmp(video, "Nope") != 0;
}
static int play(void *s, int a, int b)
{
    unsigned r[2] = { (unsigned)(unsigned long)s, (unsigned)a };
    ck_play_seen(r);                               /* the surface_play hook: its second argument is the loop flag */
    printf("PLAY %s%s\n", video, a ? " (looped)" : "");
    state = 2; played_at = now_ms; offset = 0; looping = a;
    return 1;
}
static int seek(void *s, long long ms) { if (!seek_ok) return 0; printf("SEEK %lld\n", ms); offset = ms; played_at = now_ms; return 1; }
static int get_state(void *s) { return state; }
static unsigned fn(const char *n)
{
    if (!strcmp(n, "surface_set_video")) return (unsigned)(unsigned long)set_video;
    if (!strcmp(n, "surface_play")) return (unsigned)(unsigned long)play;
    if (!strcmp(n, "surface_state")) return (unsigned)(unsigned long)get_state;
    if (!strcmp(n, "surface_seek")) return (unsigned)(unsigned long)seek;
    if (!strcmp(n, "surface_duration")) return (unsigned)(unsigned long)duration;
    if (!strcmp(n, "surface_position")) return (unsigned)(unsigned long)position;
    return 0;
}
"""

MAIN = r"""
static void tick(unsigned long ms)
{
    now_ms += ms;
    if (clip.on && state != 2) clip.on = 0;        /* clip_tick: the surface is idle */
    ck_tick();
    if (state == 2 && !looping && position(&surf_obj) >= length_of(video)) state = 0;   /* its end */
}
static void game(const char *name)                 /* the game puts a clip of its own on the surface */
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 0, -1);
}
static void game_loop(const char *name)            /* ... and one it loops (a background) */
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 1, -1);
}
static void begin(const struct pm_mode *m) { current = running = m; begun++; }
int main(void)
{
    ck_can = 1;
    begin(&mode_a);
    pm_clip("PadMode_long_Clip");                  /* the mode's video, 20 s */
    tick(16); tick(5000);
    game("BallLock");                              /* 5 s in: the game's 3 s clip */
    tick(1000); tick(1000);                        /* it plays: left alone */
    tick(1000);
    game("MainPlayLoop_DrNo");                     /* its end: the game's main-play video */
    tick(16);                                      /* ours back where it would be: ~8 s */
    tick(2000);
    game("LeftRamp");                              /* another, and this time the surface goes idle after it */
    tick(1000); tick(1000); tick(16);
    printf("on %d\n", clip.on);
    game("Something"); game("MainPlayLoop_DrNo");  /* two of the game's in a row: back once */
    tick(16); tick(16);
    printf("-- Bond Women: a start clip once, then a loop for as long as the game's multiplier runs\n");
    tick(2000);
    game("BondWomenStart_Honey"); tick(1000); tick(1000); tick(500);
    game_loop("BondWomen_007_Loop");
    tick(1000); tick(1000); printf("waits %d\n", !clip.on || ck.lost); tick(1000); tick(16);
    printf("on %d\n", clip.on);
    game("BondWomen_007Scoring_2X"); tick(16);      /* a scoring clip over ours: waited out */
    tick(3000); tick(16);
    printf("-- the mode ends under the game's clip\n");
    game("BallLock"); tick(1000);
    running = 0;
    tick(16); game("MainPlayLoop_DrNo"); tick(16); tick(16);
    printf("-- its time runs out under the game's clip\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16); tick(38000);
    game("BallLock"); tick(3000); game("MainPlayLoop_DrNo"); tick(16); tick(16);
    printf("-- it plays to its end\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16);
    for (int k = 0; k < 41; k++) tick(1000);
    game("MainPlayLoop_DrNo"); tick(16); tick(16);
    printf("-- another of ours began\n");
    pm_clip("PadMode_long_Clip"); tick(16); tick(2000);
    game("BallLock"); tick(1000);
    begin(&mode_b); tick(16);
    game("MainPlayLoop_DrNo"); tick(16);
    printf("-- the seek is refused\n");
    pm_clip("PadMode_long_Clip"); tick(16); tick(2000);
    game("BallLock"); seek_ok = 0; game("MainPlayLoop_DrNo"); tick(16);
    printf("on %d\n", clip.on);
    printf("-- another scene's surface is none of ours\n");
    seek_ok = 1; begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16); tick(2000);
    { unsigned str = std_string("Elsewhere"); set_video(&other_obj, &str); }
    tick(16); tick(1000);
    printf("done\n");
    return 0;
}
"""


def _ck_struct(src):
    m = re.search(r"#define CK_END_MS.*?\n\} ck;\nstatic int ck_can, ck_ours, ck_in, sv_ck, ck_play_hooked;\n", src, re.S)
    assert m
    return m.group(0)


def test_a_modes_clip_comes_back_where_it_would_be_after_the_games(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_ck_struct(src)] + [_lift(src, s) for s in (
        "static long long ck_ms(const char *which, void *surf)", "static int ck_mode_runs(void)",
        "static void ck_drop(const char *why)", "static int clip2_start(void *surf, const char *name)",
        "static void ck_seen(unsigned *r)", "static void ck_play_seen(unsigned *r)", "static void ck_tick(void)\n{", "int pm_clip(const char *name)")]
    out = _host_run(tmp_path, PRELUDE + "\n".join(parts) + MAIN, flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    seeks = [int(x.split()[1]) for x in out if x.startswith("SEEK ")]
    out = [x if not x.startswith("SEEK ") else "SEEK" for x in out]
    assert out == [
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo",
        "PLAY PadMode_long_Clip", "SEEK",                     # back after the game's clip, at ~8 s
        "PLAY LeftRamp", "PLAY PadMode_long_Clip", "SEEK",    # the surface idle after the game's: back again
        "on 1",
        "PLAY Something", "PLAY MainPlayLoop_DrNo", "PLAY PadMode_long_Clip", "SEEK",
        "-- Bond Women: a start clip once, then a loop for as long as the game's multiplier runs",
        "PLAY BondWomenStart_Honey",                          # once: waited out
        "PLAY BondWomen_007_Loop (looped)", "waits 1",        # its loop: one pass, at most 3 s
        "PLAY PadMode_long_Clip", "SEEK", "on 1",
        "PLAY BondWomen_007Scoring_2X",                       # a scoring clip: waited out
        "PLAY PadMode_long_Clip", "SEEK",                     # 3 s, its end: the surface idle
        "-- the mode ends under the game's clip",
        "PLAY BallLock", "PLAY MainPlayLoop_DrNo",            # never back: its mode ended
        "-- its time runs out under the game's clip",
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo",
        "-- it plays to its end",
        "PLAY PadMode_long_Clip", "PLAY MainPlayLoop_DrNo",
        "-- another of ours began",
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo",
        "-- the seek is refused",
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo", "PLAY PadMode_long_Clip",
        "on 1",                                               # from its start, rather than not at all
        "-- another scene's surface is none of ours",
        "PLAY PadMode_long_Clip", "done"]
    # where it would be by then: 5 s in, 3 s of the game's clip -> ~8 s; then ~10 s + 2 s idle wait; then on
    assert 8000 <= seeks[0] <= 8100
    assert 12000 <= seeks[1] <= 12200
    assert seeks[2] > seeks[1]
    # Bond Women: back 3 s into the 8 s loop, 2 + 2.5 + 3 s after the last return: where it would be by then
    assert seeks[3] - seeks[2] >= 2000 + 2500 + 3000


def test_the_runtime_hooks_it_on_clip_v2_with_the_ports_seek_only():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _lift(src, "static void ck_arm(void)")
    assert '"surface_seek", "surface_duration", "surface_position"' in arm and "!clip_v2" in arm
    assert 'hook(fn("surface_play"), on_surface_play)' in arm and src.count('hook(fn("surface_play")') == 1
    assert "ck_arm();" in src and "ck_tick();" in _lift(src, "static void clip_tick(void)")
    one = _lift(src, "static void on_surface_set_video(unsigned *r)")
    assert one.index("ck_seen(r)") < one.index("on_clipv_set_video(r)")   # before a variant swaps the name
    assert src.count('hook(fn("surface_set_video")') == 1                  # a site takes one hook
    # the backdrop's own asks of the surface are ours, not a clip of the game's
    assert "ck_ours = 1;" in _lift(src, "static void bd2_play(void *surf)")


@pytest.mark.parametrize("port, seek, length, where", [
    ("james_bond_le-1.06.port", "0x00578404", "0x005780bc", "0x00578260"),
    ("james_bond_pro-1.06.port", "0x00574d5c", "0x00574a14", "0x00574bb8"),
])
def test_both_bond_builds_name_the_surfaces_seek_and_the_main_play_video(port, seek, length, where):
    text = (PORTS / port).read_text(encoding="utf-8")
    assert re.search(r"^site surface_seek\s+%s 0xe92d43f0 0xe1a07003$" % seek, text, re.M)
    assert re.search(r"^site surface_duration\s+%s 0xe5d030d4 0xe92d40f0$" % length, text, re.M)
    assert re.search(r"^site surface_position\s+%s 0xe5d030d4 0xe92d40f0$" % where, text, re.M)
    assert re.search(r"^text backdrop_idle MainPlayLoop$", text, re.M)
