# Shared fake P-ROC (PAD-262)

One emulated P3-ROC for every title built on the P-ROC family: American
Pinball (all titles, pyprocgame / SkeletonGame), Dutch Pinball's Big Lebowski
(pyprocgame) and AAIW (native C++ with libpinproc linked in), Spooky's Rick and
Morty and Alice Cooper (pyprocgame). The per-title rigs (the AP, DP and Spooky
tickets) build on it: this ticket delivers the board, not a title.

`tools/proc_emu/`. Nothing in it is guessed: the protocol is the open-source
libpinproc (`PRDevice.cpp`, `PRHardware.cpp`, `pinproc.h`) and pypinproc,
and the self-test runs the real ones against it.

## The board: one FPGA model, two ways in

A P-ROC / P3-ROC is an FPGA behind an FTDI USB FIFO. libpinproc writes 32-bit
words to it (big-endian bytes) and reads words back. `prochw.py` is that FPGA,
listening on `fpga.sock`:

| host sends | FPGA does |
|---|---|
| write burst `1 len mod addr` + len words | manager (watchdog, dips), switch config (host events on/off), driver globals / groups / table (coils, lamps), PD-LED writes (`0xC00`), switch rules (notify host, linked drivers, drive-now), DMD config + frames (P-ROC) / aux (P3-ROC) |
| read request `0 len mod addr` | the same header, then len words: chip id `0xf33db33f`, version 2.17, watchdog, dips; switch state words (bit set = OPEN) and debounce words |
| (nothing) | unrequested header + event word when a switch changes and its rule says notify; DMD frame events when enabled |

Two hosts reach it:

1. **Python level** - `pystub/pinproc.py`, a pure-Python port of pypinproc
   *and* the libpinproc under it. The same constants, `decode()` (PRDecode,
   char arithmetic included), `driver_state_*`, `aux_command_*`, `PinPROC`,
   `DMDBuffer` - and `PinPROC` speaks the real word protocol to `fpga.sock`.
   Python 2.7 and 3.x, nothing to build. `run_py.sh -- python game.py` puts it
   first on `PYTHONPATH`.
2. **Native level** - `fakeftdi.c`, a libftdi1 (`libftdi1.so.2`) whose device
   is the socket. Bytes pass through untouched. `run_py.sh --real` preloads it,
   so a title's own libpinproc / pypinproc (or AAIW's binary) runs unchanged.

Because both levels talk to one FPGA model, the ctl socket drives both the
same way, and a behaviour difference between them is a bug the self-test sees.

Fidelity rules kept from the C: uint8 pulse times (300 ms -> 44), C-int dict
fields (a schedule comes back negative), `now` counted only when it `is True`,
the switch-config write on the first rule (pypinproc's static), decode()
setting the machine type `aux_command_output_primary()` reads, PDB driver
slots blank (driverNum 0) until the game writes them (pyprocgame's `pdb.py`
writes all 208 at start). One C undefined behaviour is pinned: machine
defaults read the 26-group polarity table for drivers 208-255; the stub uses
the last group.

## Switches at power-on

The ticket's warning: FakePinPROC's `switch_get_states` is all zeros (every
switch open), so a trough sits in ball search. The real picture is sharper:
**the AP troughs are NC optos** (`type: NC` in BBQ, Houdini and LoV's yamls) -
a ball in the trough *interrupts* the beam, so a full trough is OPEN contacts.
So all-open means a full trough on AP and an empty one on a NO-switch trough.

`prochw.py --yaml <machine.yaml>` seeds by meaning, not by contacts: the
trough holds `PRGame.numBalls` balls (switches named `trough<N>`, lowest N
first - BBQ has 7 trough optos and 6 balls, so `trough7` is empty), every other
switch is at rest, and contacts follow from `type`: an NC switch at rest is
CLOSED (coin door, drop targets, ramp optos), an active one open. `--balls`,
`--active`, `--closed` override. The ctl `sw <name> 1` means "active" the same
way; `closed <sw> 1` sets raw contacts.

## Using it

```
hw.sh --yaml <game>/config/machine.yaml     # the board, this PAD_SLOT
run_py.sh [--real] [--detach] -- python2 launcher.py
ctl.sh sw startButton 1 | tap leftSling 80 | state | switches | drivers | log 20 | leds
status.sh                                   # key=value, for the app later
killgame.sh                                 # game + board, proven stopped
```

Paths live in `procpath.sh` only: `/var/tmp/pad_proc/rig<slot>/` holds the
sockets, `prochw.log`, pids; `build.sh` builds fakeftdi into
`/var/tmp/pad_proc/lib` on demand (nothing binary is checked in).

`ctl log` is the board's driver history: every change with who caused it -
`host` or `rule sw66 closed` (a hardware rule the game installed, e.g. a
flipper or sling). That is how a title rig will see a trough eject, a flipper
fire, a lamp schedule.

## Proof (`selftest/`)

`selftest/build_real.sh <python>...` fetches libpinproc (dev `286c566`),
pypinproc (master `a4e1b97`) and pyprocgame (last Python 2 commit) at pinned
revisions and builds them against fakeftdi - libpinproc compiles against
`selftest/include/libftdi1/ftdi.h`, a header-only slice, so no libftdi1-dev
or libusb is needed. pypinproc is Python 2 C API only; `py3port.py` changes
its API spelling (not behaviour) for 3.x.

`selftest/run.sh` then, each on a fresh board with `selftest/machine.yaml`:

| check | what |
|---|---|
| `probe-{stub,real}-{2.7,3.12}` | `probe.py`: 40 lines covering decode across machine types, driver-state helpers, the board (states, rules, events, linked flipper drivers, host drivers, schedules, patter, LEDs, watchdog, raw `write_data`). All four runs print **identical** lines: the stub equals real libpinproc + pypinproc |
| `probe-c` | `probe.c`, a native libpinproc program in AAIW's shape on fakeftdi: PRCreate finds the P3-ROC, trough seeded, event arrives, sling rule fires its coil, host pulse and LED land |
| `demo-{stub,real}-2.7` | `demo_game.py`, a pyprocgame `GameController`: load_config (PDBConfig programs the board), enable_flippers, run loop. It reaches attract and counts **3 balls through its own switch objects** (NC optos), the start button pulses the trough coil, the flipper button fires the flipper through the hardware rule |

Result at the time of writing: all 7 VERDICTs pass from a clean build.
`tests/test_proc_emu.py` (24 tests, runs anywhere) pins the same behaviour
in-process, with golden values printed by the real libpinproc.

The pyprocgame demo is 2.7 only: upstream pyprocgame's Python 3 port was
never finished (a circular import, float driver numbers, `list.sort(cmp)`).
AP BBQ (3.12) ships its own working py3 procgame; booting it is the AP
ticket's job, and it needs that game's own dependencies (`oscpy`, SDL2 ...).

## What the title tickets add

- the game's Python and packages (AP 2.7 titles, BBQ 3.12; the survey found
  pygame/pysdl2, OpenGL, `oscpy` in BBQ), a display, sound
- its `machine.yaml` into `hw.sh --yaml`, and any title switches to seed
  beyond the trough (LoV's `troughEject` opto is not a `trough<N>`: decide
  whether a ball sits there and pass `--active troughEject`)
- a ball model on top of `ctl log` (trough eject coil -> trough opto opens,
  shooter closes), as `bofhw.py` does for BoF
- AAIW: its binary on `run_py.sh --real` (check its libftdi imports against
  fakeftdi's exports first: `nm -D --undefined-only <bin> | grep ftdi_`)
- then the Emulate tab (a follow-up once a title boots)
