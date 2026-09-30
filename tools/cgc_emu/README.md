# Chicago Gaming emulator rig (the WPC remakes)

Runs Chicago Gaming's remakes of the Williams WPC-95 games on this PC from
the card images CGC publishes: the machine's own ARM program under
`qemu-arm`, on hardware this rig makes up (`cgcshim.so`).  It boots to
attract mode and takes switches: coins are booked, Start serves a ball from
the trough, the launch button fires the autoplunger, drains return balls
(PAD-273).  Always hidden (the screen is a file; `shot.sh` makes a picture)
and muted.

| title | card image | status (2026-09-30) |
|---|---|---|
| Medieval Madness 3.0 | `MedievalMadness300Installer.img` | attract, coins, serve, launch, drain, ball save |
| Attack From Mars 1.0 | `AttackFromMars100Installer.img` | attract, coins, serve (bootcheck pass) |
| Monster Bash 1.03 | `MonsterBash103Installer.img` | attract, coins; Start does not serve yet (below) |
| Cactus Canyon 1.13 | `CactusCanyon_cc113_9-2-25_card.img` | refused: CGC's Z5 engine (below) |

The Emulate tab for these is a follow-up ticket; nothing in the app calls
this rig yet and the installer does not ship it.

## What the machine is

A BeagleBone Black (TI AM335x, armhf, Debian 7.5, glibc 2.13).  The card's
third partition holds `/emmc.img`, the image the installer writes to the
eMMC; its second partition is the game's Debian, and `/home/debian/emumm`
is the game: `emumm` (Steve Ellenoff's WPC-95 emulator - a 6809 running the
original Williams ROM, PinMAME's WPC core underneath - with CGC's colour
LCD, menus and DCS-replacement sound on top), the ROM, `cgc.so` (CGC's
art), `*data/` (sounds).  The program keeps its symbols.

| the machine | the rig |
|---|---|
| the BeagleBone | `qemu-arm-static -L <build>/sysroot` (the card's own libraries) |
| McSPI + 4 GPIO banks through `/dev/mem` | `/dev/zero`-backed memory; the once-a-millisecond board exchange (`io()` on MM, `sam_io()` on AFM/MB) returns at once, patched at its entry by name |
| the SPI FRAM (the game's NVRAM: settings, audits, high scores) | a model of the chip at the program's `spix`/`spi_cs_*` byte exchange, backed by `$CGC_ROOT/nv<slot>/<title>/fram.bin`, kept |
| the 1280x768 LCD (libdrm dumb buffers on `/dev/dri/card0`) | the `drm*` calls answered by the shim; the three RGB565 buffers live in `$CGC_RIG/fb` with a header naming the one on screen (`cgcshot.py`) |
| the playfield and backbox boards | the program's own switch array, written by the shim: `sw.py` |
| the speakers | SDL's dummy audio driver |
| `/tmp/z4.log` | a private `/tmp` per rig (`$CGC_RIG/tmp`) |

`prepare.sh` mounts the card **read-only** on two nested loop devices and
copies only the game folder and the ~50 libraries it loads (~270-320 MB a
title).  PAD-Runtime's disk is small: check `df -h /var/tmp` first.

## The board (cgcshim.c)

* **Switches.**  A set bit in the array is a closed switch, except an opto,
  which reads set when clear.  At power-up the program leaves the array as
  the machine at rest (balls home, coin door closed); MB's leaves its optos
  blocked and its ROM then says CHECK FUSES F101 AND F109 ... OPTO 12V
  SUPPLY, so the board clears every opto it knows before the balls go home.
* **Names.**  `cgcroms.py` reads the switch, flipper and coil names out of
  the Williams ROM's own test-menu tables (English page; entry 0 of each
  table is its "invalid number" text - MM's coil 1 is AUTO PLUNGER, coil 2
  TROUGH EJECT).  `sw.py list` prints them.
* **Balls** - counting, not physics.  `cgctitles.py` builds `$CGC_BALLS`
  from those names: the trough (TROUGH BALL 1-4, closed = a ball), the
  TROUGH EJECT coil (kicks position 1 at once, the rest roll down after
  400 ms, the ball reaches the SHOOTER LANE after 600 ms - a game that sees
  nothing move re-kicks), the AUTO PLUNGER coil (shooter lane -> in play),
  kickouts (MM: LEFT POPPER, RIGHT EJECT, CATAPULT), two-position motors
  (MM drawbridge; MB bank and Frankenstein table).  Coil pulses are read at
  1 kHz; `$CGC_RIG/events` logs one line per pulse.
* **First boot.**  A new FRAM makes the ROM restore factory settings and
  wait; `run_game.sh` presses ENTER, then ESCAPE until the lamps run, as an
  operator would, once per slot and title.

## Using it

As root in PAD-Runtime (`wsl -d PAD-Runtime -u root`), with `PAD_SLOT` and
`PAD_LABEL=PAD-n` set as for every rig:

```bash
bash tools/cgc_emu/prepare.sh /mnt/d/Pinball/images/CGC/MedievalMadness300Installer.img
bash tools/cgc_emu/build.sh                  # developers: rebuild cgcshim.so
bash tools/cgc_emu/run_game.sh <build>       # returns at attract (15 s; 65 s the first time)
python3 tools/cgc_emu/sw.py coin 4
python3 tools/cgc_emu/sw.py tap start
python3 tools/cgc_emu/sw.py tap "launch button"
python3 tools/cgc_emu/sw.py tap "left slingshot"   # any name from `sw.py list`
python3 tools/cgc_emu/sw.py drain
python3 tools/cgc_emu/sw.py on enter         # coin door: D1..D8, flippers F1..F8
bash tools/cgc_emu/shot.sh /mnt/c/tmp/mm.png --scale 2
bash tools/cgc_emu/status.sh
bash tools/cgc_emu/killgame.sh
bash tools/cgc_emu/bootcheck.sh <build>      # VERDICT: attract, coins booked, a ball served
```

`CGC_FRESH=1` on `run_game.sh` starts the slot's settings over.  Never
`pkill qemu-arm`: other rigs run it; every stop here goes by `CGC_MARK`.

## Not done yet

* **Monster Bash** reaches attract and books coins, but after Start pulses
  the UP/DN BANK MOTOR every 1.5 s and never serves: the bank model (either
  rest end) is not what the game waits for.
* **Cactus Canyon** runs `/home/debian/pin`, CGC's own "Z5" engine (a native
  C re-implementation, no 6809: `z5_spi_*`, `z5_fram_*`, `z5_sw_*`,
  `z5_sol_*`, plus a USB "saloon" kit).  The same approach applies with a
  second hook map; `prepare.sh` refuses it with exit 4 until then.
* The colour: the shots show CGC's green DMD dots; whether the card's
  default is a colour palette (`cgc.so` replacement art) was not checked.
* A visible window, sound, and the Emulate tab (with a switch window).
