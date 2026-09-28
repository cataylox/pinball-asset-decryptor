# A node board's motor: john_wick_le's car (PAD-237)

## What and why

David, 2026-09-01, on a live john_wick_le run: *"when i start a game, i
continually hear car tire screeches. I believe this is because the CarMec is
supposed to move into position when the game starts, and it is not getting
the feedback that it needs."*

He was right about the shape and the filed item (queue item 88) was wrong
about the mechanism. It assumed a COIL drove the car and planned a
`PAD_COIL_PROBE` run to find which one. There is no car coil. The car is a
motor the **node board runs by itself**, and the game only talks to the board.

## What the wire says (john_wick_le 1.01.0, node 9)

Found with `PAD_NB_TRACE=1` (the coil probe only logs changed payloads and ran
out of its 20000-line budget in attract):

| cmd | frame | what it is |
|---|---|---|
| 51 | `51 00 44 43 0f 00 00 00 d0 51 52 00 00 80 ...` once a second, **no reply asked** | configure motor 0: stop switch `0x40\|4` (CAR MOTOR HOME), `0x40\|3` (CAR MOTOR AWAY); outputs `0x50\|0x80`, `0x51`, `0x52` |
| 53 | `53 00 fa 14 c8 00` | send motor 0 HOME (speed / accel / decel: the CAR MOTOR HOME/AWAY SPEED, ACCEL, DECEL adjustments) |
| 54 | `54 00 fa 14 c8 00` | send motor 0 AWAY |
| 52 | `52 00`, every 50 ms, 4-byte reply | the board's status - byte 2 is its inputs 0..7 |

The outputs 0x50..0x52 are LED-class device records named `CAR MOTOR ENABLE`,
`CAR MOTOR CONTROL 1A`, `CAR MOTOR CONTROL 2A` (group 8, index 80/81/82). They
have x = y = 0, so `devicexy.py` drops them and they are in no cached table -
which is why nothing in the rig had ever named them. `findrec`-style: search
the ELF for a pointer to the name string; the record is `image`, `(group,
index)`, `(class, 2)` from there.

## How byte 2 was pinned down

`carcheck` / `motorcheck.sh`: boot, start a game, count cmd 53/54 on node 9 for
40 s. With the rig answering zeros: **35 x 53 and 31 x 54** - a re-send every
~0.9 s, and every send is the screech.

- `PAD_NB_CFILL=52:<v>` (every reply byte = v), 9 builds: 08 stops the 53s,
  10 stops the 54s, 01 / 03 / ff stop both, 02 / 04 / 80 change nothing.
- `PAD_NB_CREPLY=52:<bytes>` (new, exact bytes), 8 builds: only **byte 2**
  matters.
- Then the reading that explains all of it: node 9's switch bits at rest are
  `1b` - inputs 0, 1, 3, 4 sit at their INACTIVE level 1 (optos and stop
  switches are active-low). So byte 2 is the board's own inputs, raw, and a
  zero reply said HOME and AWAY made at once plus a ball at every car opto.
  `08` = HOME made with a ball at the car's front, so no 53 is needed and
  the car must go AWAY (54, never arrives); `10` the reverse; `01` = no
  ball at the car, so no move is wanted at all.
- Mirroring the node's last 0x11 switch byte into byte 2, 5 builds: nothing
  held -> 0/0; HOME or AWAY held -> 0/0; FRONT OPTO held (a ball at the car)
  -> 0 x 53, 33 x 54 (the game sends the car away and it never arrives);
  mirror off -> 35/31.

## What the rig does now (hwshim.c)

- **cmd 52 reply byte 2 = the node's first switch byte**, as the last 0x11 of
  that node was answered, on any node the game has sent a cmd 51. One state,
  two readers: the switch poll and the motor status cannot disagree.
- **The motor model** (`motor_note`, `motor_tick`): cmd 51 names each end's
  stop input; cmd 53 / 54 send the motor to an end. The stop it leaves opens
  at once; the one it is sent to closes `PAD_MOTOR_MS` later (600, inside the
  game's ~0.9 s re-send). A re-send while travelling is not a new move. The
  car starts between the stops (position unknown) and the game homes it at
  boot. Edges go into the switch MERGE tagged `m`, so the game, `[sw]` and
  every padsw reader see one state; last edge wins, so a held switch still
  overrides the car until its next move.
- `PAD_NB_MOTOR=0` puts back the zero reply and stops the model.
- Result, john_wick_le: 0 re-sends from Start; a ball at the car sends it
  away (54) and home again (53), one arrival each, `[motor] ... arrived`.

Proven: `tests/test_spike2_node_motor.py` (the real functions compiled out of
hwshim.c, fed the real frames), the rig sweeps above, and the whole-library
boot sweep below.

## Not done, and why

- **The car's ball optos** (FRONT / HOLD / BACK). Nothing carries a ball into
  the car, so they stay open: a car with no ball. Modes that lock a ball in
  the car will wait for one that never comes, as they would have before.
- **The drop target** on the same title: `DROP RESET` then `DROP TRIP` (node 9
  coils 8 and 6) fire in bursts of five pairs every ~3.3 s from Start, because
  nothing moves `DROP TARGET OPTO`. Not the screech - but the same kind of
  unanswered device. It stopped when a ball was held at the car's front
  opto, so the game ties the two together somehow. Its own ticket.
- **The motor's own status bits.** Bit 0 of byte 2 is CAR FRONT OPTO; no other
  byte of the 52 reply was seen to matter, and no busy or fault bit was
  looked for. If a title's board motor ever needs one, `PAD_NB_CREPLY` is the
  instrument.

## Other titles

Whole library, `rigbatch.sh` over the 33-build list with bootcheck plus the
`[motor]` config lines (2026-09-27): **33/33 boot to attract**. At least 13
titles configure a board motor (a fast boot can be stopped before cmd 51, so
"none" below is not proof of none - john_wick itself read none at 20 s):

| title | motors (cmd 53 stop / cmd 54 stop) |
|---|---|
| batman 1.13 | node 9: m1 13/8, m2 2/4 |
| deadpool_le 1.14, deadpool_pro 1.16, star_wars_elg 1.10 | node 12: m0 none/none |
| star_wars_le 1.30 | node 12 m0, node 9 m0: none/none |
| elvira3 1.13 | node 9: m0 9/3, m1 -/12, m2 -/0, m3 -/24 |
| iron_maiden_le 1.16 | node 9: m0 24/25, m1 1/0 |
| james_bond_le 1.06 | node 9: m0 1/- (the JETPACK: home opto 1, encoder optos 2 and 3) |
| jaws_le 1.02 | node 9: m0 38/32 |
| jurassic_park_le 1.16 | node 9: m0 4/6 |
| mando_le 1.44 | node 9: m0 0/1 |
| sword_of_rage_le 1.18 | node 9: m0 none/none |
| uncanny_xmen_le 0.98 | node 12: m0 4/6 |

Then `motorcheck.sh`, model on vs `PAD_NB_MOTOR=0`, 40 s from Start, on the
eight with stop switches:

- batman, iron_maiden, jaws, jurassic_park, mando, uncanny_xmen: 0 moves
  either way - nothing looped from Start, nothing changed.
- elvira3: the game sends motors 1-3 to their stops in attract; all three
  arrive in 600 ms and are never sent again.
- **james_bond_le: off = 20586 x cmd 53 in 40 s** (about 500 a second - a
  flood nobody had noticed because nothing plays a sound for it); **on = 136**,
  a pair every ~0.7 s. Improved, not answered: the JETPACK is an ENCODER
  motor (`53 00 28 20 e8 03` - speed 40, accel 32, and 1000 as a LE16 where
  john_wick sends 200) and the game wants pulses on its encoder optos while it
  moves, which this model does not make. Its own ticket, with jaws_le's
  SHARK POSITION 1..7 (the original item's generalisation; jaws showed no
  loop from Start, but its stops are inputs 38 and 32, past the byte 2 this
  reply is known to carry).

Payload of cmd 53 / 54, from the two titles: motor, speed, accel, then a LE16
(200 on john_wick = its DECEL (MS) adjustment; 1000 on the jetpack).

# An encoder motor: james_bond_le's JETPACK (PAD-249)

## What was asked, and what turned out to be true

The follow-up above asked for encoder PULSES while the jetpack moves, and for
where inputs above 7 live in the 52 reply. Reading the game answered both,
and neither was the fix:

- **The 52 reply is not the board's inputs. It is a status word for the motor
  the request names** (`52 <motor>`). james_bond_le 1.06 reads it at
  0x5aa23c as two LE16s: bytes 0-1 = the position the board has counted,
  bytes 2-3 = flags. john_wick's BidirectionalMotor reads the same four bytes
  the same way (0x4f2f24, flags 0x08 done / 0x80 fault). PAD-237's "byte 2 =
  raw inputs" answered the car because its stop switches happen to sit on
  those bit positions; it is left in place for end-stop motors because it is
  measured to work there, and nothing past bit 7 needs finding.
- **No encoder pulses.** The board counts the encoder itself. The game never
  reads the encoder optos, and when it configures the motor it sends the node
  a cmd 71 mask with those two inputs cleared (0x33b4e0 -> 0x5aa5f8).

## The jetpack's protocol (EncoderMotor, JetPackMotor derives from it)

| cmd | frame (node 9) | what it is |
|---|---|---|
| 51 | `51 00 41 00 00 43 42 00 c0 42 41 20 00 28 01 ...` | configure motor 0: home opto input 1 (`0x40\|1`), ENCODER inputs 3 and 2 (payload bytes 4-5 with 0x40). A reversed variant (`c1 ... 41 42`) is sent for the second home |
| 53 | `53 00 28 20 e8 03` | home: speed 40, accel 32, LE16 time 1000 ms |
| 55 | `55 00 0a 00 40 e8 03 00` | go to position: LE16 target (signed), speed, LE16 time, flags |
| 52 | `52 00` -> 4 bytes | this motor's status: LE16 position, then flags 0x01 moving, 0x08 homed and done, 0x40 fault |

The tick (0x33b6b8 / JetPackMotor 0x1e05b8) is a small state machine: config
+ home, config + home again, then "calibrated" and position moves (the
play routines at 0x1e0244.. ask for 10, 24, 31..40, 33). Every tick it polls
52, and a reply with **none of 0x01 / 0x08 / 0x40** makes it configure and
home the motor from scratch. The zero reply did that every tick: 20586 x cmd
53 in 40 s from Start.

**hwshim.c now plays an encoder motor** (motor_note / motor_tick /
motor_status): cmd 51 with encoder inputs marks the motor; 53 homes it
(moving, then after PAD_MOTOR_MS homed at position 0 with the home opto
made); 55 sends it to a position (moving, the count climbing pro rata, the
home opto open while away from 0); 52 is answered from that state.

## The rest of the loop was rig-wide: every board re-initialised every 0.7 s

With the status answered the jetpack still homed twice every ~708 ms. Hooks
found why, one step at a time (PAD_PASS_HOOK / PAD_REG_HOOK):

1. `33aac4` (EncoderMotor home) called every 708 ms from JetPackMotor v[17],
   itself called from 0x33aba8 - the listener for **event 135**, "re-home the
   encoder motors on node N".
2. Event 135 is raised by the node service loop when it re-initialises a
   board: `34c170` fired every **101 ms** - one board per visit, the whole bus
   every ~0.7 s - always from the **fault branch** 0x34edb8.
3. That branch is taken when the `ff` status poll's word B & 0x8010211f. The
   rig answers `ff` with zeros; the bit came from the game itself: 0x5ae930
   sets bit 31 of word B when **word A differs from a per-node counter**, and
   `PAD_REG_HOOK=5ae9f0` showed that counter at 2..167 on every poll.
4. The counter is the game's count of ADDRESSED frames sent to the board since
   the last poll (0x5a8068, +1 per frame with byte 0 & 0x80; zeroed after the
   poll and by cmd f1). A real board reports how many it received; the rig
   said 0, so every visit read as "this board lost frames".

**The rig now counts what the game counts** (nb_rx_count_tx, per node, byte 0
& 31, f1 resets it) and word A of the `ff` reply says it. `PAD_NB_RXCOUNT=0`
restores the zero. This touches every title - it is why the change needed the
whole-library sweep below - and it corrects the item-52 note on the `ff`
reply, which read the stored zero as "the previous value is always 0".

`PAD_NB_FLAGWATCH=<node>` is the instrument left behind: that board's flag
word and every reply the rig sends it, logged on change.

## Result

james_bond_le 1.06, motorcheck.sh, 40 s from Start:

| rig | cmd 53 sends |
|---|---|
| zero reply (`PAD_NB_MOTOR=0`) | 20586 / 19958 / 20272 |
| PAD-237 end-stop model | 136 (a pair every ~0.7 s) |
| encoder status only | 136 (re-homed by every board re-init) |
| encoder status + frame count | **2** (the one home the game asks for at Start) |

With the count right the board re-init (`PAD_PASS_HOOK=34c170`) never fires in
the run. The jetpack homes twice at boot, once at game start (event 78, by
design), and is then sent to position 10 by cmd 55 - the first position move
the game has made on the rig.

## Not done

- **jaws_le's shark is not a board motor.** SharkMotor derives from
  SingleDirectionCoilMotor: a coil runs it and the game reads SHARK POSITION
  1..7 and the UP/DOWN-MAG switches as it turns. That is a coil-driven mech
  with position switches - its own model, its own ticket.
- A motor that faults (0x40) is never simulated; the jetpack never stalls.
