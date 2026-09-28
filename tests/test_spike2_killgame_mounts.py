"""killgame.sh finds the card mounts it must unmount in /proc/self/mounts.

It used to glob ``"$PAD_CARDS/"*/`` and test each hit with ``mountpoint``. A
card an ordinary user mounted has no ``allow_other`` (cardmount.sh adds it for
root only), so FUSE refuses root the stat the glob needs: nothing matched, the
unmount pass was skipped, and Stop ended "still running: 2" with a WSL restart
on offer. The kernel's mount list names every mount whatever its permissions.

These run the script's own ``card_mounts`` function against a written mounts
file, so they need a POSIX bash with awk (not Windows).
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
KILLGAME = os.path.join(RIG, "killgame.sh")

pytestmark = pytest.mark.skipif(not os.path.isfile(KILLGAME), reason="rig not present")


def _read():
    with open(KILLGAME, encoding="utf-8", newline="") as fh:
        return fh.read()


def _function():
    m = re.search(r"^card_mounts\(\) \{\n.*?^\}\n", _read(), re.S | re.M)
    assert m, "killgame.sh has no card_mounts() function"
    return m.group(0)


def _code(text):
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_unmount_loop_reads_the_mount_list_not_a_glob():
    code = _code(_read())
    assert 'for m in "$PAD_CARDS/"*/' not in code
    assert "done < <(card_mounts)" in code
    assert '"${1:-/proc/self/mounts}"' in _function()


#: /proc/self/mounts lines as the kernel writes them: the path is field 2,
#: octal-escaped.  {C} is the card folder.
MOUNTS = r"""fuse2fs {C}/tmnt_multi3 fuse.fuse2fs ro,nosuid,nodev,relatime,user_id=1000,group_id=1000 0 0
fuse2fs {C}/my\040card fuse.fuse2fs ro,nosuid,nodev,relatime,user_id=1000,group_id=1000 0 0
fuse2fs {C}/back\134slash fuse.fuse2fs ro 0 0
fuse2fs {C}/tmnt_multi3 fuse.fuse2fs ro 0 0
tmpfs {C}/tmnt_multi3/deeper tmpfs rw 0 0
fuse2fs {C}2/other fuse.fuse2fs ro 0 0
fuse2fs /home/someone/card/foreign fuse.fuse2fs ro 0 0
/dev/sdc / ext4 rw,relatime 0 0
"""


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash")
                    or not shutil.which("awk"), reason="needs POSIX bash + awk")
def test_card_mounts_lists_each_mount_directly_under_the_card_folder(tmp_path):
    cards = tmp_path / "card"
    cards.mkdir()
    mounts = tmp_path / "mounts"
    mounts.write_text(MOUNTS.replace("{C}", str(cards)), encoding="utf-8")
    script = _function() + 'card_mounts "$1"\n'
    r = subprocess.run(["bash", "-c", script, "x", str(mounts)],
                       env=dict(os.environ, PAD_CARDS=str(cards)),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = sorted(r.stdout.splitlines())
    assert got == sorted([str(cards / "tmnt_multi3"),   # listed twice, once out
                          str(cards / "my card"),        # \040 unescaped
                          str(cards / "back\\slash")])   # \134 unescaped


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash")
                    or not shutil.which("awk"), reason="needs POSIX bash + awk")
def test_card_mounts_follows_a_symlinked_card_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "card"
    link.symlink_to(real)
    mounts = tmp_path / "mounts"
    mounts.write_text("fuse2fs %s/game fuse.fuse2fs ro 0 0\n" % real, encoding="utf-8")
    script = _function() + 'card_mounts "$1"\n'
    r = subprocess.run(["bash", "-c", script, "x", str(mounts)],
                       env=dict(os.environ, PAD_CARDS=str(link)),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [str(real / "game")]
