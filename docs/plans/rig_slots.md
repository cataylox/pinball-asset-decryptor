# Rig slots: several Spike 2 emulator rigs on one PC, and seeing who holds each

## What and why

David, 2026-09-27: *"why do we impose rig locks when triaging or working on
items that need the emulator? i have 4 conversations going right now, and one
has locked the rig. can we spin up multiple instances so that we are not
locking others?"* and then: *"ideally, i want to visualize the locks somehow
too (each window that pops up should say what ticket it's coming from, we
should have feedback in the triage app that the emulator rig is locked, etc.).
having some visual feedback is really important to me"*.

Until this branch there was ONE rig per PC. Worktrees gave each session its
own code, but every session shared one guest rootfs (`~/spike2root`: builds,
NVRAM, tables, save states and the rings in `dump/`), one renderer build, one
set of run logs in `~`, and a `killgame.sh` / `alive.sh` pair that saw every
rig process on the machine. The single lock file (`~/.pad_rig_lock`) made
sessions take turns so that one session's Stop would not kill another's run.
Two sessions that did not take turns got two guests and two renderers sharing
one ring (2026-08-06).

## Design

### A rig slot is a complete rig, layered over the ordinary one

`PAD_SLOT=N` (1..`PAD_SLOTS_MAX`, default 4) selects slot N; unset or 0 is the
ordinary rig, exactly as before. All of it is derived in `padpath.sh`
("RIG SLOTS"):

| | slot 0 (unchanged) | slot N |
|---|---|---|
| guest rootfs `PAD_ROOT` | `~/spike2root` | `~/padslots/N/root`, an **overlayfs**: lower `~/spike2root`, upper `~/padslots/N/upper` |
| rings, NVRAM, tables, save states, shim, GL bridge, selector | under the rootfs | under the rootfs, so in the slot's upper layer |
| renderer build `PAD_GLHOST_BIN` | `~/padglhost` | `~/padslots/N/padglhost` |
| build stage `PAD_STAGE`, override stage | `~/emusrc`, `~/override` | `~/padslots/N/emusrc`, `.../override` |
| run logs `PAD_LOGDIR` | `~` | `~/padslots/N` |
| card mountpoints `PAD_CARDS` | `~/card` | `~/padslots/N/card` |
| audio relay port `PAD_AUDIO_PORT` | 45997 | 45997 + N |
| window position files | `~/.pad_windows`, `%USERPROFILE%\.pad_playfield.json` | `.pad_windows.rigN`, `.pad_playfield.rigN.json` |
| `.pad_env` instrument knobs | `~/.pad_env` | `~/padslots/N/.pad_env` |

**Why an overlay.** The rootfs is tens of GB and the disk has 8 GB free, so a
copy per slot is impossible, and a hard-linked copy is worse than none (a
build rewriting `hwshim.so` in place would rewrite every slot's). A fresh
slot's upper layer is empty and a full boot writes ~54 MB into it.

**Mounting takes root**, so it happens where root already is: the app's runs,
`slot.sh up N`, and `riglock.sh take` run through `wsl -u root`. `watch.sh`
refuses a slot that is not mounted and prints the one line that mounts it.
The mount lasts until WSL restarts; the upper layer survives.

**The lower layer is live.** A slot 0 build or `mktables` changes what every
slot sees for files the slot has not written itself. That is intended (a slot
starts from the current rig), and it is why `ensurebuild.sh` refuses a slot 0
rebuild while ANY slot's guest is up: truncating the base `hwshim.so` under a
slot's mapped copy would SIGBUS someone else's run.

### Every process knows its slot: `PAD_SLOT` in its environment

`PAD_SLOT` is exported by `padpath.sh`, so every child inherits it, the guest
included (`run_game.sh` never clears the environment). `padslot.sh` reads it
back from `/proc/<pid>/environ`:

- `pad_slot_of`, `pad_pids`, `pad_count`, `pad_pkill` replace every `pgrep` /
  `pkill` in the run path: `killgame.sh`, `alive.sh`, `status.sh`, `watch.sh`
  (teardown, renderer checks, the main loop), `runbridge.sh`, the save/load
  scripts, `slots.sh`, `restorestate.sh`, `autoattract.sh`, `swexercise.sh`,
  `longplay.sh`, `cardmount.sh`, `modes/gamecheck.sh`, `modes/soak.sh`.
- `padglhost.c` (`pid_in_my_slot`) and `pausekeep.py` pause only their own
  slot's game; before this, Pause froze every guest on the machine.
- **Unreadable = another account's process = slot 0.** A check run as the
  desktop user cannot read a root run's environment. Counting those as slot 0
  keeps a slot-free machine exactly as before (the app's status poll runs as
  the user and must keep seeing the root run it started). A slot >= 1 check
  never counts them; run it as root for an exact answer.
- **Gone is not unreadable.** `watch.sh` forks short-lived subshells whose
  command line is `watch.sh`'s; one that exits between `pgrep` and the read is
  `-`, nobody's. (First live run: those read as two phantom slot 0 runs.)
- **Windows processes** have no environment the rig can read, so the slot is
  on the command line: the audio player's port, and `--pad-slot=N` on a slot's
  playfield window (`playfield.py` ignores it). Slot 0's Stop matches only
  playfield windows WITHOUT the marker.
- `audioreset.sh` keeps a machine-wide count on purpose: `wsl --shutdown` ends
  every slot's run.

### The board: who holds which slot, readable from everywhere

`%USERPROFILE%\.pad-rig\` (from WSL: `/mnt/c/Users/<name>/.pad-rig`; derived
from the rig's own Windows path, or `PAD_BOARD`). It is on the Windows side
because every reader is somewhere else: the sessions' rig runs in Ubuntu, the
app's in PAD-Runtime (a different distro that cannot see Ubuntu's files or
processes), and the app window and the triage dashboard run on Windows.

- `slot-N.lock`: one line of JSON, `{"slot","who","what","distro","user","taken"}`.
  mtime = the holder's last word. Written by `riglock.sh`.
- `slot-N.run`: one line of JSON, `{"slot","game","label","distro","root","pid","started"}`,
  written by `watch.sh` at start, touched every ~10 s by its main loop, removed
  by its teardown and by `killgame.sh`. A record whose mtime stops moving is a
  run that died hard.

`riglock.sh take --any <who> [what]` takes the first free slot (atomic `set -C`,
proven O_EXCL on drvfs), `note`, `release` (refused while a run is up in the
slot, judged by the run record's heartbeat AND `alive.sh`), `list [--json]`,
`free`. **Slot 0 also writes the pre-slot `~/.pad_rig_lock`**, so a session on
the old protocol still sees the ordinary rig as held.

### Who is it for: the label, on every window

`pad_label` (padpath.sh) = `PAD_LABEL`, else the holder of this slot's lock,
else `PAD_TICKET` (the triage app sets it), else the branch of the checkout the
rig runs from (read off `.git` files, since git in WSL cannot follow a Windows
worktree pointer; `ticket/PAD-n` shows as `PAD-n`, main shows nothing).
`watch.sh` fixes it once per run and exports `PAD_TITLE_TAG`:

- **Renderer windows** (`padglhost.c` `title_tag()`): `[rig 1: item/48] godzilla_pro - Stern Spike 2 emulator`,
  the legend and the second display the same way. The tag goes at the FRONT,
  because a taskbar button cuts the end off. Plain ASCII, because X11's WM_NAME
  is Latin-1.
- **Playfield window** (`playfield.py`): the same prefix on its title (which
  also makes `raise_existing()` per slot: before, two sessions on one title got
  one window, the first session's), plus a **coloured band across the top and
  a chip in the status bar** (`pfpage/pf.css` `--rig-N`, `pf.js`). Five
  colours: rig 0 grey, 1 cyan, 2 violet, 3 coral, 4 green; the app and the
  triage dashboard use the same ones.
- David's own runs from main in rig 0 have no label, and their titles are
  exactly as before.

"rig", not "slot", in everything a human reads: the app already calls save
states "slots".

### What it deliberately does not do

- Per-slot CPU limits. Each guest is ~1.5 cores; `PAD_SLOTS_MAX` is the only
  brake.
- The card image CACHE (`~/cardcache`) stays shared: it is a cache of an image
  file, and two slots mounting one card each get their own read-only fuse
  mount over it.
- `padwinpos.py` / `zorder.py` (diagnostic window recorders, not in the run
  path) still match by title needle with no slot filter.

## Status

**2026-09-27, pass 1: the rig core, emulator-proven with two concurrent rigs.**

Proven on real titles, `godzilla_pro` in rig 1 and `turtles_pro` in rig 2, both
booted at the same time (Ubuntu, Xvfb :7 because this VM's WSLg X server was
down, muted):

- one `game` process per rig, each with its own `PAD_ROOT`; one renderer per
  rig on its own `padgl` ring (two separate 64 MB rings in the two upper
  layers); ~54 MB written per upper layer for a full boot
- `status.sh` per rig: rig 1 `state=attract fps=52`, rig 2 `state=techalerts
  fps=55.5`, each from its own log
- `alive.sh`: rig 0 = 0, rig 1 = 13, rig 2 = 13 with both up
- renderer titles on the X display: `[rig 1: feature/rig-slots] godzilla_pro -
  Stern Spike 2 emulator` and `[rig 2: ...] turtles_pro - ...`
- playfield windows on Windows: `[rig 1: feature/rig-slots] godzilla_pro -
  virtual playfield` and the rig 2 one
- **`PAD_SLOT=1 killgame.sh` killed rig 1's 13 processes and left rig 2
  running** (still `running=1 state=attract fps=60.5` afterwards); its board
  run record was removed and rig 2's kept; then rig 2's own Stop cleaned it
  to 0
- `riglock.sh take/list/release` for slots 0-2, including the legacy lock file

Seen during the test, and the reason this branch matters: another session's
app run in PAD-Runtime stopped and restarted (metallica, then munsters) while
my rigs were up, and both of my playfield windows disappeared. The old
`killgame.sh`'s Windows backstop kills every `playfield.py` on the PC, across
distros. After merge, rig 0's Stop matches only unmarked windows.

**Owed**

- The app: pass `PAD_SLOT`/`PAD_LABEL` through, show the board on the Emulate
  tab, tag the app's title with its rig.
- The triage dashboard (sibling repo `pad-triage`): rig panel, header badge,
  `PAD_TICKET` into every session's environment (crossing into WSL via WSLENV).
- The `/next` skill's lock protocol (`~/.claude/skills/next/SKILL.md`) and
  `plans/TODO.md`'s non-negotiable move to `riglock.sh`. **Only at merge**:
  the skill is live for every session, and main's scripts do not know slots
  yet.
- Tests.
- A save state in a slot (criu over an overlay root): not tried yet.

## How to test it

Targeted tests: `python scripts/testpick.py` on the diff.

By hand, in WSL (Ubuntu), from this worktree's `tools/spike2_emu`:

```
wsl -u root -e bash <rig>/riglock.sh take --slot 1 feature/rig-slots godzilla run
wsl -e bash -c "PAD_SLOT=1 PAD_AUDIO=0 PAD_GAME=godzilla_pro bash <rig>/watch.sh 8"
wsl -e bash <rig>/riglock.sh list
wsl -e bash -c "PAD_SLOT=1 bash <rig>/alive.sh"
wsl -e bash -c "PAD_SLOT=1 bash <rig>/killgame.sh"
wsl -e bash <rig>/riglock.sh release 1 feature/rig-slots
```

Start a second slot beside the first and check that each slot's `alive.sh`
counts only its own, and that one slot's `killgame.sh` leaves the other up.
