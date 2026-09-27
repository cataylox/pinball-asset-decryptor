/* backdrop_test_mode.c - a rig instrument for pm_backdrop (hud-layers), never a card's mode.
 *
 * Trigger files in /dump (read twice a second), each holding a clip name:
 *   backdrop.intro  "<clip>"   pm_clip: full screen, over everything
 *   backdrop.loop   "<clip>"   pm_backdrop: looped behind the HUD
 *   backdrop.once   "<clip>"   pm_backdrop_once: once in the loop's place, then the loop again
 *   backdrop.stop              pm_backdrop(0)
 * It holds no display priority and runs no rules: it only asks the runtime, and logs what it asked. */
#include "pad_mode.h"

static unsigned ticks;

static void on_tick(void)
{
    char name[96];
    if (++ticks % 30) return;
    if (pm_trigger_text("backdrop.intro", name, sizeof name)) pm_log("intro \"%s\": %d", name, pm_clip(name));
    if (pm_trigger_text("backdrop.loop", name, sizeof name)) pm_log("loop \"%s\": %d", name, pm_backdrop(name));
    if (pm_trigger_text("backdrop.once", name, sizeof name)) pm_log("once \"%s\": %d", name, pm_backdrop_once(name));
    if (pm_trigger("backdrop.stop")) pm_log("stop: %d", pm_backdrop(0));
    if (ticks % 300 == 0 && pm_can(PM_CAN_BACKDROP))
        pm_log("showing %d, clip %d", pm_backdrop_showing(), pm_clip_playing());
}

static void on_init(void)
{
    pm_log("backdrop test: can %d", pm_can(PM_CAN_BACKDROP));
}

static const struct pm_mode backdrop_test = {
    .name = "BACKDROP TEST",
    .init = on_init,
    .tick = on_tick,
};
PM_REGISTER(backdrop_test);
