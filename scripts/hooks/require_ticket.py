"""Claude Code PreToolUse hook: no edits to this repo outside a ticket.

David, 2026-09-27: work reaches this repo from everywhere - a fresh message,
a triage email, a Discord thread, an idea mid-session - and he wants all of
it to go through ONE channel with the isolation pad-triage gives a user's
report: a PAD-n ticket, its own ticket/PAD-n branch and worktree, and main
moving only by that ticket's merge and release. Written rules did not hold
(the /next and /branch skills both said "never edit main"), so this refuses.

Wired in .claude/settings.json for Edit, Write and NotebookEdit. A file is
REFUSED when it sits in a checkout of this repo whose branch is main (or
master, or a detached HEAD) and it is not gitignored. Allowed:

  - any other repo, or no repo at all (scratchpads, memory, pad-triage)
  - a checkout on ticket/PAD-n, and the lanes still being drained: feature/*
    (the /branch skill's) and item/* (the /next queue's)
  - main while a merge or squash is in progress (conflict resolution when a
    ticket or branch lands)
  - main while /release is running: it touches <git dir>/PAD_RELEASE at its
    start (the version bump, README and tips are release commits), honoured
    for two hours so a crashed release cannot leave the door open
  - gitignored files (plans/, scratch outputs): not the repo's source
  - PAD_ALLOW_MAIN=1 in the environment Claude Code was started with - the
    emergency override, and it says so on every use

Exit 0 with a JSON deny decision refuses; any failure of THIS script lets the
edit through (a broken guard must not wedge every session).
"""
import json
import os
import subprocess
import sys
import time

LANES = ("ticket/", "feature/", "item/")
RELEASE_MARK_S = 2 * 3600


def _gitdir(root):
    """The checkout's git dir (a worktree's .git is a file pointing at it)."""
    g = os.path.join(root, ".git")
    if os.path.isdir(g):
        return g
    try:
        with open(g, encoding="utf-8") as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    d = line.split(":", 1)[1].strip()
    return d if os.path.isabs(d) else os.path.normpath(os.path.join(root, d))


def _common(gitdir):
    """Where a worktree's shared state lives (the main repo's .git)."""
    try:
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as fh:
            c = fh.read().strip()
        return c if os.path.isabs(c) else os.path.normpath(os.path.join(gitdir, c))
    except OSError:
        return gitdir


def checkout_of(path):
    """(root, gitdir) of the git checkout holding `path`, or (None, None)."""
    d = os.path.dirname(os.path.abspath(path)) if not os.path.isdir(path) \
        else os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d, _gitdir(d)
        up = os.path.dirname(d)
        if up == d:
            return None, None
        d = up


def branch_of(gitdir):
    try:
        with open(os.path.join(gitdir, "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
    except OSError:
        return None
    return head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else ""


def ignored(root, path):
    try:
        r = subprocess.run(["git", "-C", root, "check-ignore", "-q", path],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def verdict(path, env=os.environ, now=None):
    """None to allow, or the reason to refuse."""
    root, gitdir = checkout_of(path)
    if not root or not gitdir:
        return None
    if not os.path.isfile(os.path.join(root, "pinball_decryptor", "__init__.py")):
        return None                                   # not this repo
    branch = branch_of(gitdir)
    if branch is None or branch.startswith(LANES):
        return None
    if os.path.exists(os.path.join(gitdir, "MERGE_HEAD")) or \
            os.path.exists(os.path.join(gitdir, "SQUASH_MSG")):
        return None
    for d in {gitdir, _common(gitdir)}:
        mark = os.path.join(d, "PAD_RELEASE")
        if os.path.exists(mark) and \
                (now or time.time()) - os.path.getmtime(mark) < RELEASE_MARK_S:
            return None
    if ignored(root, path):
        return None
    if env.get("PAD_ALLOW_MAIN") == "1":
        sys.stderr.write("PAD_ALLOW_MAIN=1: editing %s on %s without a ticket\n"
                         % (path, branch or "a detached HEAD"))
        return None
    return (
        "This checkout (%s) is on %s. Work on this repo goes through a ticket, "
        "whatever it came from. Open one and edit inside the worktree it "
        "prints:\n\n"
        "  /ticket <one line saying what the work is>\n\n"
        "(or: python <pad-triage>/padtriage_cli.py new \"<what>\"). An ongoing "
        "feature/* or item/* worktree is fine too. Only a ticket's merge and "
        "/release move main." % (root, branch or "a detached HEAD"))


def main():
    try:
        data = json.load(sys.stdin)
        ti = data.get("tool_input") or {}
        path = ti.get("file_path") or ti.get("notebook_path")
        if not path:
            return 0
        if not os.path.isabs(path):
            path = os.path.join(data.get("cwd") or os.getcwd(), path)
        why = verdict(path)
    except Exception:                                  # noqa: BLE001
        return 0                                       # fail open, never wedge
    if why:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": why}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
