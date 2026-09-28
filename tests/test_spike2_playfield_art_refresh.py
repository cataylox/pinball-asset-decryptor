"""The cached playfield drawing follows the build's own drawing (PAD-236).

`<tables>/<game>/playfield.png` is keyed by title only, and mktables used to
copy it only when it was missing - so a second build of one title that ships a
different drawing kept the first build's picture for ever, under device
positions rebuilt against the new one. A PNG cannot carry the `# binary:` line
that protects device_xy.txt, so the comparison is against the source art.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _build(monkeypatch, tmp_path, art):
    import gameinfo
    import mktables
    monkeypatch.setattr(gameinfo, "find_playfield_art", lambda game=None: str(art))
    said = []
    mktables.build("testtitle", say=said.append)
    return tmp_path / "tables" / "testtitle" / "playfield.png", said


@pytest.fixture
def rig_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_TABLES", str(tmp_path / "tables"))
    monkeypatch.setenv("PAD_GAME", "testtitle")
    (tmp_path / "tables").mkdir()
    return tmp_path


def test_a_second_build_with_a_different_drawing_replaces_the_cached_one(
        monkeypatch, rig_env):
    first = rig_env / "first.png"
    first.write_bytes(b"\x89PNG first build's drawing")
    dest, _ = _build(monkeypatch, rig_env, first)
    assert dest.read_bytes() == first.read_bytes()

    # Same size, different bytes: a size-only test would keep the old one.
    second = rig_env / "second.png"
    second.write_bytes(b"\x89PNG secnd build's drawing")
    assert second.stat().st_size == first.stat().st_size
    dest, said = _build(monkeypatch, rig_env, second)
    assert dest.read_bytes() == second.read_bytes(), \
        "the first build's drawing survived a build that ships another one"
    assert any("artwork" in s and "second.png" in s for s in said)


def test_the_same_drawing_stays_cached(monkeypatch, rig_env):
    art = rig_env / "art.png"
    art.write_bytes(b"\x89PNG one drawing")
    _build(monkeypatch, rig_env, art)
    _, said = _build(monkeypatch, rig_env, art)
    assert any("artwork" in s and "(cached)" in s for s in said)
