"""Key-frame spacing as part of what a replacement clip must match (PAD-298).

Every song video on a Spike 2 Metallica card has a key frame every 4 frames.
A replacement with one every 60 matched the slot on everything the app used
to check, was copied onto the card as-is, and played stuttering while the
whole machine slowed down.  The slot's short spacing is now a ceiling for a
copy-through and for the build's intact copy, and conversions reproduce it.
"""

import os
import subprocess

import pytest

from pinball_decryptor.core import video
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_quality import keyframe_interval


def _have_ff():
    return bool(video.find_ffmpeg() and video.find_ffprobe())


def _clip(path, gop, seconds=2.0, width=160, height=96, fps=30):
    """An H.264 test clip with a key frame every *gop* frames and no extra
    ones at scene cuts.  True on success."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cmd = [video.find_ffmpeg(), "-y", "-f", "lavfi", "-i",
           "testsrc=size=%dx%d:rate=%d:duration=%s" % (width, height, fps,
                                                        seconds),
           "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
           "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
           path]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and os.path.isfile(path)


# ---- no ffmpeg needed -----------------------------------------------------

def test_a_short_gop_slot_caps_the_replacements_spacing():
    slot = VideoInfo("s.mp4", vcodec="h264", keyint=4)
    assert video.keyint_conflict(VideoInfo("r.mp4", keyint=60), slot) == (
        "it has a key frame every 60 frames and this slot's clip has one "
        "every 4")
    assert video.keyint_conflict(VideoInfo("r.mp4", keyint=4), slot) is None
    assert video.keyint_conflict(VideoInfo("r.mp4", keyint=1), slot) is None


def test_a_long_gop_slot_or_an_unknown_side_has_no_opinion():
    # A slot whose spacing is just its encoder's default proves nothing, and
    # neither does a file whose spacing couldn't be read.
    long_slot = VideoInfo("s.mp4", keyint=250)
    assert video.keyint_conflict(VideoInfo("r.mp4", keyint=600),
                                 long_slot) is None
    assert video.keyint_conflict(VideoInfo("r.mp4", keyint=0),
                                 VideoInfo("s.mp4", keyint=4)) is None
    assert video.keyint_conflict(VideoInfo("r.mp4", keyint=60),
                                 VideoInfo("s.mp4", keyint=0)) is None


def test_only_a_short_gop_slot_gets_a_g_flag():
    assert video._keyint_args(VideoInfo("s.mp4", keyint=4)) == ["-g", "4"]
    assert video._keyint_args(VideoInfo("s.mp4", keyint=250)) == []
    assert video._keyint_args(None) == []


def test_the_drop_in_recipe_names_the_spacing_when_it_matters():
    kw = dict(vcodec="h264", width=1360, height=768, fps=30.0,
              profile="Constrained Baseline", level=30, pix_fmt="yuv420p")
    short = VideoInfo("s.mp4", keyint=4, **kw)
    cmd = video.dropin_ffmpeg_command(short, ".mp4")
    assert " -g 4 " in cmd
    assert ("Key frames", "every 4 frames or closer") in video.dropin_spec(
        short, ".mp4")
    long_ = VideoInfo("s.mp4", keyint=90, **kw)
    assert " -g " not in video.dropin_ffmpeg_command(long_, ".mp4")
    assert "Key frames" not in dict(video.dropin_spec(long_, ".mp4"))


def test_a_non_mp4_file_reads_as_unknown(tmp_path):
    p = tmp_path / "x.webm"
    p.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 64)
    assert keyframe_interval(str(p)) == 0
    assert keyframe_interval(str(tmp_path / "missing.mp4")) == 0


# ---- needs ffmpeg ---------------------------------------------------------

def test_the_spacing_is_read_off_the_sample_table(tmp_path):
    if not _have_ff():
        pytest.skip("ffmpeg/ffprobe not available")
    a, b = str(tmp_path / "a.mp4"), str(tmp_path / "b.mov")
    if not (_clip(a, 4) and _clip(b, 30)):
        pytest.skip("ffmpeg could not render the test clips")
    assert keyframe_interval(a) == 4
    assert keyframe_interval(b) == 30
    assert video.detect_video_info(a).keyint == 4


def test_a_long_gop_replacement_is_re_encoded_to_the_slots_spacing(tmp_path):
    # The field case: same codec, size, frame rate and profile as the slot,
    # so it used to be "copied through (already matches)".
    from pinball_decryptor.core.video_slots import (scan_video_slots,
                                                    stage_replacement)
    if not _have_ff():
        pytest.skip("ffmpeg/ffprobe not available")
    slot_path = str(tmp_path / "video" / "Song_v1.mp4")
    rep = str(tmp_path / "mine.mp4")
    if not (_clip(slot_path, 4) and _clip(rep, 30)):
        pytest.skip("ffmpeg could not render the test clips")
    slot = scan_video_slots(str(tmp_path / "video"))[0]
    with open(rep, "rb") as f:
        rep_bytes = f.read()

    ok, detail = stage_replacement(slot, rep)
    assert ok, detail
    assert "key frame every 30" in detail
    with open(slot_path, "rb") as f:
        assert f.read() != rep_bytes
    assert 0 < keyframe_interval(slot_path) <= 4


def test_a_replacement_with_the_slots_spacing_still_copies_through(tmp_path):
    from pinball_decryptor.core.video_slots import (scan_video_slots,
                                                    stage_replacement)
    if not _have_ff():
        pytest.skip("ffmpeg/ffprobe not available")
    slot_path = str(tmp_path / "video" / "Song_v1.mp4")
    rep = str(tmp_path / "mine.mp4")
    if not (_clip(slot_path, 4) and _clip(rep, 4)):
        pytest.skip("ffmpeg could not render the test clips")
    slot = scan_video_slots(str(tmp_path / "video"))[0]

    ok, detail = stage_replacement(slot, rep)
    assert ok and "already matches" in detail


def test_the_build_will_not_put_a_long_gop_original_on_the_card(tmp_path):
    from pinball_decryptor.plugins.stern.engine import _intact_verdict
    if not _have_ff():
        pytest.skip("ffmpeg/ffprobe not available")
    staged, src = str(tmp_path / "staged.mp4"), str(tmp_path / "mine.mp4")
    if not (_clip(staged, 4) and _clip(src, 30)):
        pytest.skip("ffmpeg could not render the test clips")
    ok, why = _intact_verdict(src, staged)
    assert not ok and "key frame every 30" in why
    assert _intact_verdict(staged, staged) == (True, None)


def test_the_as_is_check_flags_a_long_gop_file(tmp_path):
    from pinball_decryptor.core.video_slots import scan_video_slots
    from pinball_decryptor.webui.video_helpers import playability_conflict
    if not _have_ff():
        pytest.skip("ffmpeg/ffprobe not available")
    slot_path = str(tmp_path / "video" / "Song_v1.mp4")
    rep = str(tmp_path / "mine.mp4")
    if not (_clip(slot_path, 4) and _clip(rep, 30)):
        pytest.skip("ffmpeg could not render the test clips")
    slot = scan_video_slots(str(tmp_path / "video"))[0]
    why = playability_conflict(slot, rep)
    assert why and "stutter" in why
