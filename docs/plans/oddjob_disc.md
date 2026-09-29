# Bond 60th's Oddjob disc spins in the emulator (PAD-259, was queue item 86)

## The ask

David, 2026-08-28, during the item 80 sweep: "You have to hit the odd job rotating spinner mechanism a lot of times, and I don't see the optos on the playfield or the switch matrix for me to interact with."

Item 86 was filed on `item/86` the same day and never merged, so the 2026-09-27 queue import skipped it. David asked for it again on 2026-09-29.

## What the disc is

An absolute angle sensor on node board 9 (a pinnode), read over the node bus. Read out of james_bond_60th_le 1.11 (addresses in the `nb_disc` comment in `tools/spike2_emu/hwshim.c`):

- **The read.** `cmd 61 [bit] [thr lo] [thr hi]` returns 4 bytes. `w0 & 0x3ff` is the angle, 1024 counts a turn. `w1` is a signed speed.
- **When the game reads.** Only on a 0-to-1 edge of the board's `Angle Sensor Threshold` input (bit+11). The game then forces that bit to 1 in its own copy, so every reading needs a fresh edge.
- **What counts.** A reading counts as motion when it moved more than 15 counts. The disc rule adds motion into steps using DISC SPIN DIFFICULTY and DISC SENSITIVITY THRESHOLD.
- **What is not read.** The ten `Angle Sensor 0..9` switch rows are status mirrors. Item 86's first `disc.py` drove them, and nothing moved.

## What changed

- **`hwshim.c` (`nb_disc`).** The first `cmd 61` names the sensor's node and bit. After that, every rising edge the shim reports on the Threshold input turns the disc `PAD_DISC_STEP` counts (default 24), and the next `cmd 61` answers with the new angle.
  - A read with no edge before it keeps the zero reply. That is the boot-time field-strength refresh.
  - `PAD_DISC=0` restores the zero reply.
  - No per-title constants: the node and bit come from the game's own request.
- **Spinning it.** A rip on the Threshold switch spins the disc.
  - **Playfield window:** a "Spin disc (hold)" button in the key panel's BALLS section. It appears only on a title with an `Angle Sensor Threshold` switch, because that switch has no place on the artwork.
  - **Command line:** `disc.py [seconds]` finds the same switch by name in the title's switch list and rips it.
- **`watch.sh` NVRAM check.** It also refuses a run when any file inside the title's NVRAM is root-owned and unreadable. One such `LKRAM/00000008.crc32`, left by an elevated run, stopped Bond 60th with FATAL 256 in every rig, under a folder the old check passed.

## Proof (rig 1, james_bond_60th_le 1.11 card)

- **Spinning Disc Test, before and after.** Main, spinning: every field 0. This branch, the same spin: Raw Position 465, Spin Ticks 15, Angle 104.06, Rpm 112.50, and the Light Position moving round.
- **In a game.** Spin Ticks counted 1 to 21 over a 4 s spin, and 10 on the next ball.

## Not done

- **A disc award or mode in play.** The game says "SHOOT BOND TARGETS TO LIGHT ODDJOB DISC". Awards need the disc lit first, and that was not driven here.
- **Field strength** stays at the zero reply, which the test screen shows as `0(Normal)`.
- **The button on a live rig.** It sends the same rip `disc.py` sends through the same driver call; it was proven by a unit test and the demo page, not pressed on a live rig.
