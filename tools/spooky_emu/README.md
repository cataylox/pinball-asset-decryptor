# Spooky Pinball PC emulator rig (Beetlejuice)

Runs Spooky's **Beetlejuice** on this PC from its update file, the way
`tools/bof_emu` runs a Barrels of Fun game and `tools/ap_emu` an American
Pinball one. Tested with `D:\Pinball\images\Spooky\v2026.09.15.11.beetlejuice`
(the newest).

Status as of **2026-09-29** (PAD-266): it **boots to attract mode and takes
switch input**, hidden (`bootcheck.sh`: VERDICT pass, about 1 min 50 s from a
warm cache). It was also played: two coins, Start, Ball 1 served to the
shooter lane, auto-launched, pop bumpers/spinner/ramp/sling scoring
(500,000), a drain to the outlane and the next ball served.

**In the app** (2026-09-30): Spooky Pinball has an **Emulate** tab
(`webui/tabs/emulate_spooky.py`) that leads with the games it runs -
Beetlejuice only - takes the `.beetlejuice` update (Spooky's, or one Write
built), and drives `watch.sh` / `status.sh` / `stop.sh` / `cancel.sh`. When
the game reaches attract, the switch window (`spkpf.py`) opens: tools/bof_emu's
switch page pointed at this rig's board, every switch by name. A file that is
not a Beetlejuice update is refused with that answer (`prepare.sh` exit 4).

## Why this is small

Beetlejuice is a Unity 2022.3 game with the Mono backend (`main.x86_64` +
`UnityPlayer.so`, x86-64 Linux), and the developers built a desktop mode in:

* **Virtual mode.** `Constants.IsVirtual` is true unless the hostname contains
  `haunted-mansion` (the cabinets' name). In it, `Settings.Bash` skips every
  shell call not marked safe for a VM - `sudo reboot`, `unlock-root`,
  `avrdude` flashing, the OS-file replacement at boot - and a debug terminal
  listens on 127.0.0.1:2200 (its `switch hit` is empty in this build).
* No licence, hardware-ID or activation check.

So the update alone runs on PAD-Runtime's Ubuntu 24.04; Spooky's restore
image (`bj_production_base_image_2026.04.10.zip`, the cabinet's whole OS) is
not needed. The cabinet runs `sway` (Wayland) on tty1; the Unity player is
just as happy on X, so the rig uses Xvfb and Mesa's llvmpipe (OpenGL core,
`-force-glcore`).

| the machine | the rig |
|---|---|
| `/game/code/uptest/` (the game) | the cached build, hard-linked into `$SPK_RIG/game`, bound there in a private mount namespace |
| `/game/code/config/` (settings, audits, scores) | `$SPK_ROOT/nv<slot>`, kept between runs (`SPK_FRESH=1` starts over), with factory defaults "saved" (below) |
| `/game/logs`, `/game/tmp`, `/game/media` (USB), `/game/backup`, `/game/update` | `$SPK_RIG/<name>` |
| hostname `haunted-mansion...` | `pad-rig-<slot>` in its own UTS namespace (virtual mode) |
| the Warden board on USB (`/dev/WARDEN`, 115200) | `spkwarden.py` on a pty; `spkshim.so` maps `/dev/WARDEN` onto it |
| speaker / topper boards (`/dev/spookynano`, `/dev/spookypico`) | none - the game carries on without them |
| Vosk speech sidecar (`speech.py`, TCP 12346) | none - speech is off |
| sway on the cabinet LCD | a hidden 1920x1080 Xvfb per slot (`:160 + slot`), or WSLg |

## The board (spkwarden.py)

Warden's protocol (from the decompiled `Warden.cs`): the host sends
`'>' <opcode> <args>` (~60 opcodes: coils, LEDs, switch config, steppers);
the board sends `'<' 1|0 <sw>` for a switch going active/inactive and
answers a few requests. The board reports *logical* states - the host tells
the firmware which switches are inverted. The rig's board scans the host's
stream for what it must answer or act on and swallows the rest:

* `get_switch_state` (152): the board's state. The game asks after every
  Start/menu/tilt edge, so those only count when the board agrees.
* `get_coil_config` (168) of coil 6: the game's watchdog; the answer ends in
  255 ("still configured"), anything else makes it re-send the whole config.
* firmware/hardware info (150/151): `PAD rig Warden`, logged by the game as
  `CONTROLLER: WARDEN (PAD rig)` - bootcheck's proof the rig's board was used.
* the trough eject coil (51): a ball leaves the trough, the shooter lane
  closes half a second later. The auto-launch coil (54) opens it.

At rest the trough holds 6 balls (`Game.expectedBallCount`), everything else
is open. Mono's `SerialPort` sets DTR right after `Open()`; a pty refuses the
modem-line ioctls and Mono would throw, so the shim answers them.

The game's own stub (`\` on the keyboard sets `wardenIsStubbed` and fakes the
trough) is not used: with it the game ignores the board, so only the
keyboard's handful of switches work.

**Factory defaults.** A settings folder without
`beetlejuice_factory_defaults.json` stops attract behind "FACTORY DEFAULT
SETTINGS HAVE NOT BEEN SAVED ON THIS GAME!". The rig writes an empty one,
which means "the build's own defaults" (the game logs one "No factory
default found" per setting - harmless).

## Use

The app runs `watch.sh <update>` as root (`PAD_VISIBLE=1` draws on the
desktop at 1280x720, `PAD_AUDIO=1` plays sound), polls `status.sh` (key=value)
and stops with `stop.sh`; the switch window talks to the board through
`ctl.sh --stream` (requests `sw <n> <0|1>`, `tap <n> [ms]`, `plunge`, `drain`,
`state` - the BoF boards' protocol). By hand, all in PAD-Runtime as root;
`PAD_SLOT=N` picks a slot (default 0):

```
T=/mnt/c/.../tools/spooky_emu
bash $T/build.sh                                  # once, if spkshim.so is missing
PAD_VISIBLE=0 bash $T/watch.sh /mnt/d/Pinball/images/Spooky/v2026.09.15.11.beetlejuice
python3 $T/sw.py coin; python3 $T/sw.py start     # sw.py --list, sw.py --state
python3 $T/sw.py plunge                           # or: sw.py launch (auto-launch)
python3 $T/sw.py "top pop"; python3 $T/sw.py drain
bash $T/shot.sh /mnt/c/tmp/bj.png
bash $T/status.sh
bash $T/stop.sh
bash $T/bootcheck.sh bj_v2026.09.15.11            # VERDICT <build> pass|fail ...
```

`prepare.sh` and `run_game.sh` are the two halves of `watch.sh`. The game's
Unity log is `$SPK_RIG/player.log`, its own log `$SPK_RIG/logs/*.log`, the
board's `$SPK_RIG/warden.log`.

## What is open

* **It is heavy.** ~3.2 GB of memory and, on llvmpipe, every core it is
  given: `LP_NUM_THREADS` is capped at 4 (`SPK_LP_THREADS`). Two slots at
  once work in principle (own namespace, hostname, pty and display each; the
  second one's debug terminal cannot bind 2200 and says so) but were not run.
* No physics beyond the trough and shooter lane: scoops, the couch lock, the
  drop bank and the sandworm are switches you press yourself (the game fires
  their coils into nothing).
* Only the one title and build were run. Spooky's other Unity titles
  (Halloween's UnityPlayer is the same 2022.3) ship as encrypted `.pkg`
  updates and are not covered.
* Sound (`PAD_AUDIO=1`) was run - the game starts and plays on - but not
  listened to; the visible (desktop) window has not been run on this machine.
