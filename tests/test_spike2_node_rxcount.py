"""hwshim.c counts each node board's received frames for the `ff` poll (PAD-249).

The game counts every ADDRESSED frame it sends a board (james_bond_le 1.06,
0x5a8068: [0x8b8c88 + 900 + (node & 31) * 4] += 1) and, at the `ff` status
poll, compares that count with word A of the reply (0x5ae930). A mismatch sets
bit 31 of word B, which is in the fault mask 0x8010211f, so the board is
re-initialised and event 135 re-homes every encoder motor on it. The rig used
to answer 0, which mismatched at every service visit: every board re-inited
every ~0.7 s on every title, and james_bond_le's jetpack re-homed each time.

nb_rx_count_tx() now counts what the game counts. This compiles the REAL
function out of hwshim.c (text extracted, never copied) and feeds it frames.
What is worth failing on:

  * ONLY ADDRESSED FRAMES COUNT - byte 0 with 0x80. The `00` poll and the
    unaddressed broadcasts (`0a 00`, `03 00`, `07 01 01`) are not counted by
    the game, and counting them would put word A permanently ahead.
  * THE NODE IS byte 0 & 31, as the game indexes its table.
  * cmd f1 (reset stats) ZEROES the count - the game zeroes its own right
    after sending one (0x5ab2d4) - but not for node 0, which it skips.
  * PAD_NB_RXCOUNT=0 is the comparison run's switch.
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


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _extract(name):
    """One static function's definition, brace-counted out of hwshim.c."""
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
    m = re.search(r"^static unsigned nb_rx_count\[32\];$", _src(), re.M)
    assert m, "the frame counter's declaration moved - update this test"
    return m.group(0)


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>

static unsigned char nb_req[256];
static int nb_req_len;

%s

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 'c') {                     /* c<node> - print the count */
            printf("C %%s %%u\n", s + 1, nb_rx_count[atoi(s + 1) & 31]);
        } else {                               /* a frame on the wire */
            nb_req_len = 0;
            while (s[0] && s[1] && nb_req_len < 256) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                nb_req[nb_req_len++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            if (nb_rx_count_on()) nb_rx_count_tx();
        }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("nbrx")
    body = chr(10).join([_state(), _extract("nb_rx_count_on"),
                         _extract("nb_rx_count_tx")])
    src = d / "rx.c"
    src.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("rx.exe" if os.name == "nt" else "rx")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's counter did not compile:\n" + r.stderr
    return str(exe)


def _counts(cbin, steps, **env):
    e = dict(os.environ)
    e.pop("PAD_NB_RXCOUNT", None)
    e.update(env)
    r = subprocess.run([cbin] + steps, capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return [int(line.split()[2]) for line in r.stdout.splitlines()
            if line.startswith("C ")]


#: james_bond_le 1.06, node 9, as sent (rig trace 2026-09-28).
POLL52 = "890352002206"
CFG51 = "89155100410000434200c04241200028010000000000bf00"
FF = "8902ff760a"


def test_addressed_frames_count(cbin):
    assert _counts(cbin, [POLL52, CFG51, POLL52, FF, "c9"]) == [4]


def test_polls_and_broadcasts_do_not(cbin):
    """`00`, `0a 00`, `03 00`, `07 01 01` carry no node: the game skips them."""
    assert _counts(cbin, ["00", "0a00", "0300", "070101", POLL52, "c9"]) == [1]


def test_each_board_has_its_own_count(cbin):
    assert _counts(cbin, [POLL52, POLL52, "8c02ff730a", "c9", "c12"]) == [2, 1]


def test_node_is_the_low_five_bits(cbin):
    """0xa9 and 0x89 are both node 9 to the game's 32-slot table."""
    assert _counts(cbin, ["a90352002206", POLL52, "c9"]) == [2]


def test_reset_stats_zeroes_a_board(cbin):
    """f1 to node 9: the game zeroes its count after sending it; so must we."""
    assert _counts(cbin, [POLL52, POLL52, "8902f17600", "c9",
                          POLL52, "c9"]) == [0, 1]


def test_reset_stats_to_node_zero_zeroes_nothing(cbin):
    """0x5ab2c4 skips node 0 - the `80 02 f1` frame leaves every count alone."""
    assert _counts(cbin, [POLL52, "8002f18d00", "c9", "c0"]) == [1, 1]


def test_off(cbin):
    assert _counts(cbin, [POLL52, POLL52, "c9"], PAD_NB_RXCOUNT="0") == [0]
