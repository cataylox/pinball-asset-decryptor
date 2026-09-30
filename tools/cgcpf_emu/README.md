# CGC Pulp Fiction emulator rig

Runs Chicago Gaming's **Pulp Fiction** (2023, pin RV1_0_2) on this PC from
CGC's own card image, the way `tools/pb_emu` runs Predator: the machine's
real program on its real OS, with the boards it talks to emulated. It boots
to attract mode and takes switches: coins give credits, Start starts a game,
the trough serves a ball into the shooter lane, the plunger puts it in play,
targets score, a drain returns it (PAD-274). Always hidden, always muted.

| title | image | status (2026-09-30) |
|---|---|---|
| Pulp Fiction 1.0.2 | `PulpFiction102Installer.img` | attract, coins, a game, scoring |

The WPC remakes (Medieval Madness, Attack from Mars, Monster Bash) and
Cactus Canyon are CGC's PinMAME-based program, not this one: `prepare.py`
refuses them (exit 4). They are PAD-273's rig.

How it was worked out, and the contracts in detail:
`docs/plans/cgcpf_emulator.md`.

## The machine, and what stands in for it

A BeagleBone Black running Ubuntu 12.10: `/etc/rc.local` ->
`/home/ubuntu/startup.sh` -> `./pin`, a stripped 32-bit ARM hard-float
program (SDL 1.2 for sound, libdrm for the picture). It logs plenty
(`/tmp/z4.log`, every proc by name at log level 5, its first argument).

| the machine | the rig |
|---|---|
| the BeagleBone's ARM | qemu-arm (the kernel's binfmt entry), in a chroot of the machine's own rootfs |
| Ubuntu 12.10 on the eMMC | `rootfs.img`, carved from the card image by `prepare.py`, mounted read-only under a per-run overlay |
| HDMI, through libdrm dumb buffers | `pfshim.so` defines the `drm*` calls; the buffers live in `io/fb.bin`, `shot.py` makes a PNG |
| the PRU coprocessor running `pru_spi.bin`, `/dev/uio0` | a thread in `pfshim.so` answers the PRU's mailbox (shared RAM + 0x2000) |
| the playfield board on the PRU's SPI | that thread: the game's 41-byte packet in, the board's `'C'` packet with switches 0-63 back |
| the 8 KiB SPI FRAM (settings, audits, high scores) | that thread, on `$CGCPF_NV/fram.bin`, kept between runs |
| the cabinet switches on a GPIO bus (`/dev/mem`) | `pin`'s one bus-read routine (0x5667c) is hooked to read switches 64-79 from `io/io.bin` |
| `/dev/mem`, `/dev/spidev1.0`, the uio sysfs files | zeroed memory, accepting ioctls, fixed text |
| the RTC setting the clock | `settimeofday()` is a no-op (the process shares this PC's clock) |
| balls | `pfball.py`: counting, not physics (trough coil 11, auto-plunger coil 10) |
| speakers | none: `SDL_AUDIODRIVER=dummy` |

## Using it

As root in PAD-Runtime (`wsl -d PAD-Runtime -u root`), with `PAD_SLOT` and
`PAD_LABEL=PAD-n` set as for every rig:

```bash
python3 tools/cgcpf_emu/prepare.py /mnt/d/Pinball/images/CGC/PulpFiction102Installer.img
bash tools/cgcpf_emu/run_game.sh                # newest build; returns at attract
bash tools/cgcpf_emu/status.sh                  # state=attract|game, credits=...
python3 tools/cgcpf_emu/sw.py coin 4            # 4 x 25c = one credit
python3 tools/cgcpf_emu/sw.py tap start
python3 tools/cgcpf_emu/sw.py launch            # the plunger (a skill shot waits for it)
python3 tools/cgcpf_emu/sw.py tap "jet left"    # any name from `sw.py list`
python3 tools/cgcpf_emu/sw.py drain
bash tools/cgcpf_emu/shot.sh /mnt/c/tmp/pf.png
bash tools/cgcpf_emu/killgame.sh
bash tools/cgcpf_emu/bootcheck.sh PulpFiction102   # VERDICT line
bash tools/cgcpf_emu/build.sh                   # developers: rebuild pfshim.so
```

* **The first boot** reads ~600 MB of sound banks: a couple of minutes when
  the cache is on C: (later boots ~30 s, from the page cache).
* **The cache** (`rootfs.img`, 3.4 GB) goes to `/var/tmp/pad_cgcpf/cache`
  when PAD-Runtime has 4 GB free there, else `C:\tmp\pad_cgcpf`
  (`CGCPF_CACHE` overrides).
* **Coins** are 50 ms taps: the coin handler refuses a switch held much
  longer (a jam).
* **The game's state** is read out of its memory (`peek.py`, root):
  `status.sh` names it. The game's own log is `$CGCPF_RIG/tmp/z4.log`;
  `score.log` beside it has every score.
* `CGCPF_FRESH=1` starts the FRAM over; `CGCPF_MODES=1280x800,...` changes
  the monitor's modes (the game takes the smallest 1280-wide one at least
  768 tall; the picture is laid out the same).

**Never `pkill pin`**: every slot's game is `./pin`. Stops go by the game's
root (this slot's overlay) and `CGCPF_MARK`.

## What the picture is

The HDMI output is the game's **service monitor**: switch banks, lamp and
solenoid banks, PWM levels, the FRAM, the raw SPI packets, and a state line
(`GAMESTATE:ATTRACT`, then `GAMESTATE:GAME PLAYER:1(OF 1) BALL:1(1)
SCORE:0000600 ...`). It paints the page a slice at a time into its three
buffers, so `shot.py` lays them over each other (`--front` for the one on
screen). Nothing else in the program draws for players: the GPIO bus only
reads the cabinet, and the program imports no call that could send on its
network socket (it only asks the interface for its IP and MAC).

## Not done yet

* **The Emulate tab.** A follow-up ticket: this rig speaks `status.sh`
  key=value lines and posts to the rig board like the others.
* **Drop targets, the briefcase motor, the saucers** are not modelled: the
  power-up test logs 4 switch errors and a briefcase motor timeout, and the
  game plays on.
* **Other builds.** The cabinet hook and the state/credit addresses are
  pin 1.0.2's; the hook checks the bytes it replaces and leaves any other
  build alone (its cabinet switches then read open).
