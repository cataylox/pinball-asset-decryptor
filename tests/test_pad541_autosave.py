"""PAD-541: ⚙ Save automatically.  The open project's anchor and the
settings are saved on a timer, not only when the app closes (DragonRR: "is it
autosaving.. and if it is can we have an interval option in the settings").
"""

import json

from pinball_decryptor.webui import autosave_interval as ai
from tests.webui_harness import web_app


def _project(tmp_path):
    from pinball_decryptor.core import project_file
    folder = tmp_path / "proj"
    folder.mkdir()
    project_file.save(project_file.anchor_path(str(folder)),
                      manufacturer_key="stern",
                      paths={"extract_output": str(folder),
                             "write_assets": str(folder)},
                      extract_options={})
    settings = {"last_manufacturer": "stern",
                "manufacturers": {"stern": {"extract_output": str(folder),
                                            "write_assets": str(folder)}}}
    return str(folder), settings


def _anchor_text(folder):
    from pinball_decryptor.core import project_file
    return json.dumps(project_file.load_anchor(folder))


def _settings(tmp_path):
    return json.loads((tmp_path / "cfg" / "settings.json").read_text(
        encoding="utf-8"))


def _menu(w):
    for it in w.state("shell")["settings_items"]:
        if it.get("label") == "Save automatically":
            return it["submenu"]
    return None


def test_choices_and_normalize():
    assert ai.AUTOSAVE_INTERVAL_DEFAULT in dict(ai.AUTOSAVE_INTERVAL_CHOICES)
    assert 0 in dict(ai.AUTOSAVE_INTERVAL_CHOICES)          # never is a choice
    for minutes, _label in ai.AUTOSAVE_INTERVAL_CHOICES:
        assert ai.normalize_autosave_interval(minutes) == minutes
    for junk in (None, "", "5m", 7, -1):
        assert ai.normalize_autosave_interval(junk) == \
            ai.AUTOSAVE_INTERVAL_DEFAULT


def test_on_by_default_and_the_timer_saves_the_project(tmp_path):
    folder, settings = _project(tmp_path)
    with web_app(tmp_path, settings=settings) as w:
        assert w.window.autosave_interval_var.get() == 5
        rows = _menu(w)
        assert [r["label"] for r in rows] == [
            "Every minute", "Every 5 minutes", "Every 15 minutes",
            "Every 30 minutes", "Never (only when PAD closes)"]
        assert all(r["id"] == "autosave_interval" and r["radio"]
                   and r["title"] == ai.AUTOSAVE_TIP for r in rows)
        assert [r["args"][0] for r in rows if r["checked"]] == [5]
        assert w.app._autosave_after                    # armed at startup
        # an Emulate card picked mid-session reached only the screen...
        card = str(tmp_path / "picked_mid_session.raw")
        w.run(lambda: w.window.emulate_card_var.set(card))
        assert "picked_mid_session" not in _anchor_text(folder)
        # ...until the timer fires: then it is in the project, and re-armed
        w.run(w.app._autosave)
        assert "picked_mid_session" in _anchor_text(folder)
        assert _settings(tmp_path)["emulate_card"] == card
        assert w.app._autosave_after


def test_pick_never_stops_the_timer_and_persists(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.settings_action", "autosave_interval", 0)
        assert w.window.autosave_interval_var.get() == 0
        assert _settings(tmp_path)["autosave_minutes"] == 0
        assert w.app._autosave_after is None
        assert [r["args"][0] for r in _menu(w) if r["checked"]] == [0]
        w.call("ui.settings_action", "autosave_interval", 15)
        assert _settings(tmp_path)["autosave_minutes"] == 15
        assert w.app._autosave_after


def test_never_is_kept_across_a_restart(tmp_path):
    with web_app(tmp_path, mfr="stern",
                 settings={"autosave_minutes": 0}) as w:
        assert w.window.autosave_interval_var.get() == 0
        assert w.app._autosave_after is None
