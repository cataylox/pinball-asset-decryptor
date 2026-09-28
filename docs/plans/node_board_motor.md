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
