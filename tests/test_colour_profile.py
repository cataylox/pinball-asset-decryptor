"""PAD-305: the colour profile a build applies to the user's replacement
pictures and videos (core/colour_profile.py), and where staging applies it."""

import os
import subprocess

import pytest

from pinball_decryptor.core import colour_profile as cp

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")


@pytest.fixture
def profile_on(tmp_path, monkeypatch):
    path = tmp_path / "colour_profile.txt"
    monkeypatch.setenv(cp.ENV_FILE, str(path))
    monkeypatch.setenv(cp.ENV, "1")
    return path


def _ramp(mode="RGB"):
    im = PIL.new(mode, (64, 4))
    px = im.load()
    for x in range(64):
        for y in range(4):
            v = x * 4
            px[x, y] = ((v, v // 2, 255 - v, 100 + y) if mode == "RGBA"
                        else (v, v // 2, 255 - v))
    return im


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


def test_off_by_default_and_identity_is_inactive(tmp_path, monkeypatch):
    monkeypatch.setenv(cp.ENV_FILE, str(tmp_path / "p.txt"))
    monkeypatch.delenv(cp.ENV, raising=False)
    assert cp.active() is None
    monkeypatch.setenv(cp.ENV, "1")
    (tmp_path / "p.txt").write_text("name = flat\n", encoding="utf-8")
    assert cp.active() is None


def test_missing_file_is_created_from_the_default(profile_on):
    assert not profile_on.exists()
    prof = cp.active()
    assert profile_on.read_text(encoding="utf-8") == cp.DEFAULT_TEXT
    assert prof == cp.parse(cp.DEFAULT_TEXT)[0]


def test_apply_image_keeps_alpha_and_size():
    prof, _ = cp.parse(cp.DEFAULT_TEXT)
    src = _ramp("RGBA")
    out = prof.apply_image(src)
    assert out.mode == "RGBA" and out.size == src.size
    assert out.getchannel("A").tobytes() == src.getchannel("A").tobytes()
    assert out.convert("RGB").tobytes() != src.convert("RGB").tobytes()


def test_ffmpeg_filters_match_pillow(tmp_path):
    from pinball_decryptor.core.video import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    prof, _ = cp.parse(cp.DEFAULT_TEXT)
    src = _ramp()
    src.save(tmp_path / "in.png")
    r = subprocess.run([ff, "-y", "-loglevel", "error",
                        "-i", str(tmp_path / "in.png"),
                        "-vf", ",".join(prof.ffmpeg_filters()
                                        + ["format=rgb24"]),
                        str(tmp_path / "out.png")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    a = np.asarray(prof.apply_image(src), int)
    b = np.asarray(PIL.open(tmp_path / "out.png").convert("RGB"), int)
    assert np.abs(a - b).max() <= 3


def test_image_staging_applies_it_once_from_the_source(tmp_path, profile_on):
    from pinball_decryptor.core.image_slots import ImageSlot, stage_replacement
    from pinball_decryptor.core.image import detect_image_info
    slot_file = tmp_path / "slot.png"
    PIL.new("RGB", (64, 4), (0, 0, 0)).save(slot_file)
    rep = tmp_path / "mine.png"
    _ramp().save(rep)
    slot = ImageSlot(rel_path="slot.png", abs_path=str(slot_file), ext=".png",
                     info=detect_image_info(str(slot_file)),
                     size=os.path.getsize(slot_file), probed=True)
    want = cp.active().apply_image(_ramp()).tobytes()
    for _ in range(2):                  # a second build must not stack it
        ok, detail = stage_replacement(slot, str(rep))
        assert ok, detail
        assert "Recommended" in detail
        assert PIL.open(slot_file).convert("RGB").tobytes() == want
    # the user's own file is untouched
    assert PIL.open(rep).convert("RGB").tobytes() == _ramp().tobytes()


def test_image_staging_without_it_is_unchanged(tmp_path, monkeypatch):
    from pinball_decryptor.core.image_slots import ImageSlot, stage_replacement
    from pinball_decryptor.core.image import detect_image_info
    monkeypatch.setenv(cp.ENV, "0")
    slot_file = tmp_path / "slot.png"
    PIL.new("RGB", (64, 4)).save(slot_file)
    rep = tmp_path / "mine.png"
    _ramp().save(rep)
    slot = ImageSlot(rel_path="slot.png", abs_path=str(slot_file), ext=".png",
                     info=detect_image_info(str(slot_file)),
                     size=os.path.getsize(slot_file), probed=True)
    ok, _ = stage_replacement(slot, str(rep))
    assert ok
    assert PIL.open(slot_file).convert("RGB").tobytes() == _ramp().tobytes()


def test_scene_added_picture_is_left_to_the_shaders(tmp_path, profile_on,
                                                     monkeypatch):
    """Spike 2 corrects what the game draws in its shaders (PAD-305
    shader_profile), so a picture added in Scenes is NOT corrected as a file
    as well: that would apply the profile twice."""
    from pinball_decryptor.plugins.stern import scene_edit
    p = tmp_path / "pic.png"
    _ramp().convert("RGBA").save(p)
    on = scene_edit._texture_from_png(str(p))
    monkeypatch.setenv(cp.ENV, "0")
    off = scene_edit._texture_from_png(str(p))
    assert on == off

def test_video_staging_reencodes_a_matching_clip(tmp_path, profile_on,
                                                 monkeypatch):
    """A clip that already matches its slot is normally copied through; with
    the profile on it has to be re-encoded, with the filters on the line."""
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
    ok, detail = video_slots.stage_replacement(slot, str(rep))
    assert ok, detail
    assert seen.get("colour") is not None
    assert slot_file.read_bytes() == b"x"


def test_video_filter_chain_carries_the_profile(tmp_path, profile_on,
                                                monkeypatch):
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
        colour=cp.active())
    assert ok, detail
    assert "Recommended" in detail
    assert out.stat().st_size > 0


# -- the file round trip, the emulator's override, the signature -----------

def test_to_text_round_trips_and_keeps_the_header(tmp_path):
    prof = cp.Profile(name="Mine", gamma=(1.3, 1.1, 0.9), gain=(1, .9, 1),
                      lift=(.05, .05, .05), saturation=1.2)
    path = cp.save(prof, str(tmp_path / "m.txt"))
    text = open(path, encoding="utf-8").read()
    assert text.startswith("# Pinball Asset Decryptor colour profile")
    back, problems = cp.read_file(path)
    assert problems == [] and back == prof


def test_forced_off_wins_over_the_tick(profile_on):
    assert cp.active() is not None and cp.signature()
    with cp.forced(False):
        assert cp.active() is None and cp.signature() == ""
    assert cp.active() is not None


def test_emulator_set_rebuilds_when_the_profile_changes(tmp_path, profile_on,
                                                        monkeypatch):
    from pinball_decryptor.webui import emulate_core
    card = tmp_path / "card.raw"
    card.write_bytes(b"x")
    st = card.stat()
    manifest = {"card": {"path": str(card.resolve()), "size": st.st_size,
                         "mtime": int(st.st_mtime)},
                "assets": str(tmp_path.resolve()), "assets_fingerprint": "fp",
                "scene_edits": True, "colour_profile": cp.signature()}
    args = (manifest, str(card), str(tmp_path), "fp")
    assert emulate_core.overrides_reason(*args) == ""
    monkeypatch.setenv(cp.ENV, "0")
    assert "color profile" in emulate_core.overrides_reason(*args)


# -- the Color profile tab ---------------------------------------------------

def test_color_tab_end_to_end(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    path = tmp_path / "profile.txt"
    monkeypatch.setenv(cp.ENV_FILE, str(path))
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["color"]["visible"]
        assert tabs["color"]["group"] == "Replace"
        w.call("ui.select_tab", "color")
        w.drain()
        s = w.state("color")
        assert s["enabled"] is False
        assert s["gamma"] == [1.1, 1.2, 1.35]
        assert s["sample_url"].startswith("data:image/png;base64,")
        rev = s["rev"]

        w.call("color.set_params", {"gamma": [1.5, 1.0, 9.0], "lift": 0.1,
                                    "name": "Cab 2"})
        w.drain()
        prof, problems = cp.read_file(str(path))
        assert problems == []
        assert prof.name == "Cab 2"
        assert prof.gamma == (1.5, 1.0, 2.5)          # clamped to the slider
        assert prof.lift == (0.1, 0.1, 0.1)

        w.call("color.set_enabled", True)
        w.drain()
        assert os.environ.get(cp.ENV) == "1"
        assert "Cab 2" in w.state("write").get("colour_note", "")

        w.call("color.preset", "none")
        w.drain()
        s = w.state("color")
        assert s["rev"] > rev and s["gamma"] == [1.0, 1.0, 1.0]
        assert cp.active() is None                     # no change = nothing

        w.call("color.set_enabled", False)
        w.drain()
        assert os.environ.get(cp.ENV) == "0"
        assert w.state("write").get("colour_note", "") == ""


def test_black_and_white_preset_makes_every_pixel_grey():
    prof = dict(cp.PRESETS)["bw"]
    out = np.asarray(prof.apply_image(_ramp("RGBA")))
    assert (out[..., 0] == out[..., 1]).all() and (out[..., 1] == out[..., 2]).all()
    assert prof.ffmpeg_filters()[0].startswith("colorchannelmixer=rr=0.299")


def test_stock_colors_on_a_running_spike2_game_waits_for_the_next_start(
        tmp_path, monkeypatch):
    """PAD-305: on Spike 2 the profile lives in the game program's drawing
    shaders, compiled at boot, so flipping Stock colors while the game runs
    says it applies at the next Start and rebuilds nothing."""
    from tests.webui_harness import web_app
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setenv(cp.ENV_FILE, str(tmp_path / "profile.txt"))
    with web_app(tmp_path, mfr="stern") as w:
        cp.set_enabled(True)
        emu = w.window.service("emulate")
        built = []
        monkeypatch.setattr(engine, "write_overrides",
                            lambda *a, **k: built.append(1))
        emu._live_set = {"assets": str(tmp_path), "out": str(tmp_path / "o")}
        emu._colour_src = ("card.raw", "card.raw")
        emu._last_up = True
        w.call("ui.set", "emulate", "overrides", True)
        w.call("ui.set", "emulate", "colour_stock", True)
        w.drain()
        assert built == []
        assert "Start the game again" in w.state("emulate").get("colour_live", "")
