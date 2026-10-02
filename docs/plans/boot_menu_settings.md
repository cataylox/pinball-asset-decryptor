# Boot menu Settings: color correction on the machine (PAD-307)

David, 2026-10-01: someone may not like the color correction a build applied, or want to tweak
it on the machine. A SETTINGS tile at the end of the multi-boot menu; inside, Color correction,
where the values are changed and the effect is seen on the screen itself. Then: "each game image
can have its own color profile", "or optionally a 'set to all'".

The full behaviour is in `tools/spike2_emu/codeselect/DESIGN.md`, "The SETTINGS tile: color
correction on the machine (PAD-307)". This page is the plan and what is owed.

## Shape

| piece | where |
|---|---|
| `pad_cp` always in one fixed shape, every number 8 characters | `plugins/stern/shader_profile.py` (`TUNABLE_TEMPLATE`, `tunable_in`) |
| `color_profile=` / `settings=` conf keys, the tile as a card | `codeselect/conf.c`, `conf.h` |
| Settings and Color correction screens, hold-to-repeat, idle exit | `codeselect/settings.c` |
| correction maths for the preview, test card, values file, `--apply-color` | `codeselect/colour.c` |
| tile in the menu, countdown rules, `--screen` snapshots | `codeselect/codeselect.c` |
| the boot step: copy into RAM, bind over `<title>/game` | `codeselect/select.sh` (`own_color`) |
| each image's built profile into `images.conf` | `mkmulticard.py` (`tree_colour`, `plan_colours`) |
| the same step in the emulator | `run_game.sh` |

## Decisions

- **Optional, on by default.** David: "the settings section can be optional when setting up the
  multi-boot menu". A tick in Menu settings (Stern only) writes `settings=on|off` to the card.
- **A menu gear on the tile.** David: "it should have a default 'menu gear' icon on it". The
  selector draws it (`gfx_gear`), so no picture file is needed and every card layout has it.
- **Per image, with "Save for every game".** Each image starts from what it was built with; a
  black-and-white edition stays black and white unless the operator says otherwise.
- **Nothing on the games partition is written.** The adjusted program is a RAM copy bound over
  the original at boot. The store's blobs, `trees.json`, the bypass record and `update` never see
  it. Any failure runs the program as built.
- **Only builds made after this change are adjustable.** v1.60's `pad_cp` leaves out the terms it
  did not need, so there is no slot to write into; those images get no `color_profile=` line and
  no tile. Rebuilding the image (any Write with a profile) makes it adjustable.
- **No countdown inside Settings; the tile never boots.** On the tile the countdown boots the card
  the menu opened on; two idle minutes close Settings without saving.

## Status

Emulator-proven, and that is the verification (David, 2026-10-01: "If it works fine in emulation
I'm sure it will work in the game so I'm not going to verify it on the machine"). The Multi-boot
tab's preview draws the tile too, from the same `color_profile=` lines the card carries.

## Not covered

- Stock images (no profile) and single-image cards have no way in; a card that should be
  adjustable everywhere would need the identity `pad_cp` added to every image's build.
