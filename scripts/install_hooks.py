"""Point this clone's git at the versioned hooks in .githooks.

    python scripts/install_hooks.py            # this clone (and all its worktrees)
    python scripts/install_hooks.py --check    # say whether it is installed

core.hooksPath is per CLONE, shared by every worktree of it, so this is run
once per clone - David's own, and pad-triage's automation clone. It is only
meaningful once .githooks exists on the branch main checks out, which is why
it is run at the merge of the branch that added it, not before: pointing a
clone at a directory main does not have yet would leave main with no hook at
all. The old untracked .git/hooks/commit-msg is superseded (git ignores
.git/hooks once core.hooksPath is set); it is left where it is.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True,
                          text=True)


def main(argv):
    cur = git("config", "--get", "core.hooksPath").stdout.strip()
    if "--check" in argv:
        print("core.hooksPath = %s" % (cur or "(unset)"))
        return 0 if cur == ".githooks" else 1
    if not os.path.isfile(os.path.join(ROOT, ".githooks", "commit-msg")):
        print("no .githooks/commit-msg in %s - run this from a checkout that "
              "has it (main, once merged)" % ROOT)
        return 1
    r = git("config", "core.hooksPath", ".githooks")
    if r.returncode:
        print(r.stderr.strip())
        return 1
    print("core.hooksPath = .githooks (was %s)" % (cur or "unset"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
