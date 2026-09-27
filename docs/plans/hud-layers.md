# HUD layers: modes that look like Stern made them (Godzilla)

## What and why

David, 2026-09-26, on the Godzilla example modes (the five intricate modes and ANGUIRUS):

> our videos should be full screen (behind the ui elements), instead of small feedback in the middle of
> the screen. for persistant mode elements, can we add that feedback to the ui edges? (like how the timers
> are displayed for example). it would be cool to show a gauge of like how many spikes for anguirus in the
> ui while it's active (but out of the way). let's make all the modes as intricate as possible too - videos
> shown whenever possible and not the cheesy splash cards for when a mode starts. let's also add a new
> multi-ball mode for testing. i want it to start after hitting the magna-captive ball thing like ten
> times. then during multiball, do something new and interesting that is not like the other multi-ball
> modes. ... this intricate mode effort will be recorded to show off to other users. the modes need to
> blend in and look like they were made by Stern.

And: "don't forget to get sick clips from the Godzilla films we have on the computer like we did before".

Before this branch a mode's picture was a 640x160 panel (a film still with a line of words) in the middle
of the glass, and its clip was drawn by the runtime on display layer 0: over EVERYTHING, score panel
included. Neither is how Stern presents a mode.

## How Stern presents a mode (Godzilla Premium/LE 1.16, read off the program and measured)

- **The layered display draws, every frame and in this order:** its background element, then the HUD
  scenes (the score panel, the top bar, the slide-outs scene `32e6ae28`). All on display layer 0, in call
  order: the order of `scene_show(scene, 3)` calls IS the z order (run h2's trace).
- **The background element** (`BDLBackground::v[8]`, 0x3fec4) shows the video bank's player first when the
  background has a clip (`this+0x54`), then its own scene. In main play it is one of five `BDLMainplayBG`
  objects (vtable 0x632ff0): the city. A battle's background plays its clip in the "ScoreFrame" crop
  (`GodzillaVsTitanosaurus_Background1`, lr 0x40880) and its scene is TEXT ONLY: the battle's title,
  instruction line and three counters (the Ebirah scene: `Title_Instance` at y 444, `Line1_Instance` at
  538, `Counter_Left/Center/Right` with labels at x 17 / 573 / 1123, y 104-224), in the game's two fonts
  (GameFont_Primary: white, black outline; GameFont_Secondary: orange gradient, black outline).
- **A framed shot award** (the Maser) is a foreground element that shows the player, then its own scene,
  in the background's place: full screen, under the HUD.
- **The left-edge timers** are the slide-outs scene `32e6ae28`: BattleTimer / DoubleScoringTimer badges
  (a 210x102 panel with a green LED label, BATTLE / DOUBLE SCORING / TESLA, a glowing icon disc and a dark
  number window) at x 0, y 267 / 376 / 485, the number in GameFont_Primary.
- A clip the game plays with no element drawing it is not on the glass (run h1: `clip_play` in the
  ScoreFrame crop alone shows the city, unchanged).

## What the runs taught (h1-h12, `C:\tmp\pad_hud\h*`, display_probe.c)

- h1: a clip played with no element drawing it is not on the glass.
- h2: the frame's draw order (above); a player drawn on display layer 1 is not shown and the renderer
  stops presenting (layer 1 is a second output: the renderer draws it with another EGL context).
- h3-h11: a player put in the frame's layer-0 list by US - vetoing the city's draw, swapping the city
  scene's argument, drawing it over the city, drawing it from the tick and showing the HUD scenes again,
  clip started in-process or not - stops the game's display processes (no scene_show at all; the
  renderer parked on a futex, h8's thread sample) until it is taken away. A tick-drawn player on top of
  everything (the runtime's clip route since item 132, hardware-proven) keeps presenting but the processes
  under it stall too (h10), invisible because the clip covers the glass.
- **h12 variant 6 WORKS: the game's own way.** From inside the city element's draw (the layered display's
  process): `clip_play(name, 1, "ScoreFrame")` and the city object's own video field `+0x54` = the video
  surface - what `BDLBackground::v[13]` does for a background that has a clip. The game's update
  (`BDLBackground::v[7]`, 0x3ff28) then advances the player and its draw (v[8]) shows it; the city's own
  scene show is given the player (already in the frame's list, so `display_draw` refuses it) and so the
  city is skipped. Our clip full screen, the score panel and top bar over it, the renderer presenting
  throughout (no gap in the eglshim frame counter), the city back at "off" (+0x54 = 0). The map icons
  (BRIDGE, POWER...) are not drawn over it: the game hides that scene while a background clip plays, as it
  does for its own framed clips; `32e6ae28` (the timers, a mode's HUD) is still drawn.

## Design

1. **A mode's video behind the HUD (`pm_backdrop`)**: the h12 variant 6 route in the runtime. Hooks
   `BDLBackground::v[8]` (note the element) and `scene_show` (play in-process, set `+0x54`, skip the
   city's scene). Re-played in-process when the surface goes idle with no layered foreground up (a framed
   award of the game's took the one surface). Suspended while a full-screen clip of ours plays (the intro
   on layer 0: `+0x54` back to 0 so the player is not already in the list when the tick adds it). Port
   lines: `site backdrop_draw`, `site scene_show`, `data backdrop_city_vtable`, `value backdrop_video_at`,
   `value backdrop_scene_at`.
2. **Mode HUD pieces at the edges**, built into `32e6ae28` by the card build, in the game's own fonts and
   badge art, hidden until a mode shows them: a timer badge (the stock badge with the mode's label and
   icon), a title and an instruction line (the battle layout), up to three counters, and a gauge (N pips,
   e.g. ANGUIRUS's spikes) on the right edge.
3. **Start = a full-screen intro clip** (over everything, as the game's own mode intros), then the loop
   behind the HUD. No picture panel.
4. **Event clips** in the background slot for a moment (a sever, a barrage), then the loop again.
5. **A new multiball, MELTDOWN (Burning Godzilla)**: lit by 10 Magna-Grab captive-ball hits.
6. **Light shows** (David, 2026-09-26: "add some intricate light shows when the modes start and end. They
   should be unique and colorful"): each mode's own start and end show across the playfield's inserts,
   computed per tick from each insert's place on the playfield (the port's `at x,y`), in the mode's colours.
7. **Film clips** scouted from the collection (`C:\tmp\pad_hud\scout\clips.json`, 37 slots: intro, loop,
   events, finales for the six modes and MELTDOWN), cut by the app's film cutter.

## Status

- 2026-09-26: branch created from main 7d4e6a36 (local only, neutral name, like feature/ball-manager).
  Runs h1-h12 (emulator, Premium 1.16, `C:\tmp\pad_hud`): the draw order measured, the game's own
  background route found (h12). b1: `pm_backdrop` in the runtime, emulator-proven with
  `backdrop_test_mode.c` (intro, loop behind the HUD, one-shot, the Maser's award and back, LOOPS, no
  render stall).
- 2026-09-27: `mode_hud.py` (the HUD at the edges, the game font carried from the Ebirah scene, the stock
  badge relabelled), clips by cue and `hud` in a code mode's assets through Write and Try it, light shows
  (`pm_lamp_xy`, `pm_lamp_paint`, `kit_show`), all six examples reworked, MELTDOWN added. Run t1 (KING
  GHIDORAH alone, Try it's set on a stock Premium 1.16 copy): the HUD loads and every piece is found; the
  intro, the loop behind the HUD, the head counters, the badge, the award line, the lost ending full
  screen and the total; both light shows over 83 placed inserts and 4 GI strings; no render stall. Fixed
  from it: the badge moved to the BATTLE slot (it covered the left counter), the gauge moved under the
  right counter, the game's framed awards dropped while a backdrop is up (their words sat on the title).
- 2026-09-27, run t6 (all six modes in one game, Try it's set on a stock Premium 1.16 copy, `C:\tmp\pad_hud\t6`,
  sheets `sheet_<mode>.jpg`): segv 0, fatal 0, the baseline 6 throws, no render gap. MASER (two barrages,
  the chain broken), OXYGEN (won), MELTDOWN (the whole flow to the super jackpot) and ANGUIRUS (the entrance,
  spikes, two rolls, the gauge) played as designed: intros full screen, loops behind the HUD, event clips,
  full-screen endings, totals. GHIDORAH timed out and FINAL WARS started late: the play script lost the lit
  head after a sever (it read the log's "lit X HEAD", a sever says "the lit head: X").
- 2026-09-27, the desk tests (`test_spike2_intricate_modes.py`, 108 under WSL) rewritten for the HUD, clips
  and MELTDOWN. From their review: MELTDOWN's ready insert (MAGNA GRAB pulsing red, its own lamp group,
  dark while any other mode, a stock battle/multiball or a light show runs); the captive ball left alone
  while another of our modes runs (it is OXYGEN's hold-off); four HUD texts shortened to fit; OXYGEN's
  "1 SPIN TO GO"; the desk harness holds six modes' HUD nodes and has the Left spinner.
- The six examples keep 20 calls: Premium 1.16 measures 21 call carriers (`mode_sounds.Carriers.calls`).
- **Owed:** a hardware run; the Pro 1.15/1.16 backdrop port lines are derived from the programs by the shape
  of Premium's measured ones, never run in the emulator; cues past the carrier limit (GHIDORAH's regrow and
  others) are not carried.

## How to test it

- Desk: `tests/test_spike2_intricate_modes.py` under WSL (the harness needs an ELF toolchain:
  `python3 -m pytest -o addopts='' tests/test_spike2_intricate_modes.py`); `test_stern_code_modes.py`,
  `test_stern_scene_write.py`, `test_stern_mode_assets.py`, `test_stern_mode_runtime.py` on Windows.
- Emulator: `C:\tmp\pad_hud\make_proj.py <proj> <example names...>` (a project on the stock Premium 1.16
  image, the examples cut from the films), `build_set.py <proj> stock_run.raw <base>` (Try it's set, Write's
  own code), then `t1.sh` with `TRY=<base> RUN=<out> SCRIPT=<play script>` under the rig lock.
- The real check is the app: Modes tab > Examples adds each mode from the films, Try it plays them.
