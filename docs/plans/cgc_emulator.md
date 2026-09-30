# PAD-273: emulate the CGC WPC remakes (and Cactus Canyon)

## The ask

David (2026-09-29), from the emulation survey: a rig under `tools/cgc_emu`
that boots Chicago Gaming's games to attract mode on a PC and takes switch
input, emulator-proven.  The Emulate tab is a follow-up once it boots.
Survey rating 3.5; titles Medieval Madness, Attack From Mars, Monster Bash,
Cactus Canyon; material `D:\Pinball\images\CGC\*.img`.

## What was found (and what the survey got wrong)

* The survey's plan held: `qemu-arm` + the card's own armhf libraries, a
  shim for `/dev/mem`, the IO functions hooked by name, a fake libdrm.
* The survey said CC's `pin` "has the same structure (z5_*)" as `emumm`.  It
  does not: `emumm` is a WPC-95 emulator running the Williams ROM; `pin` is
  CGC's own engine with a different symbol set.  CC is out of this ticket.
* Hooking at function entry was enough: `io()`/`sam_io()` return at once;
  nothing else polls a register.  The McSPI is shared with the **FRAM**,
  the game's NVRAM, read at power-up; the shim models the FRAM chip at the
  program's SPI byte exchange (a stubbed SPI crashed on a NULL register
  pointer first).
* Switch polarity cost the most: the power-up array is the machine at rest
  (PinMAME's convention: optos read set when clear) on MM and AFM; MB's is
  all zero.  And the ROM's coil table starts with a "Null" entry, so the
  first decode had every coil one off (the "trough eject" that kept
  re-firing was the autoplunger).

## Proof (2026-09-30, PAD-Runtime, rig slot 3, hidden, muted)

`bootcheck.sh` VERDICT pass for MM (first boot from a fresh FRAM, 66 s,
then 15 s) and AFM (15 s): attract, four coins booked in the FRAM, Start
fired TROUGH EJECT (coil 2) and the ball reached the shooter lane.  By hand
on MM: CREDITS 2 after four coins; BALL 1 after Start; LAUNCH BUTTON fired
AUTO PLUNGER (coil 1); after 12 s with no switch hit the game ran a WPC ball
search; a drain was answered by a ball-save serve and autolaunch.  The
service menu works (ENTER / ESCAPE / +/- on the coin door).  MB: attract and
coins; Start blocked (README).

## Left for later

MB's bank mechanism, CC's Z5 engine, colour, window/sound, the Emulate tab.
