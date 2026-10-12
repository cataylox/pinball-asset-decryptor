"""PAD-549: the window opens where the user can see it.

The desktop window reopens at the place saved in settings.json.  When the
display is made smaller (an 8K ultrawide switched to 4K) or a monitor is
gone, that place is on no screen any more and the window opened out of
sight with no way to drag it back.  fit_to_screens keeps a saved place whose
title bar is still on a screen, and opens one that is not centred on the
main screen.
"""
from pinball_decryptor.webui import host
from pinball_decryptor.webui.host import fit_to_screens

FOUR_K = [(0, 0, 2560, 1440)]           # 3840x2160 at 150%, in logical px


def test_the_reported_case_comes_back_centred():
    # David's settings after the switch: right half of the 8K, x=3407
    assert fit_to_screens(1718, 1398, 3407, 0, FOUR_K) == (1718, 1398, 421, 21)


def test_a_place_on_the_screen_is_kept():
    assert fit_to_screens(1280, 860, 300, 200, FOUR_K) == (1280, 860, 300, 200)


def test_a_title_bar_partly_on_screen_is_kept():
    # most of the window hangs off the right edge, but 200 px of its title
    # bar can still be grabbed
    assert fit_to_screens(1280, 860, 2360, 100, FOUR_K)[2:] == (2360, 100)


def test_a_sliver_of_title_bar_is_not_enough():
    w, h, x, y = fit_to_screens(1280, 860, 2540, 100, FOUR_K)
    assert (x, y) == (640, 290)


def test_above_or_below_the_screen_comes_back():
    assert fit_to_screens(1280, 860, 100, -500, FOUR_K)[2:] == (640, 290)
    assert fit_to_screens(1280, 860, 100, 1420, FOUR_K)[2:] == (640, 290)


def test_a_second_monitor_place_is_kept_while_it_is_there():
    two = [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)]
    assert fit_to_screens(1280, 860, 3000, 50, two) == (1280, 860, 3000, 50)
    # the second monitor unplugged: back on the main one
    assert fit_to_screens(1280, 860, 3000, 50, two[:1])[2:] == (640, 290)


def test_centres_on_the_main_screen_not_the_first_listed():
    left_first = [(-1920, 0, 1920, 1080), (0, 0, 2560, 1440)]
    assert fit_to_screens(1280, 860, 9000, 0, left_first)[2:] == (640, 290)


def test_a_window_bigger_than_the_screen_is_cut_to_fit():
    assert fit_to_screens(5000, 2000, 9000, 0, FOUR_K) == (2560, 1440, 0, 0)
    assert fit_to_screens(5000, 2000, 0, 0, FOUR_K) == (2560, 1440, 0, 0)


def test_no_saved_place_stays_for_the_window_system_to_pick():
    assert fit_to_screens(5000, 2000, None, None, FOUR_K) == (
        2560, 1440, None, None)


def test_no_screens_known_changes_nothing():
    assert fit_to_screens(1718, 1398, 3407, 0, []) == (1718, 1398, 3407, 0)


def test_screens_off_windows_are_left_to_the_window_manager(monkeypatch):
    monkeypatch.setattr(host.sys, "platform", "linux")
    assert host._screens(object()) == []


def test_screens_that_cannot_be_read_change_nothing(monkeypatch):
    class Broken:
        @property
        def screens(self):
            raise RuntimeError("no GUI")
    monkeypatch.setattr(host.sys, "platform", "win32")
    assert host._screens(Broken()) == []
