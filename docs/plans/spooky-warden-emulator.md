# PAD-267: a Warden board emulator for Spooky's Unity and Godot titles

## The ask

David, 2026-09-29, one slice of the emulation survey: answer the real
`/dev/WARDEN` protocol (PAD-266's Beetlejuice rig only answered the handful
of requests Beetlejuice needs to boot) so switches, coils, LEDs and steppers
behave, and extend the rig to the other Warden-era titles on
`D:\Pinball\images\Spooky` - survey each, confirm its hardware link, boot it
to attract and take switch input. App wiring is a follow-up.

## What the survey found (per title, confirmed from each build's code)

| title | build | engine | board | verdict |
|---|---|---|---|---|
| Beetlejuice | v2026.09.15.11 | Unity 2022.3 Mono | Warden | runs (PAD-266) |
| Scooby-Doo | v2025.12.01.09 | Unity 2022.3 Mono | Warden (`Warden.cs`) | runs |
| Texas Chainsaw Massacre | 1.00 | Unity 2019 Mono | Warden (`pinAPI.IOsystem = 20`; a Pinotaur path exists but is not selected) | runs |
| Evil Dead | 2026.07.15 | Unity 2022.3 Mono | Warden (`warden.cs`, threaded, fixed-length replies) | runs |
| Looney Tunes | 2025.10.08 | Godot 4.1.2 (custom), PCK in the ELF | Warden (`autoloads/warden.gd`, wjwwood serial) | runs |
| Ultraman | 1.18 | Unity | **Pinotaur** (`/dev/pinheck`, `/dev/ttyUSB<n>`), no Warden code | refused: PAD-268's board |

The protocol is one firmware seen from five hosts; the argument count of
every opcode agrees across all of them (tabulated from every `warden_send` /
`send_message` call), which is what lets the board frame the stream exactly
instead of scanning it.

Differences that mattered:

* **Replies.** Evil Dead and Texas Chainsaw read replies as fixed-length
  frames (152: 2 bytes, 168: 5, 151: 7, 212: 1) and reject anything else;
  Evil Dead checks hardware info is exactly `WARDEN\0` and reconnects
  otherwise; Looney pings with hardware info every 2 s. PAD-266's
  `WARDEN (PAD rig)` would have failed both, so the board answers `WARDEN`.
* **Finding the port.** The Unity games open `/dev/WARDEN`; Looney lists
  ports first (glob of `/dev/ttyACM*`, `/dev/ttyS*`, `/dev/ttyUSB*`, ...), so
  the shim's `glob()` adds `/dev/WARDEN` to the ttyUSB pattern.
* **Desktop mode.** Only Beetlejuice has one. The others shell out to
  `sudo`/`unlock-root`/`reboot`/`avrdude`/`timedatectl`; the rig puts
  logging no-ops first on their `PATH` (PAD-Runtime has no `sudo` at all,
  but a `reboot` must never be a real one).
* **Rest state.** Balls at rest: 6 (Beetlejuice, Evil Dead) or 7 (the rest;
  a short trough means a ball search, and Texas Chainsaw refuses Start).
  Texas Chainsaw's orbit diverter rests down (switch 43); Evil Dead's
  lower-playfield ball and standing drop targets are made at rest.
* **Settings.** Each game keeps them in folders of its own under `/game`
  (`code/config`, `audits`, `game_settings`), so `/game` itself is the kept
  directory per slot and title.

## What was built

`tools/spooky_emu`: `spktitles.py` (profiles + detection from `app.info` or
the Godot pack's `project.binary`), `spkwarden.py` rewritten as a framed
full-protocol board with per-title mechanics, `spkshim.c` (+ `glob`),
`xinerama_stub.c` (Godot 4.1 needs a libXinerama; PAD-Runtime has none),
`prepare.sh` (every format; refuses Pinotaur and P-ROC updates by name),
`run_game.sh` (layouts, persistent `/game`, no-op commands, `uname`, the
Godot launch line), `spk_attract` (attract per title, from the game's log or
the board's), a title-aware `sw.py` and virtual-playfield table (`spkswitches.py`, for the AP window PAD-266 moved to).
`tests/test_spooky_emu_rig.py` covers the board, the profiles and detection.

## Proof

Hidden runs in PAD-Runtime rig slot 1 (see the ticket's report): each of the
five boots to attract (`bootcheck.sh` VERDICT pass, pictures) and was
played: coin, Start, served by its eject coil, launched by its launch coil,
switches scored. Evil Dead's hand homed through the emulated stepper, and
its serve followed the diverter servo to the right lane.

## Left for later

* Offer the four new titles in the app's Emulate Spooky tab (file types,
  supported-games card, labels).
* Ultraman and Halloween: a Pinotaur board (PAD-268).
* Scoops, VUKs, locks, toys: switches pressed by hand, as on the other rigs.
