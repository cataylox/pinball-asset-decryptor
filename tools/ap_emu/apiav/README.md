# American Pinball apiav rig

Runs an American Pinball title whose screens and sound come from AP's native
**`apiav`** process on this PC. Development title: **Barry-O's BBQ
Challenge** 24.07.04 (`D:\Pinball\images\AP\bbq-gamecode_24.07.04.pkg`).
Hot Wheels and Galactic Tank Force ship `apiav` too; they were not tried
here. The older titles (Houdini .. Oktoberfest) draw in-process and are
`tools/ap_emu`'s own.

Status as of **2026-09-29** (PAD-265): the game **boots to attract mode and
takes switch input**. The whole attract loop plays (title video, Last Game,
Barry's Best, the multiball champions, the progressive jackpot, Cookoff
Champ) on the 1920x1080 main screen, with the 800x480 HUD beside it. Coins
count credits, Start begins a game ("CHALLENGER 1 / BALL 1", the skill-shot
choice on the HUD), and playfield switches score (a sling fires its coil
through the game's own hardware rule). Wiring it into the app's Emulate tab
is a follow-up ticket.

## How it fits together

| the machine | the rig |
|---|---|
| AP's OS image (not published): Ubuntu 24.04-class, Python 3.12, SDL2, GStreamer | PAD-Runtime (Ubuntu 24.04, glibc 2.39, the same Python 3.12) + a conda-forge env under `/var/tmp/pad_apav/env` (`setup.sh`); nothing is installed into the distro |
| `/game` = the unpacked .pkg | the rig's hard-linked copy, bind-mounted on `/game` in the rig's own mount namespace |
| `/game/local_config/config.yaml` (from the OS image) | written by `run_game.sh`: `pinproc.PinPROC`, `use_desktop` |
| `apiav` on `localhost:16726`, started by the OS | `apiav -d <title>/assets`, started first by `netns.sh` |
| P3-ROC on the Aimtron motherboard, AP's own pypinproc | `tools/proc_emu`'s board (`prochw.py`) + its pure-Python `pinproc` (PAD-262) |
| the cabinet LCD + HUD | a hidden Xvfb (`:160 + slot`, 2720x1560) or WSLg (`--visible`) |

The game is AP's Python source (`launcher.py` -> `procgame` SkeletonGame ->
`ApiLib` -> `bbq/`). It draws nothing itself: every screen, sound and video
is a JSON line to `apiav` over TCP, and `apiav` answers with its version and
with frame callbacks.

## What the rig has to supply

* **Its own network namespace.** `apiav` listens on `localhost:16726` and
  AVController dials exactly that; neither takes an option. Each slot runs
  both in `unshare --net --mount`, with its own loopback, so slots never
  meet.
* **Xvfb inside that namespace.** WSLg mounts `/tmp/.X11-unix` read-only,
  so a new Xvfb can only listen on its *abstract* socket, and abstract
  sockets belong to one network namespace: an Xvfb started outside cannot
  be reached from inside (SDL: "No available video device"). `shot.sh`
  grabs through `nsenter`.
* **`write_i2c_data`.** AP's pypinproc has a call upstream's lacks: a
  buffered `write_data(7, addr, value)` for the PCA9685 RGB LED chips on the
  P3-ROC's I2C bus (`procgame/game/rgb_led.py`). Without it the run loop
  dies on its first tick. Added to proc_emu's stub (a module-7 burst queued
  until the next flush).
* **The en_US.UTF-8 locale.** `bbq_main.py` sets it (score digit grouping)
  and dies without it. PAD-Runtime has only C.UTF-8 and no locale sources;
  `setup.sh` takes them from Ubuntu's `locales` .deb (unpacked, not
  installed) and compiles the one locale into the env (`LOCPATH`).
* **gst-plugins-bad** for `vp9alphadecodebin`: the title screen and many
  overlays are transparent VP9 webm, and without it `apiav` shows nothing
  where they play.
* **A closed coin door.** On AP `coinDoor` is active when the door is shut;
  the board seeds it active (`--active coinDoor`), or "Coin Door is Open"
  covers attract.

Nothing is patched in the game or in `apiav`, and there is no licence or
hardware-ID check (Scorbit derives a serial from the MAC address; the
network is off by default).

## Use

All in PAD-Runtime, as root; `PAD_SLOT=N` picks a slot (default 0).

```
T=/mnt/c/.../tools/ap_emu/apiav
bash $T/setup.sh                                  # once: the env (~1 GB)
python3 $T/prepare.py /mnt/d/Pinball/images/AP/bbq-gamecode_24.07.04.pkg   # -> bbq_24.07.04
bash $T/run_game.sh bbq_24.07.04                  # Ready: bbq_24.07.04, slot 0, display :160
bash $T/sw.sh tap coin1 120                       # 4 coins = 1 credit on the default pricing
bash $T/sw.sh tap startButton 150
bash $T/sw.sh sw flipperLwL 1 ; bash $T/sw.sh sw flipperLwL 0
bash $T/sw.sh switches | state | drivers | log 20
bash $T/shot.sh /mnt/c/tmp/bbq.png [main|hud|all]
bash $T/status.sh
bash $T/killgame.sh
```

`run_game.sh --visible` draws on the WSLg desktop, `--audio` plays through
WSLg's PulseAudio, `--sim` also draws AP's own playfield simulator panel
(lamps and switches) beside the main screen (`/game/.sim`).

Logs: `$AV_RIG/game.out` (the game, DEBUG), `apiav.out`, `rig.log`, and
proc_emu's `/var/tmp/pad_proc/rig<slot>/prochw.out`.

## What is open

* **No ball model.** Start pulses `troughKicker`, but no ball leaves the
  trough, so the game re-kicks every 1.5 s and ball search follows. A model
  on proc_emu's driver log (kicker -> trough opto opens, `shooter` closes)
  is the next step before a game can be played through.
* `--audio`, `--visible` and `--sim` are wired but were not exercised on
  2026-09-29.
* BBQ logs one `AVController ... TypeError` on a frame callback during the
  game intro: the game's own handler, not the rig.
* Hot Wheels and Galactic Tank Force (both ship `apiav`) not tried.
