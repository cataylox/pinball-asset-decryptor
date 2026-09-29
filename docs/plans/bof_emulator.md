# Barrels of Fun emulator (PAD-257)

Run a Barrels of Fun title (Dune, Winchester Mystery House, Labyrinth) on a
PC, the way `tools/spike2_emu` runs a Stern Spike 2 game and `tools/jjp_emu`
runs a Jersey Jack one.

## Why this is the smallest emulator PAD has

A BoF `.fun` decrypts (GPG, per-title passphrase) to a tarball holding one
**native x86-64 Linux Godot 4 export** with its PCK embedded, plus the update
scripts (`updated_bash_profile`, `updated_updatecode`) and, on Dune, the worm
board's firmware (`worm_wrangler_main.bin`) and its flasher (`bossac`).

The binary needs only `libc` and `libm`, is **not stripped** (full symbols and
DWARF), carries no dongle, no licence check and no machine binding. Under WSL
it starts as is and draws through Vulkan (llvmpipe on a hidden Xvfb; the
host GPU through WSLg). With no hardware it stops at the game's own
"FAST HARDWARE NOT DETECTED" screen - that is the whole gap.

So there is no CPU to emulate, no GL/video bridge, no key. The work is the
hardware the game talks to over USB serial.

## The hardware, as the game's own scripts define it

The scripts are compiled GDScript (`.gdc`, Godot 4.5 bytecode) inside the PCK.
`pck_directory.read()` pulls them out; GDRE Tools (`--decompile`,
`--bytecode=4.5.0`) turns them back into readable source. Every protocol
reply in `bofhw.py` is shaped by the parser in these scripts, not by FAST's
documentation: the game's parser is the only reader that matters.

Engine side: a `SerialPort` Godot module wrapping the wjwwood `serial`
library. Its Linux port list globs `/dev/ttyACM*` (and ttyS/ttyUSB/...) and
reads each port's USB identity from sysfs:

| field | built from |
|---|---|
| `desc` | `<manufacturer> <product> <serial>` of the USB device |
| `hw_id` | `USB VID:PID=<idVendor>:<idProduct> SNR=<serial>` |

Game side (Dune, `autoloads/fast.gd` + `cooper/autoload_stems/fast_stem.gd`,
`autoloads/bics.gd`):

* **FAST Neuron, NET port** - first `/dev/ttyACM*` whose desc contains
  `FAST Pinball`, 921600 baud, `\r`-terminated ASCII.
  `ID:` -> `ID:NET <board>  <fw>` (the game reads `split(" ")[3]` and demands
  fw >= 2.26 or it starts flashing firmware), `CH:2000,01` -> `CH:P`,
  `CN:` -> one `NN:` line per node board (matched by substring against
  `0024-`, `3208-`, `1616-`, `3208-`; `split(" ")[5]` is the firmware),
  `SA:` -> `SA:<n>,<hex>` (switch n = bit n%8 of byte n/8, **physical** level:
  the game applies each switch's `reversed` flag itself), `SL:`/`DL:`/`TL:`
  switch config, driver config, driver action, `WD:` watchdog.
  Switch events: `-L:xx` active, `/L:xx` inactive (logical, no reversal).
* **FAST expansion bus** - the second FAST port. `ID@<board>:` for boards
  `48` (Neuron's own), `b4`, `84`, `86` -> `ID:EXP <name>  <fw>` (>= 0.44).
  Then `ER@`/`RF@`/`LM@` config and **binary** LED frames with no terminator:
  `RD@<board>:` + count + count x (index, r, g, b), `RL@` the same with a
  fade byte.
* **BICS** ("Barrels Interactive Control", Dune's worm wrangler) - the port
  whose hw_id contains `PID=2341:` (an Arduino), else `/dev/bof_worm`.
  `\r\n`-terminated replies. `ID:` -> `ID:WORM WRANGLER,..,<board>,v1.0.0`,
  then a homing handshake (`HOME:STEPPER ALL` -> `,ACK`, `HOME:EDGES?` ->
  `HOME:EDGES ACK`), magnet/flasher/profile `SET:`s, `MOVE:STEPPER`,
  `POSITION:STEPPER?` and `SET:OFFSETS?` (positions compare as STRINGS
  against the offsets, so named moves report the offset string exactly).
  Its four switches arrive with the prefixes REVERSED (`/L` = active) and map
  to game switches 49..52.

## How the emulator presents the ports

* `bofhw.py` makes one pty per port, links them as `<rig>/dev/ttyACM0..2`
  (+ `bof_worm`) and writes a fake sysfs tree under `<rig>/sys` with the USB
  identities above (FAST = 2e8a:1074 "FAST Pinball Neuron", BICS = 2341:003d
  "Arduino LLC Arduino Due").
* `bofhwshim.so` (LD_PRELOAD) rewrites only paths: `/dev/ttyACM*` to the rig
  dir (real ones are hidden), `/sys/class/tty/ttyACM*` to the fake sysfs, and
  `glob("/dev/ttyACM*")` lists the rig's ports under their `/dev` names. It
  also makes `TIOCMBIS`/`TIOCMBIC` succeed on a tty: a pty refuses them and
  wjwwood **throws** on that failure (`set_dtr`), which would abort the game.
* A control socket (`<rig>/ctl.sock`) sets switches: `sw <n> <0|1>`,
  `tap <n> [ms]`, `state`, `leds`.

## The host must be protected from the game

The game shells out through `OS.execute("sudo", ...)`: `mount -o remount,ro /`
and `remount,rw /` around every settings save, `sync`, `systemctl`, `iwctl`,
`bluetoothctl`, `dhcpcd`, `cp` over `/home/pinball/.bash_profile`. Run as
root in a WSL distro, the first of those remounts the distro read-only. The
rig therefore:

* runs the game as an ordinary user, never root;
* puts a logging no-op `sudo` (and `systemctl`, `iwctl`, ... `reboot`) first
  on `PATH` - seen in the first boot: 16 `sync`s, both remounts, two `cp`s;
* gives it its own `HOME`, so `user://` (settings, audits, high scores) lives
  in the rig dir.

## Proven (emulator-proven, Dune `GDHarvest_202600513`)

1. No hardware: boots, draws the backbox LCD (1280x720) and the playfield
   screen, stops at "FAST HARDWARE NOT DETECTED".
2. Emulated hardware: full handshake (Neuron identified and configured, four
   node boards, all four expansion boards, BICS homed), 32 drivers configured,
   ~430 LEDs driven, watchdog running -> **attract mode**.
3. Start pressed (switch 14): game starts, flippers enabled, trough eject
   (driver 0x27) fires, the model puts the ball in the shooter lane (79) ->
   **Ball 1, skillshot screen**.

## Open

* Winchester and Labyrinth: port logic, BICS devices and switch maps differ
  per title - each needs its profile.
* Ball model beyond the trough eject: launch, drain, multiball.
* Rig scripts in the repo's conventions (padpath, killgame, status, hidden by
  default, muted by default), then the app's Emulate tab and a switch panel.
* Audio (Dummy driver today) and GPU rendering (llvmpipe today).
