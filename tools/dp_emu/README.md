# Dutch Pinball PC emulator rig

Runs a Dutch Pinball game on this PC, the way `tools/bof_emu` runs a Barrels
of Fun game, and backs the app's **Emulate DP** tab (Dutch Pinball -> Play ->
Emulate). Two titles, two quite different programs:

| | The Big Lebowski | Alice's Adventures in Wonderland |
|---|---|---|
| program | x86-64 PyInstaller (Python 2.7) build of Dutch Pinball's pyprocgame-derived `dp` framework | `/opt/pinterface`, a stripped native C++ program (Buildroot 2023.08, glibc 2.37, SDL2), libpinproc compiled in |
| on the PC | runs on PAD-Runtime's own libraries (it bundles everything) | runs in a chroot of its own root |
| the board | **its own simulator**: `./start fakepinproc dev` | none - `aaiw/aaiwshim.c` answers it as a P-ROC |
| switches in | pygame keys, through keyboard.yaml | P-ROC switch events from the fake board |
| screens | one colour-DMD window, 1366x512 | the LCD (1366x768) and the round one (480x480) |
| comes as | a disk image (+ update zips) | a Clonezilla `full_image` installer |

Status as of **2026-09-29** (PAD-263): both **boot to attract, take every
switch, start a game and score** - hidden, visible, with and without sound.
See *What is proven* and *What is open*.

## Use

The app runs `watch.sh` (as root) and polls `status.sh`; that is the whole
contract. By hand, in PAD-Runtime, as root; `PAD_SLOT=N` picks a slot:

```
T=/mnt/c/.../tools/dp_emu
PAD_VISIBLE=0 bash $T/watch.sh /mnt/d/Pinball/TBL/justin_img/TBL_justin_113_v10.img \
    "/mnt/d/Pinball/images/Dutch Pinball/TBL-v1.15.zip"          # TBL 1.15, hidden
PAD_VISIBLE=0 bash $T/watch.sh "/mnt/d/Pinball/images/Dutch Pinball/AAIW_1.05_full_image.img"
python3 $T/sw.py --list                    # every switch of the running game
python3 $T/sw.py startButton               # tap; or: sw.py flipperLwL down / up
bash $T/shot.sh /mnt/c/tmp/game.png        # every window the game opened
bash $T/status.sh; bash $T/stop.sh
```

`PAD_VISIBLE=1` (the app's default) draws on the WSLg desktop in ordinary
framed windows titled `<PAD_LABEL> - <the game's title>`; `PAD_AUDIO=1` plays
the sound through WSLg's PulseAudio. `dppf.py` is the switch window (the tab
opens it): TBL's own machine drawing with every switch on it plus a grouped
list, or Alice's switches as a list; hold with the mouse, right-click to
latch, the game's own keys work while it is focused.

| script | what |
|---|---|
| `watch.sh <img> [zip...]` | prepare (cached) + start + wait; `== Prepare/Game/Ready ==` and `progress N` for the footer |
| `prepare.py` | a build from a disk image (cached by its size and time, the two newest kept), updates laid over it |
| `run_game.sh` / `run_aaiw.sh` | start one build on this slot (TBL / Alice) |
| `status.sh`, `stop.sh`, `cancel.sh`, `killgame.sh` | key=value status; stop; cancel a start (drops the half-made build); stop and prove it |
| `dpctl.py` (`ctl.sh`) | press/hold/tap switch n; `--stream` for the switch window |
| `sw.py` | the same by name, for people |
| `dpinput.c` | TBL's shim: key events from a FIFO, window frame and title |
| `dpswitches.py` | TBL: a key for EVERY machine.yaml switch in the rig's keyboard.yaml, and switches.json |
| `aaiw/aaiwshim.c`, `aaiw/switches.json` | Alice's fake P-ROC and input shim; its 65 switches |
| `ftd2xx_stub.py` | Bride of Pinbot 2.0's missing driver DLL (see *What is open*) |

## The Big Lebowski: what the rig has to supply

The game ships its own simulator, so the rig only gives it what the
machine's disk gave it:

* **A disk image.** The update zips are not whole builds. ~1,400 base assets
  (the DMD dot sheet `display/dot_shapes.png`, most fonts and sounds) live
  only in the machine's `/home/dp/game/assets`, and the machine's updater
  copies the INSTALLED version folder and lays the zip over it, so each
  installed folder holds files no zip has (1.10 on the image: 173). A zip
  laid over the wrong folder dies in the preloader (`dp/font.py`), with no
  assets in `dp/display.py`. So `prepare.py` starts from the image, and lays
  updates over its installed version, refusing a zip whose `delta` list
  does not name it.
* **`serial` and `temp/`** beside the version folder (it opens `../serial`).
* **An audio device.** With none, pygame's mixer never opens and the first
  `Sound(file)` fails (`Unrecognized argument (type file)`). A muted run uses
  SDL's disk writer into `/dev/null`.
* **Every switch.** FakePinPROC reads switches only as keys through
  keyboard.yaml, which maps a dozen. `dpswitches.py` adds one key per
  machine.yaml switch (1000+n) to the rig's copy - unlinked first, never
  written through the cache's hard link - so targets, ramps and the trough
  can be pressed too.
* **Input with no one at the keyboard.** `dpinput.so` (LD_PRELOAD) pushes key
  events onto SDL's queue from a FIFO: no focus, no X tools. It starts its
  reader only in the process that opens a window (the PyInstaller bootloader
  re-executes itself) and finds SDL by handle (pygame loads it RTLD_LOCAL).

Two image-specific traps, handled in the rig's copy only: macOS `._*` files
(skipped), and a **zero-byte WAV** in the fan-modded `TBL_justin_113_v10.img`
(`remake_hotelcalifornia_loop.wav`), replaced by a second of silence.

## Alice's Adventures in Wonderland

The game SSD's root is a partclone + zstd image inside the Clonezilla
installer (`pinball-image/sda2.ext4-ptcl-img.zst`); `prepare.py` restores it
to `root.ext4` (~2.5 min, 8.5 GB). `run_aaiw.sh` loop-mounts it read-only
once (`$DP_ROOT/lower/<build>`, shared by every slot) and gives each slot an
overlay over it, then chroots into that as the ordinary user.

* **Mounts.** `/proc` is mounted fresh; `/sys`, `/dev` and the X socket are
  bound in and made `rslave` AT ONCE. PAD-Runtime's mounts are shared, and a
  recursive unmount of a shared bind propagates back to the host's own
  `/dev/pts`. And `dp_clear_rig` refuses to delete a rig folder with anything
  still mounted under it (a recursive delete through a bound `/dev`...).
* **The board.** `aaiwshim.so`, through the root's `/etc/ld.so.preload` (its
  busybox `env`/`sh` drop LD_PRELOAD), replaces the libftdi1 calls libpinproc
  makes and answers like a P-ROC FPGA: chip id, version, switch state words,
  and a switch event word for every press. It holds every switch at the
  machine's rest level (`AAIW_CLOSED`: the closed-at-rest switches plus 5
  balls in the trough). Most of Alice's switches rest CLOSED, so a press
  moves a switch AWAY from rest (`dpctl.py`). Coil/lamp writes are dropped.
* **The switches** (`aaiw/switches.json`): the game's own numbers and names
  ("46 Pop Bumper Top" is in the program), its cabinet switches at 64-79,
  and each one's rest level read from the running game's memory.
* **glibc.** The shim must not need a glibc newer than the root's 2.37;
  `run_aaiw.sh` refuses a build that asks for GLIBC_2.38+ (`sscanf` and
  `strtoul` would, so the shim parses numbers by hand).
* **Sound.** The root's SDL2 has no PulseAudio driver (ALSA, OSS, disk,
  dummy). With sound on, SDL's disk driver writes into a FIFO and a relay
  (`ffmpeg ... -f pulse`) plays it; the shim logs the format the game opens
  (48 kHz s16 stereo) so the relay reads it right.
* `pinterface` ignores SIGTERM: `killgame.sh` KILLs everything whose root is
  the slot's chroot, then unmounts it.

## Two rig-wide lessons

* **Xvfb must run with `-noreset`.** By default it regenerates when its last
  client disconnects, and a connection that arrives meanwhile is reset: TBL
  failed to start 3 times in 5 ("Couldn't open X11 display" -> pygame's
  "video system not initialized"); 8 of 8 with it. `dp_wait_display` waits
  until the display actually opens - PAD-Runtime's `/tmp/.X11-unix` is WSLg's
  read-only mount, so a rig's Xvfb has only its abstract socket, and waiting
  for the socket file never ends.
* **A press is held at least 100 ms** (`dpctl.py`): both games debounce, and
  a 0 ms click (Playwright's) started nothing on Alice.

## What is proven (2026-09-29)

* TBL 1.13 (off the image) and 1.15 (the zip over it) boot to attract, hidden
  and visible; Start begins a game; the window's Left Slingshot scores
  (00 -> 10 -> 20 -> 30). 8 of 8 cold starts.
* Alice 1.05 boots to attract on both screens; Start (from the switch
  window) begins Ball 1/3; three Pop Bumper Top hits score 15,000.
* Visible: framed, movable windows titled `PAD-263 - The Big Lebowski TM
  Pinball`, and Alice's two windows side by side.
* Sound: TBL opens its mixer on WSLg's PulseAudio (no disk-writer fallback -
  and it cannot load a sound without an open device); Alice's relay reads
  its stream at 196 KB/s (48 kHz s16 stereo) into PulseAudio, no errors.
* Stop leaves nothing: games, displays, relays, chroot mounts (PAD-Runtime's
  own `/dev`, `/proc`, `/sys` untouched).

## What is open

* **Bride of Pinbot 2.0** (`BOP2-v1.21.zip`) is a WINDOWS build of the same
  `dp` framework, driving the original machine's ROM through PinMAME
  (`pinmame/pinmamep.exe`, ROMs `bop_l6`/`bop_l7`, an AutoHotkey script to
  place its window). It runs on Windows itself: `ftd2xx_stub.py` gets it past
  the FTDI driver DLL its pinproc.pyd needs, and it then stops where TBL's
  zips do - a base asset (a font) no update zip carries. There is no BOP2
  disk image on this machine. With one, its `game/assets` beside the zip's
  version folder and `start.exe fakepinproc dev` is the next step; PinMAME
  and its AutoHotkey placement are untested.
* The machine's own ball physics are not modelled: a drained ball is a press
  of the outhole/trough switches, by hand.
* Alice's resting switch levels are the game's own idle values; the four
  optos that rest closed (30, 33, 49, 51) and the coin slots' mixed levels
  are as the game has them, unverified on a machine.
