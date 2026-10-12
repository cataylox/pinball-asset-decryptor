"""How often the running app saves what it otherwise only saves on quit
(Settings, the gear, Save automatically).

Edits to pictures, sounds, videos, text, scenes, modes and default settings
are written the moment they are made.  What waited for the quit (or a project
switch) is the rest of the open project: the Multi-boot list, the Emulate
card, the Extract options and the Write file name.  A crash, a power cut or a
killed process took a whole session of those (DragonRR, PAD-541: "is it
autosaving.. and if it is can we have an interval option in the settings").
"""

# (minutes, label).  ``0`` is a real choice: only on quit, as before.
# ``AUTOSAVE_INTERVAL_DEFAULT`` must be one of these values.
AUTOSAVE_INTERVAL_CHOICES = (
    (1, "Every minute"),
    (5, "Every 5 minutes"),
    (15, "Every 15 minutes"),
    (30, "Every 30 minutes"),
    (0, "Never (only when PAD closes)"),
)
AUTOSAVE_INTERVAL_DEFAULT = 5

#: The menu rows' tooltip: what the timer saves, and what it never needed to.
#: Every user sees it, so it never names the preview features (test_webui_concealment).
AUTOSAVE_TIP = (
    "Your changes to pictures, sounds, videos, text, scenes and "
    "default settings are saved the moment you make them, whatever this is "
    "set to. This saves the rest of the open project on a timer: the "
    "Multi-boot list, the Emulate card, the Extract options and the Write "
    "file name. PAD always saves them when it closes too.")


def normalize_autosave_interval(value):
    """The stored autosave interval as one of :data:`AUTOSAVE_INTERVAL_CHOICES`.

    Missing, unparseable or off-menu falls back to
    :data:`AUTOSAVE_INTERVAL_DEFAULT`; ``0`` (never) survives.
    """
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return AUTOSAVE_INTERVAL_DEFAULT
    return minutes if minutes in {m for m, _ in AUTOSAVE_INTERVAL_CHOICES} \
        else AUTOSAVE_INTERVAL_DEFAULT
