"""hwshim.c's node-board motor: the car john_wick_le screeched for (PAD-237).

David, 2026-09-01: "when i start a game, i continually hear car tire screeches.
I believe this is because the CarMec is supposed to move into position when
the game starts, and it is not getting the feedback that it needs."

The car is a motor the NODE BOARD runs. The game configures it (cmd 51: which
input is the stop switch at each end), sends it to an end (cmd 53 or 54) and
polls the board (cmd 52) until that end's switch reads made. Nothing moved the
switches and the reply to cmd 52 said both ends were made at once, so the game
sent the move again every ~0.9 s for ever - and every send plays the screech.

hwshim.c now plays the car: motor_note() reads the config and the moves off
the wire, motor_tick() lands the car at the end it was sent to. This compiles
those REAL functions out of hwshim.c (the text is extracted, never copied here)
with the switch write and the clock stubbed, and feeds them the frames
john_wick_le 1.01.0 actually sent (rig 2 trace, 2026-09-27). What is worth
failing on:

  * WHICH END IS WHICH. cmd 53 must stop on the config's FIRST switch (CAR
    MOTOR HOME, input 4) and cmd 54 on the SECOND (CAR MOTOR AWAY, input 3).
    Measured on the rig: a reply showing HOME made ended the 53 retries and
    AWAY made the 54 ones. Swapped, the car goes to the wrong end and the game
    retries exactly as before.
  * THE END IT LEAVES OPENS AT ONCE, the end it is sent to closes only after
    the travel time. A car at both ends at once is the state that caused this.
  * A RE-SEND WHILE TRAVELLING IS NOT A NEW MOVE. The game repeats the command
    while the car has not arrived; restarting the clock on each would mean it
    never arrives if the travel time were ever longer than the repeat.
  * PAD_NB_MOTOR=0 moves nothing, which is the comparison run's switch.

Skipped where there is no C compiler, which is most Windows checkouts; it runs
in WSL and anywhere with cc/gcc, which is where the shim is built anyway.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "tools", "spike2_emu", "hwshim.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]

#: john_wick_le 1.01.0, node 9, as sent (PAD_NB_TRACE=1, 2026-09-27).
CONFIG = "8915510044430f000000d051520000800000000000008800"   # cmd 51, motor 0
HOME = "89075300fa14c8004700"                                  # cmd 53
AWAY = "89075400fa14c8004600"                                  # cmd 54
#: The same config on motor 1 of node 10, to see nothing is pinned to 9/0.
OTHER = "8a15510145420f000000d051520000800000000000008700"


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _extract(name):
    """One static function's text, brace-counted out of hwshim.c.

    The DEFINITION, not the forward declaration above it: a match with a `;`
    before its first `{` is a prototype and is skipped.
    """
    src = _src()
    m = None
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            m = c
            break
    assert m, "%s not found in hwshim.c - did it get renamed?" % name
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


def _state():
    """The model's own declarations: #define NB_MOTORS .. the nb_motors array."""
    src = _src()
    m = re.search(r"^#define NB_MOTORS.*?^static struct nb_motor nb_motors\[.*?;$",
                  src, re.M | re.S)
    assert m, "the motor state declarations moved - update this test"
    return m.group(0)


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char nb_motor_cfg[64];
static unsigned long now_ms;
static unsigned long pad_ms(void) { return now_ms; }
static void logmsg(const char *s) { (void)s; }
static void motor_switch(unsigned nid, int bit, int made)
{
    printf("E %%lu %%u %%d %%d\n", now_ms, nid, bit, made ? 1 : 0);
}

%s

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 't') {                  /* t<ms>:<node> - clock, then tick */
            char *e;
            now_ms = strtoul(s + 1, &e, 10);
            motor_tick((unsigned)strtoul(e + 1, 0, 10));
        } else {                            /* f<hex> - a frame on the wire   */
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            motor_note(f, n);
        }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("nbmotor")
    body = chr(10).join([_state(), _extract("nb_motor_on"), _extract("motor_ms"),
                         _extract("motor_say"), _extract("motor_tick"),
                         _extract("motor_note")])
    src = d / "motor.c"
    src.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("motor.exe" if os.name == "nt" else "motor")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's motor did not compile:\n" + r.stderr
    return str(exe)


def _run(cbin, steps, **env):
    """The switch edges the model makes, as (ms, node, input, made)."""
    e = dict(os.environ)
    e.pop("PAD_NB_MOTOR", None)
    e.pop("PAD_MOTOR_MS", None)
    e.update(env)
    r = subprocess.run([cbin] + steps, capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return [tuple(int(x) for x in line.split()[1:])
            for line in r.stdout.splitlines() if line.startswith("E ")]


def test_home_is_the_first_stop_switch(cbin):
    """cmd 53 lands on input 4 (CAR MOTOR HOME), 600 ms after it was sent."""
    edges = _run(cbin, ["t1000:9", "f" + CONFIG, "f" + HOME,
                        "t1599:9", "t1600:9"])
    # Sent at 1000, from BETWEEN the stops: nothing to leave, so the only
    # edge is the arrival, and not a millisecond early.
    assert edges == [(1600, 9, 4, 1)]


def test_away_opens_home_then_makes_away(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "t5000:9", "f" + AWAY, "t5599:9", "t5600:9"])
    assert edges == [(600, 9, 4, 1),        # home
                     (5000, 9, 4, 0),       # leaves home at once
                     (5600, 9, 3, 1)]       # reaches away after the travel


def test_never_at_both_ends(cbin):
    """The fault itself: HOME and AWAY made together is what kept it retrying."""
    steps = ["t0:9", "f" + CONFIG]
    t = 0
    for cmd in [HOME, AWAY, HOME, AWAY, AWAY, HOME]:
        t += 1000
        steps += ["t%d:9" % t, "f" + cmd]
        for dt in (100, 300, 599, 600, 900):
            steps.append("t%d:9" % (t + dt))
    made = {3: 0, 4: 0}
    for _ms, _node, bit, level in _run(cbin, steps):
        made[bit] = level
        assert not (made[3] and made[4]), "the car is at both ends at once"


def test_a_resend_while_travelling_is_not_a_new_move(cbin):
    """The game repeats the move until it sees the car arrive."""
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + AWAY,
                        "t300:9", "f" + AWAY, "t500:9", "f" + AWAY,
                        "t600:9", "t900:9"])
    assert edges == [(600, 9, 3, 1)]


def test_a_move_to_where_it_already_is_moves_nothing(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "t2000:9", "f" + HOME, "t3000:9"])
    assert edges == [(600, 9, 4, 1)]


def test_turned_round_mid_travel(cbin):
    """Sent home while still on its way away: it goes home, nothing half-made."""
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "t1000:9", "f" + AWAY, "t1200:9", "f" + HOME,
                        "t1700:9", "t1800:9"])
    assert edges == [(600, 9, 4, 1), (1000, 9, 4, 0), (1800, 9, 4, 1)]


def test_no_config_no_car(cbin):
    """A move for a motor the game never configured is not ours to play."""
    assert _run(cbin, ["t0:9", "f" + HOME, "t5000:9"]) == []


def test_travel_time_knob(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t249:9", "t250:9"],
                 PAD_MOTOR_MS="250")
    assert edges == [(250, 9, 4, 1)]


def test_off_moves_nothing(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "f" + AWAY, "t1200:9"], PAD_NB_MOTOR="0")
    assert edges == []


def test_node_and_motor_come_from_the_frame(cbin):
    """Node 10 motor 1, stops 5 and 2: nothing about john_wick is hard-coded."""
    edges = _run(cbin, ["t0:10", "f" + OTHER,
                        "f8a075301fa14c8004600", "t600:10"])
    assert edges == [(600, 10, 5, 1)]
