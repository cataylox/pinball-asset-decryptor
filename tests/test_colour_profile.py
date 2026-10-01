"""PAD-305: the colour profile, a staged change of the project
(core/colour_profile.py), where staging applies it off Spike 2, and the
Color profile tab."""

import os
import subprocess

import pytest

from pinball_decryptor.core import colour_profile as cp

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

RECOMMENDED = dict(cp.PRESETS)["recommended"]


@pytest.fixture
def project(tmp_path):
    """A project folder with the Recommended profile staged."""
    d = tmp_path / "proj"
    d.mkdir()
    cp.store(str(d), RECOMMENDED)
    return d


def _ramp(mode="RGB"):
    im = PIL.new(mode, (64, 4))
    px = im.load()
    for x in range(64):
        for y in range(4):
            v = x * 4
            px[x, y] = ((v, v // 2, 255 - v, 100 + y) if mode == "RGBA"
                        else (v, v // 2, 255 - v))
    return im


# -- the profile itself ----------------------------------------------------

def test_default_text_parses_clean_and_changes_something():
    prof, problems = cp.parse(cp.DEFAULT_TEXT)
    assert problems == []
    assert prof.name == "Recommended"
    assert not prof.is_identity()
    # mids come down (the machine shows them too bright), ends stay put
    for ch in range(3):
        t = prof.table(ch)
        assert t[0] == 0 and t[255] == 255
        assert t[128] < 128


def test_bad_lines_are_named_not_fatal():
    prof, problems = cp.parse("gamma = 1.2\nwobble = 3\ngain = a b c\n"
                              "lift = 2 2 2\njunk\nsaturation=0.5\n")
    assert prof.gamma == (1.2, 1.2, 1.2)           # one number = all three
    assert prof.saturation == 0.5
    assert prof.gain == (1.0, 1.0, 1.0)
    assert len(problems) == 4
    assert any("wobble" in p for p in problems)


def test_apply_image_keeps_alpha_and_size():
    src = _ramp("RGBA")
    out = RECOMMENDED.apply_image(src)
    assert out.mode == "RGBA" and out.size == src.size
    assert out.getchannel("A").tobytes() == src.getchannel("A").tobytes()
    assert out.convert("RGB").tobytes() != src.convert("RGB").tobytes()


def test_ffmpeg_filters_match_pillow(tmp_path):
    from pinball_decryptor.core.video import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    src = _ramp()
    src.save(tmp_path / "in.png")
    r = subprocess.run([ff, "-y", "-loglevel", "error",
                        "-i", str(tmp_path / "in.png"),
                        "-vf", ",".join(RECOMMENDED.ffmpeg_filters()
                                        + ["format=rgb24"]),
                        str(tmp_path / "out.png")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    a = np.asarray(RECOMMENDED.apply_image(src), int)
    b = np.asarray(PIL.open(tmp_path / "out.png").convert("RGB"), int)
    assert np.abs(a - b).max() <= 3


def test_black_and_white_preset_makes_every_pixel_grey():
    prof = dict(cp.PRESETS)["bw"]
    out = np.asarray(prof.apply_image(_ramp("RGBA")))
    assert (out[..., 0] == out[..., 1]).all() and (out[..., 1] == out[..., 2]).all()
    assert prof.ffmpeg_filters()[0].startswith("colorchannelmixer=rr=0.299")


def test_every_starting_point_says_how_it_was_made():
    assert set(cp.PRESET_TIPS) == {k for k, _p in cp.PRESETS}
    assert "photos of a display test card" in cp.PRESET_TIPS["recommended"]


def test_to_text_round_trips_and_keeps_the_header(tmp_path):
    prof = cp.Profile(name="Mine", gamma=(1.3, 1.1, 0.9), gain=(1, .9, 1),
                      lift=(.05, .05, .05), saturation=1.2)
    path = cp.save(prof, str(tmp_path / "m.txt"))
    text = open(path, encoding="utf-8").read()
    assert text.startswith("# Pinball Asset Decryptor colour profile")
    back, problems = cp.read_file(path)
    assert problems == [] and back == prof
    assert cp.to_text(RECOMMENDED) == cp.DEFAULT_TEXT


# -- a staged change of the project ------------------------------------------

def test_a_project_has_no_profile_until_one_is_staged(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    assert cp.for_project(str(d)) is None and cp.active(str(d)) is None
    cp.store(str(d), RECOMMENDED)
    assert cp.for_project(str(d)) == RECOMMENDED
    cp.store(str(d), cp.Profile(name="flat"))      # changes nothing = none
    assert cp.for_project(str(d)) is None


def test_the_profile_lives_beside_the_other_staged_changes(project):
    from pinball_decryptor.core import staged_changes
    data = staged_changes.load(str(project))
    data["image"] = {"images/a.png": "C:/x.png"}
    staged_changes.save(str(project), data)
    cp.store(str(project), dict(cp.PRESETS)["bw"])
    data = staged_changes.load(str(project))
    assert data["image"] == {"images/a.png": "C:/x.png"}
    assert data[cp.KEY]["saturation"] == 0.0


def test_forced_off_wins_over_the_project(project):
    assert cp.active(str(project)) is not None and cp.signature(str(project))
    with cp.forced(False):
        assert cp.active(str(project)) is None
        assert cp.signature(str(project)) == ""
    assert cp.active(str(project)) is not None


def test_write_lists_it_as_pending(project):
    from pinball_decryptor.webui import write_scan
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    rows = write_scan.colour_rows(SternManufacturer(), str(project))
    assert rows == [("color profile  —  Recommended, on everything the game "
                     "draws", "color", "Pending (color profile)", "pending")]
    cp.store(str(project), None)
    assert write_scan.colour_rows(SternManufacturer(), str(project)) == []


def test_emulator_set_rebuilds_when_the_profile_changes(tmp_path, project):
    from pinball_decryptor.webui import emulate_core
    card = tmp_path / "card.raw"
    card.write_bytes(b"x")
    st = card.stat()
    manifest = {"card": {"path": str(card.resolve()), "size": st.st_size,
                         "mtime": int(st.st_mtime)},
                "assets": str(project.resolve()), "assets_fingerprint": "fp",
                "scene_edits": True,
                "colour_profile": cp.signature(str(project))}
    args = (manifest, str(card), str(project), "fp")
    assert emulate_core.overrides_reason(*args) == ""
    cp.store(str(project), dict(cp.PRESETS)["bw"])
    assert "color profile" in emulate_core.overrides_reason(*args)


# -- staging, where the file correction applies (not Spike 2) -----------------

def _image_slot(tmp_path):
    from pinball_decryptor.core.image_slots import ImageSlot
    from pinball_decryptor.core.image import detect_image_info
    slot_file = tmp_path / "slot.png"
    PIL.new("RGB", (64, 4), (0, 0, 0)).save(slot_file)
    return slot_file, ImageSlot(rel_path="slot.png", abs_path=str(slot_file),
                                ext=".png",
                                info=detect_image_info(str(slot_file)),
                                size=os.path.getsize(slot_file), probed=True)


def test_image_staging_applies_the_projects_profile_once(tmp_path, project):
    from pinball_decryptor.core.image_slots import stage_replacements
    slot_file, slot = _image_slot(tmp_path)
    rep = tmp_path / "mine.png"
    _ramp().save(rep)
    want = RECOMMENDED.apply_image(_ramp()).tobytes()
    for _ in range(2):                  # a second build must not stack it
        n, fails = stage_replacements({"slot.png": slot},
                                      {"slot.png": str(rep)})
        assert n == 1 and not fails
        # no project given: no profile (the build passes its project)
        assert PIL.open(slot_file).convert("RGB").tobytes() == _ramp().tobytes()
    from pinball_decryptor.core.image_slots import stage_replacement
    ok, detail = stage_replacement(slot, str(rep), colour=cp.active(str(project)))
    assert ok and "Recommended" in detail
    assert PIL.open(slot_file).convert("RGB").tobytes() == want
    # the user's own file is untouched
    assert PIL.open(rep).convert("RGB").tobytes() == _ramp().tobytes()


def test_scene_added_picture_is_left_to_the_shaders(tmp_path, project):
    """Spike 2 corrects what the game draws in its shaders (shader_profile),
    so a picture added in Scenes is NOT corrected as a file as well."""
    from pinball_decryptor.plugins.stern import scene_edit
    p = tmp_path / "pic.png"
    _ramp().convert("RGBA").save(p)
    on = scene_edit._texture_from_png(str(p))
    cp.store(str(project), None)
    assert scene_edit._texture_from_png(str(p)) == on


def test_video_staging_reencodes_a_matching_clip(tmp_path, monkeypatch):
    """A clip that already matches its slot is normally copied through; with
    a profile it has to be re-encoded, with the filters on the line."""
    from pinball_decryptor.core import video_slots
    from pinball_decryptor.core.video import find_ffmpeg
    if not find_ffmpeg():
        pytest.skip("no ffmpeg")
    seen = {}

    def fake_transcode(src, dst, info, **kw):
        seen.update(kw)
        with open(dst, "wb") as f:
            f.write(b"x")
        return True, "re-encoded"

    monkeypatch.setattr(video_slots, "_already_matches",
                        lambda *a, **k: True)
    monkeypatch.setattr(video_slots, "_remux_verdict",
                        lambda *a, **k: (True, None))
    monkeypatch.setattr(video_slots, "transcode_video_to", fake_transcode)
    slot_file = tmp_path / "slot.mp4"
    slot_file.write_bytes(b"old")
    rep = tmp_path / "mine.mp4"
    rep.write_bytes(b"new")
    slot = video_slots.VideoSlot(
        rel_path="slot.mp4", abs_path=str(slot_file), ext=".mp4",
        info=None, size=3, probed=False)
    ok, detail = video_slots.stage_replacement(slot, str(rep),
                                               colour=RECOMMENDED)
    assert ok, detail
    assert seen.get("colour") is RECOMMENDED
    assert slot_file.read_bytes() == b"x"


def test_video_filter_chain_carries_the_profile(tmp_path):
    from pinball_decryptor.core import video
    if not video.find_ffmpeg():
        pytest.skip("no ffmpeg")
    src = tmp_path / "in.mp4"
    r = subprocess.run([video.find_ffmpeg(), "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
                        "-t", "0.5", "-pix_fmt", "yuv420p", str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = tmp_path / "out.mp4"
    ok, detail = video.transcode_video_to(
        str(src), str(out), video.detect_video_info(str(src)),
        colour=RECOMMENDED)
    assert ok, detail
    assert "Recommended" in detail
    assert out.stat().st_size > 0


# -- the Color profile tab -----------------------------------------------------

def test_color_tab_stages_on_the_project(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["color"]["visible"]
        assert tabs["color"]["group"] == "Replace"
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        s = w.state("color")
        assert s["has_project"] and s["active"] is False
        assert s["sample_url"].startswith("data:image/png;base64,")
        rev = s["rev"]

        w.call("color.preset", "recommended")
        w.drain()
        s = w.state("color")
        assert s["active"] and s["rev"] > rev and s["gamma"] == [1.1, 1.2, 1.35]
        assert cp.for_project(str(proj)) == RECOMMENDED

        w.call("color.set_params", {"gamma": [1.5, 1.0, 9.0], "lift": 0.1})
        w.drain()
        prof = cp.for_project(str(proj))
        assert prof.gamma == (1.5, 1.0, 2.5)          # clamped to the slider
        assert prof.lift == (0.1, 0.1, 0.1)

        w.call("color.preset", "none")                # No change = off
        w.drain()
        assert w.state("color")["active"] is False
        assert cp.for_project(str(proj)) is None

        # moving a slider from No change stages "My profile"
        w.call("color.set_params", {"saturation": 0.0})
        w.drain()
        assert cp.for_project(str(proj)).name == "My profile"

        # Revert all takes it away with the project's other changes
        w.window.clear_replace_assignments(str(proj))
        w.drain()
        assert cp.for_project(str(proj)) is None
        assert w.state("color")["active"] is False


def test_try_it_starts_the_emulator_with_the_profile(tmp_path, monkeypatch):
    """"Try it in the emulator" turns on the edits, takes Stock colors off and
    starts the game, or stops a running one and starts it again."""
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        emu = w.window.service("emulate")
        calls = []
        monkeypatch.setattr(emu, "start", lambda: calls.append("start"))
        monkeypatch.setattr(emu, "stop", lambda: calls.append("stop"))
        monkeypatch.setattr(emu, "_card", lambda: "card.raw")
        w.call("ui.set", "emulate", "colour_stock", True)
        w.call("color.try_emulator")
        w.drain()
        assert calls == ["start"]
        assert emu.emulate_overrides_var.get() is True
        assert emu.emulate_colour_stock_var.get() is False
        assert w.state("shell")["tab"] == "emulate"
        # a game running: stop, then start once it is down
        emu._last_up = True
        w.call("color.try_emulator")
        w.drain()
        assert calls == ["start", "stop"] and emu._restart_wait
        emu._last_up = False
        w.call("ui.select_tab", "color")
        emu._restart_when_down()
        assert calls == ["start", "stop", "start"]


def test_stock_colors_on_a_running_spike2_game_waits_for_the_next_start(
        tmp_path, monkeypatch, project):
    """On Spike 2 the profile lives in the game program's drawing shaders,
    compiled at boot, so flipping Stock colors while the game runs says it
    applies at the next Start and rebuilds nothing."""
    from tests.webui_harness import web_app
    from pinball_decryptor.plugins.stern import engine
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(project))
        emu = w.window.service("emulate")
        built = []
        monkeypatch.setattr(engine, "write_overrides",
                            lambda *a, **k: built.append(1))
        emu._live_set = {"assets": str(project), "out": str(tmp_path / "o")}
        emu._colour_src = ("card.raw", "card.raw")
        emu._last_up = True
        w.call("ui.set", "emulate", "overrides", True)
        w.call("ui.set", "emulate", "colour_stock", True)
        w.drain()
        assert built == []
        assert "Start the game again" in w.state("emulate").get("colour_live", "")


def test_staging_a_profile_changes_the_write_tabs_fingerprint(project):
    """The Write tab rescans its list only when its fingerprint moves; a
    profile staged on the Color profile tab has to move it."""
    from pinball_decryptor.webui import write_scan
    before = write_scan.fingerprint(None, str(project), 0, True)
    cp.store(str(project), dict(cp.PRESETS)["bw"])
    assert write_scan.fingerprint(None, str(project), 0, True) != before
