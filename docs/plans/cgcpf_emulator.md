# Emulating CGC's Pulp Fiction (PAD-274)

## The ask

David, 2026-09-29: investigate adding emulation for the other manufacturers,
then queue the work. This ticket is the Pulp Fiction slice. The survey
(static, nothing run) rated it the hardest CGC title: a stripped binary, the
playfield driven by the AM335x PRU through a shared-memory mailbox, the
display drawn in code. Scope: a rig under `tools/` that boots the game to
attract mode on a PC and takes switch input, emulator-proven; the Emulate
tab is a follow-up.

## Result

`tools/cgcpf_emu` boots `pin` RV1_0_2 to attract in ~30 s (a couple of
minutes the first time), and `bootcheck.sh` proves the input path end to
end: four 50 ms coin taps give a credit, Start starts a game (the game's
state word goes 1 -> 2), the trough coil serves a ball that the game sees
in the shooter lane, the plunger puts it in play, and jets, spinners and
targets score (`score.log`: `JET 100 ... TARGET 100`, 600 points).

## How the machine was taken apart

The card image is a BeagleBone SD "installer": partition 3 (ext4) holds
`/emmc.img`, whose partition 2 is the Ubuntu 12.10 root. `/emmc.img` is in
29 extents, so `prepare.py` reads it through debugfs's extent map.

`pin` is stripped, but it links libdrm, SDL and libc dynamically and logs
everything with its function names, and it is Thumb-2 at fixed addresses
(non-PIE). A capstone pass with literal-pool and movw/movt string
resolution named the code by its log strings.

### The PRU mailbox (shared RAM + 0x2000)

The game links am335x_pru_package's `prussdrv` statically:
`prussdrv_open(0)` maps `/dev/uio0` (sizes from
`/sys/class/uio/uio0/maps/map*/`), requires the INTC revision
`0x4E82A900` at +0x20000 to call the part an AM33xx, loads `./pru_spi.bin`
into PRU0 and maps the shared RAM. The mailbox (read from
`spi_packet_xfer_pru`, `spi_packet_tx_pru`, `spi_packet_rx_pru`):

| word 0 bit | |
|---|---|
| 31 | go (ARM sets it last) |
| 30 | done / ready (PRU sets it; the ARM checks it before a transfer) |
| 29 | with 31: "firmware version" - the reply's u16 at +0x144 is major.minor |
| 19-16 | SPI clock divider |
| 15-0 | length |

tx bytes at +4, rx at +0x144 (320 bytes). The ARM polls word 0 up to
100000 times (a few ms under qemu) and then calls the transfer lost - so the
shim's PRU thread spins (sched_yield) while the bus is busy and only sleeps
after 3 s of quiet; FRAM writes are flushed to disk from another thread.

### The two SPI devices

* **The playfield board.** The game sends 41 bytes: `0x13`, 39 output bytes
  (lamps, solenoids, PWM), a checksum. The board's reply, found anywhere in
  the first 31 bytes: `'C'`, a type byte, 8 switch bytes (switches 0-63),
  checksum = low byte of the sum of the ten before it, a flag byte (0 = 8
  more bytes follow). Switch inputs are **active low**, except the game's
  optos (kind 1 in its runtime table at 0x456ee4: switches 0-10, 28, 32-35:
  the trough, jam, subway, case popper, briefcase stack), where a ball in
  the beam drives the input high.
* **The FRAM** (8 KiB): standard SPI FRAM commands, READ 03 / WRITE 02 /
  WREN 06, 13-bit address. The shim tells the two apart by the first byte.

### The cabinet: a GPIO parallel bus

Switches 64-79 (Start, coin door, flippers, coins, service buttons) are
read over a bit-banged bus: the game writes a chip select into a GPIO
DATAOUT register mapped from `/dev/mem` and reads eight DATAIN pins back
straight away - no gap a helper thread could fill. One routine does it each
loop (0x5667c, `read(uint8_t out[2])`), so the shim writes a Thumb
`ldr.w pc, [pc]` over its first 8 bytes at load time, sending it to C that
reads `io.bin`. It checks the 8 bytes first and leaves any other build
alone.

### The display

`modeset.c`-style libdrm: one connector, three dumb buffers, flips by
`drmModeSetCrtc`. The shim implements the `drm*` calls itself (a preload
wins over `libdrm.so.2`) and keeps the buffers in a file. What the game
draws there is its service monitor, painted in slices across the three
buffers. It chooses the smallest 1280-wide mode at least 768 tall; the
layout does not change with it.

### Coils

`gameTroughReleaseProc` fires coil 11, `gameShootBallProc` coil 10; coil
11 was seen at packet byte 21 bit 3, so coil n is byte 20 + n/8, bit n%8.
Coils are PWM'd, so `pfball.py` counts a coil as fired when its bit returns
after 150 ms away.

## Walls hit on the way, in order

1. `/dev/dri/card0` missing -> the libdrm stand-in.
2. `/dev/spidev1.0` opened first (mode/speed ioctls) -> accepted.
3. "PRUSetup: error mapping PRU shared memory" -> the INTC revision.
4. Transfers timing out -> the PRU thread's polling, FRAM saves off-thread.
5. The service page with every input reading closed -> active-low wire.
6. Balls "in" the subway and briefcase -> optos; then the trough is an opto
   too (the game's start check wants the trough count at 0x4503bc > 3).
7. Coins ignored when held 150 ms -> 50 ms taps.
8. The game as an unprivileged user could not reopen `/tmp/z4.log` (the
   image ships the machine's last one, root's) -> its own `/tmp`.
