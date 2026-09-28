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
  nothing moves `DROP TARGET OPTO`. Answered in PAD-248 - see "The drop
  target (PAD-248)" below.
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

## The drop target (PAD-248)

john_wick_le 1.01.0, `motorcheck.sh` 40 s from Start with the car model on
(its `c40i=` field now splits node 9's coil fires by index: 06 = DROP TRIP,
08 = DROP RESET):

| run | DROP fires |
|---|---|
| nothing held | 139 (06:69, 08:70) |
| a ball held at CAR FRONT OPTO (77) | 138 |
| DROP TARGET OPTO (81) held made | 0 |

The burst on the wire: RESET, TRIP 100 ms later, five pairs 250 ms apart, a
1.8 s pause, again. A game wanting the target UP has no reason to fire TRIP
after every RESET, and the opto held made satisfies it, so the game is
dropping the target and waiting for the opto to read MADE = down.

The first RESET goes out 34 ms after the Start press: it is the game's own
start-of-game drop, not a response to anything else in the rig.

PAD-237's own sweeps disagree with each other: its `model` sweep read 140
fires with nothing held and 0 with a ball at CAR FRONT OPTO (the ticket's
"it stopped when a ball was held"), its `final` sweep the reverse - 0 with
nothing held although a game started (BALL 1 on screen), 140 with the ball.
Here, on the same card and model, three sweeps fired every time with or
without the ball. So the car is not what decides it, and why those runs were
not asked is NOT known; each rig slot keeps its own NVRAM, and a game that
has given up on a device it logged as failing is the candidate, not a
finding. None of that changes the answer: whenever the game drops the
target, the opto now says so.

`MOTOR_SETTLE` (seconds to wait after attract before Start, default 8) was
added on the way: a first sweep of three rigs at once pressed Start while
john_wick_le still showed its STANDARD GAME MODE card, no game started, and
every count read 0. 45 starts a game every time.

**The model** is `ballmodel.DropTarget` (pass 2: `DropBank`), run by the ball feeder (it already
polls the coil counters at 50 Hz and writes switches): TRIP -> the switch goes
to its down level `PAD_DROP_MS` (default 30) later, RESET -> the other level.
A bank is matched by NAME (`ballmodel.DROP_BANKS`: DROP TRIP, DROP RESET,
DROP TARGET OPTO), so only john_wick_le has one today. `PAD_DROP_TARGET=0`
turns it off, `PAD_DROP_DOWN=0` flips the polarity.

| run (model on unless said) | DROP fires |
|---|---|
| 40 s | 2 (one RESET, one TRIP; the feeder closes 81) |
| 40 s, `PAD_DROP_DOWN=0` | 139 |
| 40 s, a ball held at CAR FRONT OPTO | 2 |
| 120 s | 2 |
| 120 s, `PAD_DROP_TARGET=0` | 380 |

## Every title's banks (PAD-248, pass 2)

David: "do the other titles too". The model became `ballmodel.DropBank`: an
optional TRIP coil, a RESET coil and every switch of the bank, TRIP making
them all and RESET opening them all. `DROP_BANKS` lists 18 banks on 12
titles by name (a bank is answered only when the title has its coils AND
every switch, so "3 BANK DROP" on jaws_le and on metallica each match only
their own switches). No title without a bank resolves one (godzilla_pro: 0).

From Start with nothing held, no title but john_wick_le retries a drop coil
(11-title sweep, `coils=` field). So the proof is the other half: hold every
bank switch made (targets down) at Start. With nothing answering, the game
fires RESET until they open; with the model, once.

| title | bank(s) | RESET fires in 40 s, model off -> on |
|---|---|---|
| james_bond_le 1.06 | CENTER 3 BANK (optos) | 60 -> 1 |
| jaws_le 1.02 | 3 BANK | 45 -> 1 |
| star_wars_le 1.30 | FORCE 5 bank | 12 -> 1 |
| king_kong_le 0.97 | 4 BANK | 9 -> 2 |
| james_bond_60th_le 1.11 | INLINE (trip), LEFT 4 BANK 'BOND', CENTER 3 BANK | 5, 5, 5 -> 1, 1, 1 (c40i) |
| beatles 1.29 | LEFT 3, RIGHT 4, CENTER 4 | 3, 3, 3 -> under 3 each |
| deadpool_pro 1.16 | LIL DP 3 BANK (trip) | 3 -> 0 |
| metallica_spike 1.03 | 3 BANK | 3 -> under 3 |
| led_zeppelin_le 1.22 | 3 BANK DROP Z-E-P | 150 -> not measured |
| john_wick_le 1.01 | DROP TARGET OPTO (trip) | 139 -> 2 (pass 1) |

(`coilcount.py` prints coils fired 3 or more times, so "under 3" is a
coil that dropped out of the list; `c40i` counts node 9 exactly.)

**Not proven on the rig, and why:**

- led_zeppelin_le with the model on, and jurassic_park_the_pin either way:
  the runs landed on rig slots whose NVRAM had never finished Stern's Guided
  Setup, and sat on its language menu ignoring Start (`started=no`). The
  slot where both titles had started (rig 1) was taken by another ticket.
- deadpool_le: no rig slot ever got it to take Start, with or without the
  model and the holds (`deadpool_le.bare`) - an existing rig fault with this
  title, not this change. Its LIL DP bank is the same coils as deadpool_pro's
  (proven); which of its two 4-bank reset coils is DEAD and which is POOL
  (LEFT = DEAD, RIGHT = POOL here) is a reading of the names, not a
  measurement.

`motorcheck.sh` now says whether the game started (`started=` - the feeder
serving a ball; Start pressed up to three times) and, when it did not, prints
the feeder's last lines and the switch edges.

**Seen on the way, not this ticket:** beatles and james_bond_60th_le fire
their TROUGH eject 22 times in 40 s from Start (`coils=TROUGH=22`), and
jurassic_park_the_pin an unnamed node 8 index 1 coil as often (the eject
index on most titles); deadpool_le never takes Start on any rig.
