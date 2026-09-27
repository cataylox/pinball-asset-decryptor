# Ticket intake: every change to this repo goes through a PAD-n ticket

## What and why

David, 2026-09-27: *"i don't consistently use "next" when picking up tasks in
this repo, it can come from a fresh message, triage, discord, etc. is there a
way to enforce picking up new items all through the same "channel"? ... i want
better organization that enforces isolation and organization like in
pad-triage - that's a great example of how our loose requests should go
through, but I don't necessarily want to expose to the discord channel my
internal conversations"*. His choices: internal tickets are **set up only**
(no automatic session), the old `/next` queue is **imported as tickets**, and
the repo **hard-blocks** work outside a ticket.

Before this, nothing enforced anything. The rules lived in skill prose
(`/next`, `/branch`, `/finish`) that a session only follows when it is
invoked, and the one hook (an untracked `.git/hooks/commit-msg`) blocked only
main commits whose subject began "Item N". Work that arrived as a plain
message landed on whatever checkout the session opened - usually main.

## Design

**One channel: pad-triage.** It already gives a user's report everything
wanted here - a number, a `ticket/PAD-n` branch and worktree in its
automation clone, a session keyed to that worktree, an approval gate, and a
serialized merge-and-release. pad-triage v0.9.0 (`f5ae5ca`, its own repo)
adds **internal tickets** (`padtriage/internal.py`):

- never visible to the Discord bot: `/api/state` leaves them out unless the
  caller asks with `?all=1` (the dashboard does, the bot does not), so it
  fails closed without the bot's code knowing they exist
- set up at once (worktree ready when `new` returns), no automatic session,
  no reply draft; closed straight after the release
- `padtriage_cli.py new | start | ready | list | import-queue`, the same over
  `POST /api/internal`, and a "New internal ticket" button on the dashboard
- `import-queue` turns the open items of `plans/TODO.md`'s Queue section into
  QUEUED internal tickets (a pushed `item/<N>` branch is continued, not
  restarted)

**The `/ticket` skill** (`~/.claude/skills/ticket/SKILL.md`) is how a session
opens or resumes one and works it: full request text as the ticket's record,
all edits and commits in the ticket's worktree, `ready` with a summary that
the release notes are written from, then David approves.

**Enforcement in this repo:**

- `.claude/settings.json` (now tracked: `.gitignore` ignores `.claude/*` but
  re-includes this one file) runs `scripts/hooks/require_ticket.py` before
  every Edit, Write and NotebookEdit. It refuses a file in a checkout of this
  repo whose branch is main/master/detached, and says to run `/ticket`.
  Allowed: other repos and no repo; `ticket/*`, and the lanes being drained,
  `feature/*` and `item/*`; main during a merge or squash; main while
  `<git dir>/PAD_RELEASE` is under two hours old (`/release` touches it);
  gitignored files; `PAD_ALLOW_MAIN=1` (the emergency override, announced).
  Any failure of the guard itself lets the edit through.
- `.githooks/commit-msg` (installed by `scripts/install_hooks.py` as
  `core.hooksPath`) refuses a commit onto main unless it is a merge or squash
  landing, a release commit (subject `vX.Y.Z ...`), queue-only bookkeeping, or
  `PAD_ALLOW_MAIN=1`. It replaces the untracked "Item N" hook.

**Deliberately not done:** Bash writes (`sed -i`, redirects) on main are not
intercepted - the commit hook stops them from landing, and intercepting every
shell command would be guesswork. pad-triage's dashboard still listens on all
interfaces with no token (the phone and ntfy buttons use it); internal
tickets are on it too.

## Status

**2026-09-27, pass 1.** pad-triage v0.9.0 committed and pushed (its tests
86 + 1 skip; the staged tree alone 58 + 1). The guard and the hook here:
`tests/test_require_ticket.py` 20/20 on Windows and under WSL, including the
commit hook in a real repository (blocked plain commit, release subject,
override, ticket branch and its `--no-ff` merge, queue-only). Checked on the
real checkouts: an edit to `pinball_decryptor/app.py` on the main checkout is
denied; `plans/notes.md` there (gitignored), the rig-slots worktree and
pad-triage are allowed. The `/ticket` skill is written.

Not yet exercised end to end: a real `ptc new` against the running dashboard
(it needs the v0.9.0 restart), and the queue import.

## At merge - in this order

1. Restart PAD Triage (tray: Restart) so v0.9.0 is running; check the
   dashboard shows the "New internal ticket" button.
2. Import the queue: `python <pad-triage>/padtriage_cli.py import-queue
   C:/Users/david/Documents/development/pinball-asset-decryptor` (11 open items
   today; re-running imports nothing twice).
3. Merge this branch (`/finish feature/ticket-intake`, or by hand). From that
   moment every session in the main checkout is refused edits.
4. `python scripts/install_hooks.py` in the main checkout, and again in
   pad-triage's automation clone (`pad-triage/work/repo`).
5. `/release`: at its start `touch "$(git rev-parse --git-common-dir)/PAD_RELEASE"`,
   at its end `rm -f` it - in `~/.claude/skills/release/SKILL.md` and the
   repo's `.claude/commands/release.md`.
6. Retire `/next`, `/add` and `/branch`: replace each SKILL.md body with a
   pointer to `/ticket` (the queue is now tickets). Keep `/finish` until the
   last `feature/*` and `item/*` branch has landed.
7. The rig-lock protocol text in `docs/plans/rig_slots.md` (feature/rig-slots)
   names the rig holder by ticket: `riglock.sh take --any PAD-n ...`.

## How to test it

`python -m pytest tests/test_require_ticket.py` (and under WSL). By hand after
step 4: on the main checkout, `git commit --allow-empty -m "x"` is refused,
`PAD_ALLOW_MAIN=1 git commit --allow-empty -m "x"` passes (then reset it away).
In a Claude Code session in the main checkout, ask for any edit: the Edit is
refused with the `/ticket` message; `/ticket <what>` opens PAD-n and the edit
succeeds in its worktree.
