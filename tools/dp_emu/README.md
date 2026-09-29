# Dutch Pinball PC emulator rig

Runs a Dutch Pinball game on this PC, the way `tools/bof_emu` runs a Barrels
of Fun game. Development title: **The Big Lebowski**, versions 1.13 (off a
machine's disk image) and 1.15 (the 1.15 update zip laid over that image's
installed 1.13, as the machine's updater does).

Status as of **2026-09-29** (PAD-263): the game **boots to attract mode and
takes switch input** - proven by capturing its window: the attract clips play
on the colour DMD, and a pressed Start (`sw.py startButton`) starts a game
("BALL 1/3 PLAYER 1", the rug skill-shot prompt). Wiring it into the app's
Emulate tab is a follow-up ticket.

## Why this is the smallest rig of all

The game ships its own simulator. `start` is an x86-64 PyInstaller (Python
2.7) build of Dutch Pinball's pyprocgame-derived framework (packages `dp` and
`game`), with every library it needs in its own folder (SDL 1.2, pygame,
numpy, libpinproc). Given `fakepinproc` on its command line it talks to a
**FakePinPROC** instead of the P3-ROC, serves balls from a fake trough
(`TroughFake`), and reads switches from the keyboard through the build's own
`config/keyboard.yaml`. There is no licence or hardware-ID check. Nothing is
emulated here; the rig only gives the game what the machine's disk gave it.

| the machine | the rig |
|---|---|
| `/home/dp/game/{assets,<version>,version,serial,temp}` | `$DP_RIG/game/`, hard-linked from the prepared build |
| `run.sh`: `./start fullscreen os_version ...` | `./start fakepinproc dev` |
| P3-ROC over USB (libftdi) | the game's own FakePinPROC |
| a keyboard on the service port (never) | `dpinput.so` + `sw.py` |
| X on the cabinet LCD | a hidden Xvfb per slot (`:120 + slot`), or WSLg |

## What the rig has to supply

* **A disk image.** The update zips (`TBL-v1.00.zip` ...) are not whole
  builds. ~1,400 base assets - the DMD dot sheet
  `display/dot_shapes.png`, most fonts, most sounds - live only in the
  machine's `/home/dp/game/assets` (without them the game dies at
  `dp/display.py`: `'NoneType' object has no attribute 'get_width'`). And
  the machine's updater copies the installed version folder and lays the zip
  over it, so each installed version folder holds files no zip has (1.10 on
  the image: 173). A zip laid over the wrong folder dies in the preloader
  (`dp/font.py`: `'NoneType' object has no attribute 'readlines'` - that
  was 1.10 + 1.15 without the image's 1.10 folder). So a build is prepared
  from a **disk image** first, and `prepare.py zip` lays updates over its
  installed version, refusing a zip whose `delta` list does not name it.
* **`serial` and `temp/`** beside the version folder (it opens `../serial`
  at boot).
* **An audio device.** With none, pygame's mixer is never opened and the
  first `pygame.mixer.Sound(file)` fails (`Unrecognized argument (type
  file)`). A hidden run uses SDL's disk writer into `/dev/null`.
* **Switch input with no one at the keyboard.** PAD-Runtime has no xdotool
  or XTest library, and a hidden window has no focus. `dpinput.so`
  (LD_PRELOAD) pushes key events straight onto SDL's queue from a FIFO. Two
  traps it handles: the PyInstaller bootloader re-executes itself (so the
  shim must stay in the environment and only start its reader in the process
  that opens a window), and pygame loads SDL `RTLD_LOCAL` (so SDL's symbols
  are fetched from the loaded library by name, not `RTLD_NEXT`).

Two image-specific traps, both handled in the rig's copy only (the cache and
the image are never changed): macOS `._*` AppleDouble files (skipped when
preparing), and a **zero-byte WAV** in the fan-modded image
`TBL_justin_113_v10.img` (`remake_hotelcalifornia_loop.wav`), which stops
the boot the same way a missing mixer does; the rig stands a second of
silence in for it and logs that in `rig.log`.

## Use

All in PAD-Runtime, as root; `PAD_SLOT=N` picks a slot (default 0).

```
T=/mnt/c/.../tools/dp_emu
python3 $T/prepare.py image /mnt/d/Pinball/TBL/justin_img/TBL_justin_113_v10.img --name TBL-justin
python3 $T/prepare.py zip "/mnt/d/Pinball/images/Dutch Pinball/TBL-v1.10.zip" \
        "/mnt/d/Pinball/images/Dutch Pinball/TBL-v1.15.zip" --base TBL-justin      # -> zip-1.15
bash $T/run_game.sh TBL-justin            # Ready: ... display :120 (1366x512)
python3 $T/sw.py startButton              # or: sw.py flipperLwL down / up; sw.py --list
bash $T/shot.sh /mnt/c/tmp/tbl.png
bash $T/status.sh
bash $T/killgame.sh
```

`run_game.sh --visible` draws on the WSLg desktop instead, `--audio` plays
sound through WSLg's PulseAudio, `--version V` runs another version folder
of the build (`prepare.py image --all` keeps every version on the image).

## What is proven

* 1.13 off the image (slot 1) and 1.15 (the zip over the image's 1.13,
  slot 0) both boot to attract, hidden, and start a game on
  `sw.py startButton`: "BALL 1/3 PLAYER 1" (2026-09-29).

## What is open

* Only the switches `keyboard.yaml` names have a key (Start, launch, coins,
  menu1-4, flippers, tilt, slam tilt, coin door). Playfield switches
  (targets, ramps, the bowling alley) need FakePinPROC's `add_switch_event`
  reached some other way - the `dev` machine view, or a keyboard.yaml of our
  own in the rig's copy.
* `--audio` and `--visible` are wired but were not exercised on 2026-09-29.
* Other Dutch Pinball titles (Alice's Adventures in Wonderland, Bride of
  Pinbot 2) were not tried.
