# Pinball Brothers FAST emulator rig (Predator)

Runs Pinball Brothers' **Predator** (2025) on this PC from its update files,
on an emulated **FAST Neuron** with its four I/O nodes and three expansion
boards (`pbfast.py`), the way `tools/bof_emu` runs a Barrels of Fun game.
It boots to attract mode, draws the real screens and takes switches: coins,
Start, the trough serving a ball, the launch button firing the auto-launcher,
targets scoring, drains and ball save (PAD-271). All of it runs hidden on a
private display, muted.

| title | update | status (2026-09-30) |
|---|---|---|
| Predator 1.0.1 | `pbpp_predator_game_1_0.upd` + `pbpp_predator_game_1_0_1.upd` (delta) | attract, played |

Alien, Queen and ABBA are **not** FAST machines (PB's own Heighway-lineage
I/O boards): `prepare.sh` refuses them with exit 4, and `tools/pbio_emu`
(PAD-272) covers them.

The app's **Emulate PB** tab (`webui/tabs/emulate_pb.py`, laid out as the
AP and Spooky tabs are) drives it through `watch.sh`, `stop.sh`,
`status.sh`, `cancel.sh`, `cache.sh` and `setup.sh`; the switch window is
AP's (`tools/ap_emu/appf.py`, through `pbpf.py`), the live volume Spooky's
(`tools/spooky_emu/spkvol.py`, through `pbvol.py`).

## Why this is small

The update is the machine's whole `/opt/game`: two native x86-64 Linux
programs and their media, with no licence, hardware-ID or activation check.

* **pinprog** - the rules. FreeWPC-derived C (Heighway's `hp-freewpc` fork,
  `platform/pb`), **not stripped, with full DWARF**: every function, global
  and source line has its name, so the FAST layer (`platform/pb/fast.c`) reads
  straight out of the disassembly. It talks to the Neuron over `/dev/ttyACM0`
  and `/dev/ttyACM1`, plays sound with SDL2_mixer and serves the screen
  program on TCP 5555. Settings, audits and high scores are `nvram/raven.nvr`
  in its cwd; its log is `raven.log` there.
* **vidprog** - the screen. C++, SDL2 + GStreamer (`uridecodebin` ->
  `appsink` for the `.mp4` animations), pinprog's TCP client.

Both were built on PB's Yocto OS ("pb-os", glibc 2.40) but ask for at most
GLIBC_2.39, so PAD-Runtime's Ubuntu 24.04 runs them once they have:

| the machine | the rig |
|---|---|
| loader `/lib/ld-linux-x86-64.so.2` | patched to `/lib64/...` at prepare time (patchelf; nothing else touched) |
| GNU Pth, SDL2_mixer/_image/_ttf, GStreamer, libxml2 | `$PB_ENV` (`setup.sh`: conda-forge, and Debian's last `libpth20`) |
| `/opt/game` | `$PB_RIG/game`, the build hard-linked, bound there in a private mount namespace |
| `/opt/game/nvram/` | `$PB_ROOT/nv<slot>/<title>/nvram`, kept between runs (`PB_FRESH=1` starts over) |
| the FAST Neuron on USB (`/dev/ttyACM0` NET, `/dev/ttyACM1` EXP) | `pbfast.py` on two ptys; `pbshim.so` maps the opens there |
| TCP 5555 between the two programs | `15555 + slot` (`pbshim.so` moves bind/connect), so rigs run side by side |
| `amixer`, `/opt/utils/game_update.sh`, `/etc/init.d/S11vidprog` | logging no-ops (`$PB_RIG/shell.log`); S11vidprog restarts this slot's vidprog |
| speakers | none: `SDL_AUDIODRIVER=dummy` unless `--audio` |
| the cabinet LCD | a hidden 1920x1080 Xvfb per slot (`:180 + slot`), or WSLg with `--visible` |

## The board (`pbfast.py`)

Every reply is the shape `fast.c` reads (details and addresses in
`docs/plans/pb_emulator.md`):

* **NET** - `ID:` -> `ID:NET FP-CPU-2000 02.26` (`fast_identify` picks the NET
  port by that prefix); `CH:`, `DL:` -> `XX:P`; `NN:<n>` -> the node's name,
  version, drivers, switches (`FP-I/O-0024`, `-3208`, `-1616`, `-3208`: 104
  switches, 40 drivers); `SA:` -> `SA:10,<15 bytes>`. **`WD:`, `SL:`, `TL:`
  get no reply**: `fast_read` hands any unsolicited line to whatever reply is
  being waited for, so a stray `WD:P` would answer an `SA:`.
* **EXP** - `EA:<addr>` selects a board; `ID@48:` / `B4` / `D0` / `30` ->
  `FP-CPU-2000`, `FP-EXP-0071`, `-0051`, `-1313`; `BR:`, `EM:`, `ER:` and
  the three-field `MF:` (motor wake-up) -> `XX:P`; `RS:` (one LED), `MP:`,
  two-field `MF:` are fire-and-forget. LED colours are kept for `sw.py leds`.
* **Switches** - events are `-L:xx` active / `/L:xx` inactive for every
  switch (the board applies an opto's inversion itself); in `SA:` an opto's
  bit is set when it is NOT blocked. The optos (trough 24-29, jam, locks,
  scoop, toy sensors...) are the game's own `mach_opto_mask`.
* **Balls** - counting, not physics: six in the trough (24-29, `TROUGH 1`
  first), `TROUGH RELEASE` (driver 0x11) moves one to the shooter lane (31),
  `AUTO LAUNCH` (0x10, fired when the player presses the launch button)
  puts it in play, `sw.py drain` returns one. A bank reset (0x17, 0x18,
  0x1C) stands its drop targets back up.

## Using it

As root in PAD-Runtime (`wsl -d PAD-Runtime -u root`), with `PAD_SLOT` and
`PAD_LABEL=PAD-n` set as for every rig:

```bash
# what the app's Start runs: setup (once), unpack, board, game, attract
PAD_VISIBLE=0 bash tools/pb_emu/watch.sh ".../pbpp_predator_game_1_0_1.upd"
bash tools/pb_emu/stop.sh                    # the app's Stop
bash tools/pb_emu/cache.sh --list            # the app's Cache window
bash tools/pb_emu/ctl.sh state               # the switch window's pipe (JSON)

bash tools/pb_emu/setup.sh                   # once: the libraries (~700 MB)
bash tools/pb_emu/build.sh                   # developers: rebuild pbshim.so
bash tools/pb_emu/prepare.sh ".../pbpp_predator_game_1_0.upd" ".../pbpp_predator_game_1_0_1.upd"
bash tools/pb_emu/run_game.sh                # newest build; returns at attract
python3 tools/pb_emu/sw.py tap "COIN 2"      # x4 = one credit
python3 tools/pb_emu/sw.py tap start
python3 tools/pb_emu/sw.py tap "LAUNCH BUTTON"
python3 tools/pb_emu/sw.py tap "LEFT SLING"  # any name from `sw.py list`
python3 tools/pb_emu/sw.py drain
bash tools/pb_emu/shot.sh /mnt/c/tmp/pred.png
bash tools/pb_emu/status.sh
bash tools/pb_emu/killgame.sh
bash tools/pb_emu/bootcheck.sh <build>       # VERDICT line: attract + a coin seen
```

`PBFAST_TRACE=1` on `run_game.sh` logs every command the game sends to
`$PB_RIG/pbfast.log`.

**Never `pkill pinprog`**: Alien, Queen and ABBA's programs (PAD-272's rig)
have the same names and run as the same user. Every stop here is filtered by
this slot's `PB_MARK`.

## The app's tab

* **Which file.** A person picks ONE update - the version to play.
  `pbupdates.py` finds the rest of its chain beside it (every
  `<game>_game_<version>.upd` of the same game up to that version, oldest
  first), so picking `…_1_0_1.upd` unpacks `…_1_0.upd` and then the delta.
* **status.sh** speaks the AP rig's keys (`running=`, `attract=`,
  `switches_json=`, ...) plus `ready=` (setup.sh done), `balls=` and
  `leds_lit=`.
* **The switch window** (`pbpf.py`) is appf's schematic view: every switch
  from `pbswitches.py`'s table (the game's own names, AP's keys), and the
  LEDs the game has lit as its lights grid.  `pbctl.py` turns the board's
  `ok` / `err` replies into the JSON appf reads.  The board adds `rip`,
  `reset`, `pause` (SIGSTOP/SIGCONT of this rig's pinprog and vidprog) and
  holds any `sw` press at least 100 ms: a 1 ms click reached pinprog as
  "SW 5 COIN 2 unstable" and was dropped.
* **Stop** also ends run_game.sh's namespace shell and its `runuser`
  wrappers (by `ns.pid`): they carry no `PB_MARK`, and once their programs
  were killed they sat stopped with zombies under them, one pair per run.

## Not done yet

* The main toy (helicopter/minigun motors, `TOY *` position switches) is
  answered but not modelled: its sensors all read clear, and the game's diags
  report 0 errors in attract. A mode that moves the toy may complain.
* The coin door (`ESCAPE`/`UP`/`DOWN`/`ENTER` service buttons) works as
  switches; the service menu has not been walked.
