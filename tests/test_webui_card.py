"""The Select card tab's own half (webui/tabs/card.py + card_preview.py):
what the page shows about the picked card - the game's loading splash or a
multi-boot card's menu, and the Image Info report in place - read on a
worker, never on the loop."""

import io
import time
from pathlib import Path

from tests.webui_harness import web_app

from pinball_decryptor.webui import card_preview as CP

_JS = Path(__file__).resolve().parents[1] / "pinball_decryptor" / "webui" / "static" / "js" / "tabs"


def _svc(w):
    return w.window.service("card")


def _settled(w, timeout=20):
    """The card state once neither half is still loading."""
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        c = w.state("card")
        busy = [x for x in (c.get("preview"), c.get("info"))
                if x and x.get("state") == "loading"]
        if not busy:
            return c
        time.sleep(0.05)
    raise AssertionError("still loading: %r" % (w.state("card"),))


def _card(tmp_path, name="card.raw"):
    p = tmp_path / name
    p.write_bytes(b"\0" * 4096)
    return str(p)


def _shot(tmp_path, kind="splash", w=1360, h=768):
    return lambda p, out: {"src": str(tmp_path / (kind + ".png")), "w": w, "h": h,
                           "kind": kind, "card_path": ""}


def _no_render(*_a):
    raise AssertionError("the menu must not be drawn")


def test_no_card_shows_nothing(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("card.look", "") is True
        c = w.state("card")
        assert c["preview"] is None and c["info"] is None
        # a path that is not there (half typed) is no card either
        w.call("card.look", str(tmp_path / "nope.raw"))
        assert w.state("card")["preview"] is None


def test_details_in_place_and_nothing_to_picture(tmp_path):
    card = _card(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        c = _settled(w)
        titles = [s["title"] for s in c["info"]["sections"]]
        assert "File" in titles
        # not a Spike 2 card: nothing on the glass, and nothing said about it
        assert c["preview"]["state"] == "none" and not c["preview"]["note"]
        # the same card again is not read again
        seq = _svc(w)._seq
        w.call("card.look", card)
        assert _svc(w)._seq == seq
        assert w.call("card.info_copy").startswith("Image Info")


def test_splash_shown(tmp_path, monkeypatch):
    card = _card(tmp_path)
    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(CP, "games_on", lambda p: ["Godzilla Pro"])
    monkeypatch.setattr(CP, "splash_png", _shot(tmp_path))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        p = _settled(w)["preview"]
        assert (p["state"], p["kind"], p["w"], p["h"]) == ("ready", "splash", 1360, 768)
        assert p["src"].endswith("splash.png") and not p["note"]


def test_multiboot_menu_shown(tmp_path, monkeypatch):
    card = _card(tmp_path)
    calls = []

    def menu(path, out, runner):
        calls.append(path)
        return {"src": str(tmp_path / "menu.png"), "w": 1360, "h": 768}

    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(CP, "games_on", lambda p: ["A", "B", "C"])
    monkeypatch.setattr(CP, "menu_png", menu)
    monkeypatch.setattr(CP, "rig_off", lambda: False)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        p = _settled(w)["preview"]
        assert (p["state"], p["kind"], p["games"]) == ("ready", "menu", 3)
        assert calls == [card]


def test_multiboot_menu_that_fails_falls_back_to_the_splash(tmp_path, monkeypatch):
    card = _card(tmp_path)

    def menu(path, out, runner):
        raise RuntimeError("Drawing the menu failed (exit 127)")

    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(CP, "games_on", lambda p: ["A", "B"])
    monkeypatch.setattr(CP, "menu_png", menu)
    monkeypatch.setattr(CP, "rig_off", lambda: False)
    monkeypatch.setattr(CP, "splash_png", _shot(tmp_path))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        p = _settled(w)["preview"]
        assert (p["state"], p["kind"]) == ("ready", "splash")
        assert "exit 127" in p["note"]


def test_card_in_a_reader_gets_its_splash(tmp_path, monkeypatch):
    """The menu is drawn from an image file; a card with no cache key (the
    card in a reader) says so and shows the first game's splash."""
    card = _card(tmp_path)
    monkeypatch.setattr(CP, "card_key", lambda p: None)
    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(CP, "games_on", lambda p: ["A", "B"])
    monkeypatch.setattr(CP, "menu_png", _no_render)
    monkeypatch.setattr(CP, "splash_png", _shot(tmp_path))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        p = _settled(w)["preview"]
        assert p["kind"] == "splash" and "reader" in p["note"]


def test_no_menu_render_with_the_rig_off(tmp_path, monkeypatch):
    """PAD_UI_NO_RIG (tests, captures) runs no tool: the splash, and why."""
    card = _card(tmp_path)
    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(CP, "games_on", lambda p: ["A", "B"])
    monkeypatch.setattr(CP, "menu_png", _no_render)
    monkeypatch.setattr(CP, "splash_png", _shot(tmp_path))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        p = _settled(w)["preview"]
        assert p["kind"] == "splash" and "PAD_UI_NO_RIG" in p["note"]


def test_a_newer_pick_drops_the_older_answer(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        old = svc._seq
        w.run(svc._forget)                  # another card was picked
        svc._post(old, svc._preview, state="ready", kind="splash")
        w.drain()
        assert w.state("card")["preview"] is None


def test_backglass_follows_the_game_folders_edition():
    names = ["backglass_le.png", "backglass_prem.png", "backglass_pro.png"]
    assert CP._pick_backglass(names, "godzilla_pro") == "backglass_pro.png"
    assert CP._pick_backglass(names, "godzilla_le") == "backglass_le.png"
    assert CP._pick_backglass(names, "godzilla_premium") == "backglass_prem.png"
    assert CP._pick_backglass(names, "king_kong") == "backglass_prem.png"
    assert CP._pick_backglass(["backglass_x.png"], "godzilla_le") == "backglass_x.png"
    assert CP._pick_backglass(["2112_logo.png"], "rush_le") is None


def test_splash_falls_back_to_the_stern_logo(tmp_path, monkeypatch):
    """A tree with no splash of its own shows the OS partition's Stern logo,
    and says which it is."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 3)).save(buf, "PNG")
    monkeypatch.setattr(CP, "splash_bytes", lambda p: None)
    monkeypatch.setattr(CP, "boot_screen_bytes", lambda p: (buf.getvalue(), "/usr/local/spike/SternLogo.png"))
    got = CP.splash_png("x.raw", str(tmp_path))
    assert (got["kind"], got["w"], got["h"]) == ("boot", 4, 3)
    monkeypatch.setattr(CP, "splash_bytes", lambda p: (buf.getvalue(), "/g/assets/lcd/GameLogo.png"))
    assert CP.splash_png("x.raw", str(tmp_path))["kind"] == "splash"


def test_boot_screen_prefers_the_stern_logo(monkeypatch):
    from pinball_decryptor.plugins.stern import engine, formats

    class Reader:
        def read_file_bytes(self, node):
            return node["data"]

    monkeypatch.setattr(formats, "open_card", lambda p: io.BytesIO(b""))
    monkeypatch.setattr(formats, "parse_all_partitions_file", lambda f: [(1, 0x83, 2048, 100)])
    monkeypatch.setattr(engine, "_boot_screen_dir", lambda f, parts: (Reader(), {}))
    monkeypatch.setattr(engine, "_boot_images", lambda r, n: [
        ("/usr/local/spike/Another.png", {"data": b"no"}),
        ("/usr/local/spike/SternLogo.png", {"data": b"yes"})])
    assert CP.boot_screen_bytes("x.raw") == (b"yes", "/usr/local/spike/SternLogo.png")
    monkeypatch.setattr(engine, "_boot_screen_dir", lambda f, parts: (None, None))
    assert CP.boot_screen_bytes("x.raw") is None


def test_page_buttons_and_no_drop_zone():
    """No drop zone (the window never gets a dropped file's path, David
    2026-09-26: "it doesn't even work"); the button goes to the Extract tab
    and says so."""
    card = (_JS / "card.js").read_text(encoding="utf-8")
    ext = (_JS / "extract.js").read_text(encoding="utf-8")
    assert "DropZone" not in card and "DropZone" not in ext
    assert "drop_paths" not in card and "drop_paths" not in ext
    assert ">Go to Extract<//>" in card and "Extract…<//>" not in card
    # the picker has no Image Info badge: the details are under the card
    start = ext.index("export function SourceBody(")
    body = ext[start:ext.index("\nfunction ", start)]
    assert "InfoBadge" not in body and "DropZone" not in body


# ------------------------------------------------- the ⓘ and this section
# PAD-173, Sam: "the 'Technical details about this image' information button
# seems a bit redundant and slower than the Information section on the select
# card."  It was: the ⓘ predates this tab and collected the same report again
# in a window of its own.  For the PICKED card it now brings the person here.

def test_the_info_badge_for_the_picked_card_comes_to_this_tab(tmp_path):
    card = _card(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", card)
        w.call("ui.select_tab", "extract")
        assert w.call("extract.open_image_info", "input") is True
        assert w.state("shell")["tab"] == "card"
        # ...and the window was not opened behind it: one report, one place.
        assert not (w.state("extract")["info"] or {}).get("sections")


def test_the_write_tabs_original_comes_here_too(tmp_path):
    card = _card(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", card)
        w.run(lambda: w.window.write_upd_var.set(card))
        w.call("ui.select_tab", "write")
        assert w.call("write.image_info") is True
        assert w.state("shell")["tab"] == "card"


def test_an_original_that_is_not_the_picked_card_keeps_its_window(tmp_path):
    """The Original can be an image this tab is not showing, and then the
    window is the only place its details have."""
    picked = _card(tmp_path, "picked.raw")
    other = _card(tmp_path, "other.raw")
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", picked)
        w.run(lambda: w.window.write_upd_var.set(other))
        w.call("ui.select_tab", "write")
        w.call("write.image_info")
        assert w.state("shell")["tab"] == "write"


def test_a_picked_path_that_is_not_there_still_says_so(tmp_path):
    """A half-typed path has no section here either, so the window's "File
    not found" stays the answer."""
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", str(tmp_path / "nope.raw"))
        w.call("ui.select_tab", "extract")
        assert w.call("extract.open_image_info", "input") is False
        assert w.state("shell")["tab"] == "extract"
        assert w.asked and w.asked[-1]["title"] == "File not found"


def test_the_card_tile_is_capped_and_the_right_tile_takes_the_slack():
    """PAD-173, David: at 4K the card details tile sat below the fold with
    nothing to say it was there, and capping the tile alone left an ugly gap
    beside it.  Measured at 1920x1080 with the log pane open (a 4K screen at
    200%): the details started at y=944 against a pane ending at 845, and
    with these three rules they start at 800.  The glass cap is the one that
    keeps the top of the details on screen, so it is the one worth pinning."""
    css = (_JS.parent.parent / "css" / "tabs" / "card.css").read_text(
        encoding="utf-8")
    assert ".c-page .x-cols > .x-col:first-child > .card { max-width:" in css
    # the right-hand tile grows into what the cap leaves over
    assert "@media (min-width: 1500px)" in css
    assert "grid-template-columns: minmax(0, 900px) minmax(0, 1fr)" in css
    # ...and the glass stops growing taller on a short window
    assert ".c-page .c-glass { max-height: max(300px, calc(100vh - 700px)); }" \
        in css
