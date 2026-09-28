"""Work on this repo goes through a ticket (docs/plans/ticket_intake.md):
the Claude Code edit guard (scripts/hooks/require_ticket.py) and the git
commit-msg hook (.githooks/commit-msg) both refuse main."""
import io
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts", "hooks"))
import require_ticket as rt                                   # noqa: E402

GIT = shutil.which("git")


def checkout(tmp_path, branch="main", ours=True, name="co"):
    """A fake checkout: .git/HEAD on `branch` ('' = detached)."""
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    head = ("ref: refs/heads/%s\n" % branch) if branch else "0123abcd" * 5 + "\n"
    (root / ".git" / "HEAD").write_text(head)
    if ours:
        (root / "pinball_decryptor").mkdir()
        (root / "pinball_decryptor" / "__init__.py").write_text("")
    (root / "src").mkdir()
    return root


def f(root):
    return str(root / "src" / "thing.py")


def test_main_is_refused_and_says_how_to_open_a_ticket(tmp_path):
    why = rt.verdict(f(checkout(tmp_path)), env={})
    assert why and "/ticket" in why and "main" in why


@pytest.mark.parametrize("branch", ["ticket/PAD-241", "feature/rig-slots", "item/86"])
def test_a_ticket_or_a_running_lane_is_allowed(tmp_path, branch):
    assert rt.verdict(f(checkout(tmp_path, branch)), env={}) is None


@pytest.mark.parametrize("branch", ["master", "", "scratch"])
def test_every_other_head_is_refused(tmp_path, branch):
    assert rt.verdict(f(checkout(tmp_path, branch)), env={})


def test_other_repos_and_no_repo_are_none_of_its_business(tmp_path):
    assert rt.verdict(f(checkout(tmp_path, ours=False)), env={}) is None
    loose = tmp_path / "loose"
    loose.mkdir()
    assert rt.verdict(str(loose / "notes.md"), env={}) is None


def test_a_merge_or_squash_landing_on_main_is_allowed(tmp_path):
    root = checkout(tmp_path)
    (root / ".git" / "MERGE_HEAD").write_text("x")
    assert rt.verdict(f(root), env={}) is None
    (root / ".git" / "MERGE_HEAD").unlink()
    (root / ".git" / "SQUASH_MSG").write_text("x")
    assert rt.verdict(f(root), env={}) is None


def test_a_release_marker_opens_main_for_two_hours_only(tmp_path):
    root = checkout(tmp_path)
    mark = root / ".git" / "PAD_RELEASE"
    mark.write_text("")
    assert rt.verdict(f(root), env={}) is None
    old = time.time() - 3 * 3600
    os.utime(mark, (old, old))
    assert rt.verdict(f(root), env={})


def test_a_worktree_follows_its_git_file_to_its_head_and_the_shared_marker(tmp_path):
    common = tmp_path / "main" / ".git"
    wtgit = common / "worktrees" / "x"
    wtgit.mkdir(parents=True)
    (wtgit / "HEAD").write_text("ref: refs/heads/main\n")
    (wtgit / "commondir").write_text("../..\n")
    root = tmp_path / "wt"
    (root / "pinball_decryptor").mkdir(parents=True)
    (root / "pinball_decryptor" / "__init__.py").write_text("")
    (root / ".git").write_text("gitdir: %s\n" % wtgit)
    assert rt.verdict(str(root / "a.py"), env={})
    (common / "PAD_RELEASE").write_text("")        # /release run from the main clone
    assert rt.verdict(str(root / "a.py"), env={}) is None


def test_the_emergency_override_allows_and_says_so(tmp_path, capsys):
    assert rt.verdict(f(checkout(tmp_path)), env={"PAD_ALLOW_MAIN": "1"}) is None
    assert "PAD_ALLOW_MAIN=1" in capsys.readouterr().err


@pytest.mark.skipif(not GIT, reason="no git")
def test_gitignored_scratch_on_main_is_allowed(tmp_path):
    root = tmp_path / "real"
    root.mkdir()
    subprocess.run([GIT, "init", "-q", "-b", "main", str(root)], check=True)
    (root / "pinball_decryptor").mkdir()
    (root / "pinball_decryptor" / "__init__.py").write_text("")
    (root / ".gitignore").write_text("plans/\n")
    assert rt.verdict(str(root / "plans" / "notes.md"), env={}) is None
    assert rt.verdict(str(root / "pinball_decryptor" / "app.py"), env={})


def test_the_hook_speaks_claude_codes_json(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": "src/thing.py"},
         "cwd": str(root)})))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.delenv("PAD_ALLOW_MAIN", raising=False)
    assert rt.main() == 0
    d = json.loads(out.getvalue())["hookSpecificOutput"]
    assert d["permissionDecision"] == "deny" and "/ticket" in d["permissionDecisionReason"]


def test_a_broken_request_fails_open(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert rt.main() == 0 and out.getvalue() == ""


def test_the_project_settings_wire_the_guard_to_every_edit_tool():
    with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as fh:
        s = json.load(fh)
    pre = s["hooks"]["PreToolUse"][0]
    assert set(pre["matcher"].split("|")) == {"Edit", "Write", "NotebookEdit"}
    assert "scripts/hooks/require_ticket.py" in pre["hooks"][0]["command"]


# --------------------------------------------------------------------------
# .githooks/commit-msg, in a real repository
# --------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    if not GIT:
        pytest.skip("no git")
    r = tmp_path / "r"
    r.mkdir()

    def g(*a, env=None, ok=True):
        e = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                 GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        e.pop("PAD_ALLOW_MAIN", None)
        e.update(env or {})
        p = subprocess.run([GIT, "-C", str(r)] + list(a), capture_output=True,
                           text=True, env=e)
        if ok:
            assert p.returncode == 0, p.stderr
        return p

    g("init", "-q", "-b", "main")
    shutil.copytree(os.path.join(REPO, ".githooks"), str(r / ".githooks"))
    g("config", "core.hooksPath", ".githooks")
    (r / "a.txt").write_text("1")
    g("add", "a.txt")
    g("commit", "-q", "-m", "v0.0.1 - first", "--no-verify")
    return r, g


def _commit(r, g, name, msg, env=None):
    (r / name).write_text(str(time.time()))
    g("add", name)
    return g("commit", "-q", "-m", msg, env=env, ok=False)


def test_a_plain_commit_on_main_is_blocked(repo):
    r, g = repo
    p = _commit(r, g, "b.txt", "Fix the thing")
    assert p.returncode != 0 and "BLOCKED" in p.stderr and "/ticket" in p.stderr


def test_a_release_commit_and_the_override_pass(repo):
    r, g = repo
    assert _commit(r, g, "b.txt", "v1.23.0 - Something shipped").returncode == 0
    p = _commit(r, g, "c.txt", "hotfix", env={"PAD_ALLOW_MAIN": "1"})
    assert p.returncode == 0 and "PAD_ALLOW_MAIN=1" in p.stderr


def test_any_other_branch_is_untouched_and_its_merge_lands(repo):
    r, g = repo
    g("checkout", "-q", "-b", "ticket/PAD-7")
    assert _commit(r, g, "b.txt", "Work on the ticket").returncode == 0
    g("checkout", "-q", "main")
    p = g("merge", "--no-ff", "-m", "PAD-7: merge", "ticket/PAD-7", ok=False)
    assert p.returncode == 0, p.stderr


def test_queue_only_bookkeeping_still_passes(repo):
    r, g = repo
    (r / "plans").mkdir()
    (r / "plans" / "TODO.md").write_text("q")
    g("add", "plans/TODO.md")
    assert g("commit", "-q", "-m", "queue: rank", ok=False).returncode == 0
