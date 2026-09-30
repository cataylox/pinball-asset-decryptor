# American Pinball PC emulator rig

Runs an American Pinball game on this PC from its game-code `.pkg`, the way
`tools/bof_emu` runs a Barrels of Fun game and `tools/dp_emu` a Dutch Pinball
one. Titles: **Houdini** (21.10.25), **Oktoberfest** (22.09.19), **Hot
Wheels** (21.10.24), **Legends of Valhalla** (25.08.27) and **Galactic Tank
Force** (26.07.27B), all from `D:\Pinball\images\AP\*.pkg`.

Status as of **2026-09-29** (PAD-264): all five **boot to attract mode and
take switch input**, hidden, several at once (`bootcheck.sh`: VERDICT pass
for all five in one run). Houdini, Hot Wheels and Galactic Tank Force were
also played: coins, Start, Ball 1, the ball served to the shooter lane,
plunged, and playfield switches scoring (Houdini 89, Hot Wheels 36,150, Tank
50,550). The app's **Emulate tab** for American Pinball (PAD-292) runs it:
see "The Emulate AP tab" below.
Barry-O's BBQ Challenge is PAD-265.

## Why this is small

AP's games are SkeletonGame (PyProcGameHD) with their own simulator built in:
config.yaml can select `procgame.fakepinproc.FakePinPROC` instead of the
P3-ROC, and AP's developers ran the games on their desktops that way. There
is no licence or hardware-ID check. AP publishes no restore images and the
`.pkg` holds only the game folder, so the rig supplies what the machine's OS
did.

| the machine | the rig |
|---|---|
| `/game/<dir>/` (houdini, legends, hw, okto, tank) | `$AP_RIG/game`, hard-linked from the unpacked build, bound at `/game/<dir>` in a private mount namespace |
| `/game/local_config/` (settings, audits; `../local_config/config.yaml`) | `$AP_RIG/local_config` bound there; the rig writes config.yaml (`py/mkconfig.py`) |
| Python 2.7 + pySDL2, SDL2_mixer/ttf/image, PyYAML, PIL, numpy, OpenCV 2.4, pyOSC | conda-forge's archived py27 builds (`setup.sh` -> `$AP_PY`) |
| Python 3.14 (Galactic Tank Force 26.07: its bytecode's magic) | `$AP_PY3` |
| `apiav`, AP's native A/V controller (Hot Wheels on), with GStreamer | the build's own `apiav`, on GStreamer + libav from `$AP_AV` |
| pypinproc's `pinproc.so` | `py/pinproc.py`, its module-level part in pure Python |
| the P3-ROC | the game's own FakePinPROC |
| X on the cabinet LCD | a hidden Xvfb per slot (`:140 + slot`), or WSLg |

## What the rig has to supply (and why)

`py/aprun.py` runs the title's launcher after putting these in place:

* **A machine at rest.** FakePinPROC answers all switches open. On AP's NC
  trough optos that reads as a full trough of blocked optos everywhere else;
  games ball-search or refuse to start. Each switch starts inactive (NC
  closed), the trough holds `PRGame.numBalls` balls, the coin door is shut.
  `AP_SEED="name=1,..."` overrides any raw state.
* **Switch input with nobody at the keyboard.** `sw.py` writes to a FIFO; the
  game loop delivers it through FakePinPROC's `add_switch_event`, so every
  switch in the machine yaml works (not just the keyboard map).
* **A trough.** Firing the trough's eject coil takes a ball off the eject end
  and puts it in the shooter lane half a second later (SkeletonGame's
  Trough, Houdini's TroughHoudini and ApiLib's TroughController all
  covered). `sw.py shooter open` plunges. `AP_BALLS=0` turns it off.
* **The OSC mode's `closed_switches`** (the developers' way to fill a trough
  on a desktop) is dropped: on Houdini's NC optos it EMPTIES the trough. The
  OSC server itself is off in the rig config (fixed port 9000).
* **en_US.UTF-8.** PAD-Runtime has only C.UTF-8 and no locale sources; the
  games only use it for `locale.format` score commas, so `localeconv()`
  answers en_US's number rules over C.UTF-8. Tank's Python 3 code still calls
  `locale.format` (removed in 3.12): `format_string` stands in.
* **OpenCV 2.4's `cv2.cv`** names (procgame's movie code) on 4.2.
* **Houdini's fonts.** Every title's framework falls back to
  `/game/houdini/assets/dmd/fonts/Courier.ttf` (AP built its OS image on a
  Houdini). Other titles get their own Courier/Impact, or DejaVu Sans.

`run_game.sh` also: removes Houdini's one-time OS-update files from the rig's
copy (its launcher would `cp` into /usr/bin and write /etc/osversion), runs
the game in the folder that holds its `assets/`, points a config-less
title's asset paths at the folders the build has, and for an A/V title
(launcher sets `USING_AVCONTROLLER`) starts `apiav -d <assets> -x` first, as
the machine's xinitrc does, turns SkeletonGame's own HD display and stock
modes off, and parks the game's own window off-screen.

## Use

All in PAD-Runtime, as root; `PAD_SLOT=N` picks a slot (default 0).

```
T=/mnt/c/.../tools/ap_emu
bash $T/setup.sh                                       # once: the Python/GStreamer envs
python3 $T/prepare.py /mnt/d/Pinball/images/AP/houdini-gamecode_21.10.25.pkg   # -> houdini_21.10.25
bash $T/run_game.sh houdini_21.10.25                   # Ready: ... (hidden)
python3 $T/sw.py coin1; python3 $T/sw.py startButton   # sw.py --list, sw.py --state
python3 $T/sw.py shooter open                          # plunge
bash $T/shot.sh /mnt/c/tmp/houdini.png
bash $T/status.sh
bash $T/killgame.sh
bash $T/bootcheck.sh okto_22.09.19                     # VERDICT <build> pass|fail ...
```

`run_game.sh --visible` draws on the WSLg desktop, `--audio` plays through
WSLg's PulseAudio. `aprun.py --pm` (edit `$AP_RIG/ns.sh`) prints the failing
frames' variables on a crash - the games ship bytecode, not source.

Credits: Houdini takes 2 coins a credit, Hot Wheels/Tank 4 (ApiLib's coin
event closes a few seconds after the last coin).

## The Emulate AP tab (PAD-292)

`webui/tabs/emulate_ap.py` drives the rig through four scripts, as the BoF
and Dutch Pinball tabs drive theirs, always on slot 0:

* `watch.sh <game.pkg>` (root) - `setup.sh` the first time (a ~1 GB
  download), `prepare.py` (a build remembers its .pkg's size and time, so a
  rebuilt one of the same name is unpacked again; `progress N` lines),
  `run_game.sh --visible [--audio]`, then `apswitches.py` and `status.sh`.
  `== Setup/Prepare/Game/Ready ==` headers drive the app's footer; exit codes
  are listed in the script.  Barry-O's BBQ is refused (exit 10): it is
  `apiav/`'s.
* `status.sh` - key=value lines (the app parses them).
* `stop.sh`, `cancel.sh` - Stop, and Cancel while a start is in flight.
* `cache.sh --list | --drop <name>...` (root) - the tab's Cache... window:
  every unpacked build (size, last played - `run_game.sh` touches
  `<build>/used` - and the .pkg it came from, `prepare.py`'s `pkg`) and
  `envs`, what `setup.sh` downloaded.  A running game's build, and `envs`
  while any game runs, are refused.

The switch window is `appf.py` on the app's Windows Python (a pfweb page,
`appage/`), talking to `apctl.py` through one `ctl.sh --stream` pipe.  Its
playfield is the game's own: every title ships its developers' OSC
switch-matrix layout (`<title>.layout`: a playfield picture and each
switch's spot on it), and `apswitches.py` copies the best-matching one into
`$AP_RIG/switches.json` with groups and keys.  Newer packages dropped the
layout (Legends of Valhalla 26.08.22 ships none, nor a playfield picture):
the first one seen for a title is kept in `$AP_ROOT/layouts/<machine dir>/`
and stands in, as does another cached build of the title; with neither, the
window is the list alone.

Drain (`!drain`) drops the ball on the trough's ENTRY switch, then rolls it
down to the next free position: SkeletonGame only looks for a drain once
its entry switch fires (`sw_trough6_active` sets `ball_entered_trough`;
trough7 on Houdini), so a count going up anywhere else was ignored and
Drain never ended a ball.  The rig config also turns ball search off: with
no ball rolling, 18 s without a switch hit is normal here, and the search's
coil fire hands out a free ball save (Legends of Valhalla's ship release,
5 s) that swallowed the next Drain.  Proven on all five titles: Drain after
the ball save ends Ball 1 and the game serves Ball 2.  `py/aprun.py` writes the
switches the game has active to `$AP_RIG/active` (the window lights them)
and takes `!drain` (a ball back into the trough).

Two fixes it needed: Legends of Valhalla's launcher sets
`USING_AVCONTROLLER = "0"`, which `run_game.sh` read as an A/V title and
parked its window off-screen (every picture was black); and `--audio` could
not connect: WSLg's PulseAudio shares no memory with this distro, so the
envs' libpulse gets `enable-shm = no` (`PULSE_CLIENTCONFIG`).

## What is open

* **One A/V title at a time** across all slots: the game reaches `apiav` at
  localhost:16726, fixed. A network namespace per slot would lift it, but
  PAD-Runtime's `/tmp/.X11-unix` is WSLg's read-only mount, so Xvfb serves
  only its abstract socket, which a network namespace cannot see.
  `run_game.sh` refuses a second one.
* No physics beyond the trough: drains, locks, VUKs and mechs (Houdini's
  stage, Tank's tank) are switches you press yourself.
* Tank 26.07's Python: its bytecode is 3.14 but it calls `locale.format`,
  which 3.14 lacks, on the attract high-score page - the machine may run an
  older Python 3 from source. The rig uses 3.14 plus the stand-in.
* Tank 25.08.28 (the older package) and Oktoberfest on the rig were not
  played past attract.  `--audio` and `--visible` were exercised on Legends
  of Valhalla only (PAD-292).
* Settings, audits and high scores do not survive a run: `run_game.sh`
  starts each from a fresh copy of the build.
