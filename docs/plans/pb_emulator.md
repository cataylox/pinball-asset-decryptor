# Pinball Brothers Predator on the FAST emulator (PAD-271)

**Goal** (the 2026-09-29 survey's scope for every maker): a rig under
`tools/pb_emu` that boots the game to attract mode on a PC and takes switch
input, emulator-proven. The app's Emulate tab is a follow-up ticket.

**Result (2026-09-30):** done. Predator 1.0.1 (`pbpp_predator_game_1_0.upd` +
the `_1_0_1` delta) boots to attract with 0 diag errors, draws its real
screens, and plays: coins, Start, the trough serving, the launch button
firing the auto-launcher, targets scoring, a drain with ball save and a
re-serve. Two slots run side by side. The survey's rating 2 held; the
predicted main cost (Ghidra on pinprog) mostly disappeared because pinprog
ships unstripped with full DWARF.

## What the update is

A plain gzip+tar of the machine's `/opt/game` (4,003 files, 4.7 GB): only
`pinprog`, `vidprog`, `audio/`, `media/`. No OS, but none is needed:

* `pinprog` - FreeWPC-derived C (`hp-freewpc`, Heighway's fork: the source
  tree path is in the binary), machine `raven`, platform `pb`. Links libm,
  libpthread, librt, GNU Pth (`libpth.so.20`, FreeWPC's native task
  scheduler), SDL2 + SDL2_mixer. Not stripped, DWARF 5: `gdb` prints
  `names_of_switches`, `names_of_drives`, `switch_table` after `break main`.
* `vidprog` - C++, SDL2/_image/_ttf, GStreamer (`uridecodebin` -> `appsink`),
  libxml2. Connects to pinprog on 127.0.0.1:5555 and plays what it is told.
* Built on PB's Yocto SDK (`/opt/pb-os/1.0`, glibc 2.40, GCC 14.2) but
  needing at most GLIBC_2.39 / GLIBCXX_3.4.29 - Ubuntu 24.04's are enough.
  The one incompatibility is the loader path `/lib/ld-linux-x86-64.so.2`;
  prepare.sh patches it to `/lib64/...` with patchelf.
* No licence check stopped it: `platform/hp/secure.c` / `crypt.c`
  (`secure_init`, `secure_string_get/put`, `blockcrypt`) were not read in
  detail, but the game runs with an empty `nvram/`, creates its files
  ("Creating file N") and plays. It exits if the `nvram/` directory is
  missing.

## FAST as fast.c speaks it

Read from the disassembly (`objdump -l` gives `fast.c:<line>` per
instruction; a small helper resolves rip-relative string operands) and
confirmed by running. Session 290d11's Ghidra decompiles agreed.

**Ports.** Both `/dev/ttyACM0` and `ttyACM1` open O_RDWR|O_NONBLOCK; four
`"    \r"` flush each, then `ID:` alternates until one answers with
`ID:NET FP-CPU` (strncmp 13) - that is NET, the other EXP.

**Reader** (`fast_read`, lines end `\r`): `-L:xx` / `/L:xx` are switch events
(`phy_switch_update(n, '0'|'1')`: `-` = active), `!B` is a board booting,
`XX:F` is dropped; ANY other line is copied into the reply buffer being
waited on. So a reply to a command the game does not wait for corrupts the
next wait - `WD:`, `SL:`, `TL:`, `RS:`, `MP:`, `EA:` must stay silent.

**Waited for** (`fast_write_*` with response type != 0):

| command | reply | reader |
|---|---|---|
| `ID:` (NET) | `ID:NET FP-CPU-2000 02.26` | `fast_identify` |
| `CH:2000,01`, `DL:...` | `CH:P`, `DL:P` | CONFIRM: char after ':' is `P` |
| `NN:<n>` | `NN:<n>,<name>,01.00,<drv hex>,<sw hex>,...` | `fast_get_node_name`: strtok(".,"): node, name, major, minor, drivers, switches |
| `SA:` | `SA:10,<15 bytes hex>` | `fast_read_switches`: cc-1 bytes; bit set = closed; an opto's bit is inverted (`switch_is_opto`) |
| `ID@<addr>:` (EXP) | `ID:EXP <name> 00.10` | stored for the service page |
| `BR:`, `EM:`, `ER:`, `MF:<m>,<a>,<b>` (wake-up) | `XX:P` | CONFIRM |

**Boards** (raven.log "adding board"): NET nodes `FP-I/O-0024` (8 drivers,
24 switches), `FP-I/O-3208` (8/32), `FP-I/O-1616` (16/16), `FP-I/O-3208`
(8/32) = 104 switches, 40 drivers. EXP: `48` FP-CPU-2000 (the Neuron's own
LEDs), `B4` FP-EXP-0071, `D0` FP-EXP-0051, `30` FP-EXP-1313; `EA:B40` selects
board B4 breakout 0, then `RS:<led><rrggbb>`.

**Sequence:** ID both ports -> `CH:2000,01` -> `WD:` -> `NN:00..03` ->
per EXP board `ID@x:` + `BR:` -> `SA:` -> `DL:` x48 -> `SL:` x120 -> motors
`EM:`/`MP:`/`MF:` -> attract. `WD:000005DC` every second after.

**Switch polarity.** `-L` = active for every switch in events (the board
applies an opto's `SL: mode 02` itself). Getting this wrong for the trough
optos made the game re-kick forever ("kick blocked by kick_request hook"):
it never saw the ball leave. `INTERLOCK` (4) must be active (coin door
closed) or the main toy refuses to move ("Motion request canceled by
interlock switch").

**Drivers** (`TL:<sol hex>,01` pulses; the numbers are `names_of_drives`,
not the FAST driver index `drvN` the log also prints): 0x11 TROUGH RELEASE,
0x10 AUTO LAUNCH (fired by the timed launcher when LAUNCH BUTTON is
pressed, and by ball save), 0x17/0x18/0x1C drop bank resets.

## The rig

`pbpath.sh` (paths, slot, `PB_MARK`), `setup.sh` (conda-forge SDL/GStreamer/
libxml2/patchelf + Debian `libpth20` into `/var/tmp/pad_pb/env`), `build.sh`
(`pbshim.so`), `prepare.sh`, `run_game.sh`, `killgame.sh`, `shot.sh`,
`status.sh`, `bootcheck.sh`, `sw.py`, `pbfast.py`, `pbtitles.py`. See
`tools/pb_emu/README.md` for the table of machine -> rig substitutions.

Decisions:

* **Mount namespace, not a chroot** - the programs only need `/opt/game`
  and a writable cwd; `/opt` is a private tmpfs with the build bound in,
  and `/etc/init.d` is replaced by a stub `S11vidprog`.
* **TCP 5555 moved per slot by the shim**, not a network namespace: in
  PAD-Runtime the rig's Xvfb listens only on an abstract socket, which a
  private netns cannot see.
* **Kills filtered by `PB_MARK`**, never by name: PAD-272's rig (Alien,
  Queen, ABBA) runs programs also called `pinprog` and `vidprog`, as the
  same user.
* **Muted by default** (`SDL_AUDIODRIVER=dummy`, no Pulse): an early trial
  in another distro played through WSLg.

## Owed / next

* The Emulate tab (follow-up ticket), with a virtual playfield from
  `pbtitles.py`'s switch names, and the installer shipping `tools/pb_emu`.
* The main toy (helicopter/minigun motors and the `TOY *` sensors) is
  answered but not modelled.
* `setup.sh` fetches ~700 MB of conda packages; if the tab ships, the same
  micromamba env AP uses could be shared.
