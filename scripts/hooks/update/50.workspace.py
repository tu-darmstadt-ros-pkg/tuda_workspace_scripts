#!/usr/bin/env python3
"""
Update every git repository under the *src* directory of a ROS 2 workspace.

* fetches & prunes all remotes
* pulls the current branch (if it has an upstream)
* detects local branches whose upstream was deleted **and** have no commits
  unknown to any remote – offers to delete them
* performs the heavy work in parallel, prints results sequentially
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tuda_workspace_scripts.print import (
    print_header,
    print_subheader,
    print_error,
    print_info,
    print_warn,
    confirm,
    Colors,
    print_workspace_error,
)
from tuda_workspace_scripts.workspace import get_workspace_root

try:
    import git
except ImportError:
    print(
        "GitPython is required! Install with 'pip3 install --user gitpython' or "
        "'apt install python3-git'"
    )
    raise


# HELPERS
def launch_subprocess(cmd: list[str] | tuple[str, ...], cwd: str | Path):
    """Run *cmd* in *cwd*, forwarding Ctrl-C to the child process group."""
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except KeyboardInterrupt:
        raise


def _has_unpushed_commits(repo: git.Repo, branch_name: str) -> bool:
    """True iff *branch_name* contains commits unknown to **any** remote."""
    try:
        cnt = int(
            repo.git.rev_list("--count", branch_name, "--not", "--remotes").strip()
            or "0"
        )
        return cnt > 0
    except git.exc.GitCommandError:
        return False


def _is_deleted_branch(repo: git.Repo, branch: git.Head) -> tuple[bool, str | None]:
    """
    Returns (deletable, warning)

    * deletable → upstream vanished **and** branch is fully merged everywhere.
    * warning   → explanatory message when *not* deletable (None if none).
    """
    tracking = branch.tracking_branch()
    if tracking is None:
        return False, None

    try:
        # tracking.remote_name might fail if config is corrupt, handle safely
        if not tracking.remote_name:
            return False, None

        remote = repo.remotes[tracking.remote_name]

        # Check if the tracking ref actually exists in the remote's refs
        if tracking in remote.refs:
            return False, None

    except (IndexError, ValueError):  # remote itself lost
        if not repo.head.is_detached and branch.name == repo.head.ref.name:
            warn = (
                f"Remote '{tracking.remote_name}' for current branch {branch.name} "
                "does not exist anymore. Skipping deletion."
            )
            return False, warn
        return False, None

    if not repo.head.is_detached and branch.name == repo.head.ref.name:
        warn = (
            f"Current branch {branch.name} was deleted on the remote. "
            "Skipping deletion."
        )
        return False, warn

    if _has_unpushed_commits(repo, branch.name):
        warn = (
            f"Branch {branch.name} was deleted on the remote but still has "
            "commits that are not present on any remote."
        )
        return False, warn

    return True, None


# RESULT CONTAINER
class RepoResult:
    __slots__ = (
        "path",
        "branch",
        "fetch_ok",
        "pull_attempted",
        "pull_ok",
        "deletable",
        "warnings",
        "stdout",
        "stderr",
        "error",
    )

    def __init__(
        self,
        path: Path,
        branch: str,
        fetch_ok: bool,
        pull_attempted: bool,
        pull_ok: bool,
        deletable: list[str],
        warnings: list[str],
        stdout: str,
        stderr: str,
        error: str | None = None,
    ):
        self.path = path
        self.branch = branch
        self.fetch_ok = fetch_ok
        self.pull_attempted = pull_attempted
        self.pull_ok = pull_ok
        self.deletable = deletable
        self.warnings = warnings
        self.stdout = stdout
        self.stderr = stderr
        self.error = error


# WORKER (PARALLEL)
def process_repo(repo_path: Path) -> RepoResult:
    """Fetch, optional pull, stale-branch detection – runs in a thread."""
    try:
        # 1. Subprocess Fetch (Side effect: updates refs on disk)
        fetch = launch_subprocess(["git", "fetch", "--all", "--prune"], cwd=repo_path)
        fetch_ok = fetch.returncode == 0

        # 2. Instantiate GitPython Repo object NOW, after fetch,
        # so it sees the pruned refs correctly.
        repo = git.Repo(repo_path)

        if not repo.head.is_valid():
            return RepoResult(
                repo_path, "no-HEAD", True, False, True, [], [], "", "", None
            )

        branch_name = (
            f"detached@{repo.head.commit.hexsha[:7]}"
            if repo.head.is_detached
            else repo.head.ref.name
        )

        # 3. Pull current branch (fast-forward only)
        pull_attempted = False
        pull_ok = True
        pull_out = pull_err = ""

        if not repo.head.is_detached:
            upstream = repo.head.ref.tracking_branch()
            if upstream is not None and upstream in repo.refs:
                pull_attempted = True
                pull = launch_subprocess(["git", "pull", "--ff-only"], cwd=repo_path)
                pull_ok = pull.returncode == 0
                pull_out = pull.stdout or ""
                pull_err = pull.stderr or ""

        # 4. Stale-branch detection
        deletable: list[str] = []
        warnings: list[str] = []
        if fetch_ok:
            for br in repo.branches:
                can_del, warn = _is_deleted_branch(repo, br)
                if can_del:
                    deletable.append(br.name)
                if warn:
                    warnings.append(warn)

        return RepoResult(
            path=repo_path,
            branch=branch_name,
            fetch_ok=fetch_ok,
            pull_attempted=pull_attempted,
            pull_ok=pull_ok,
            deletable=deletable,
            warnings=warnings,
            stdout=(fetch.stdout or "") + pull_out,
            stderr=(fetch.stderr or "") + pull_err,
        )

    except Exception as exc:  # keep other repos going
        return RepoResult(repo_path, "?", False, False, False, [], [], "", "", str(exc))


# DISCOVERY
def collect_repos(ws_src: Path) -> list[Path]:
    """Return absolute paths of *top-level* git repos under ws_src."""
    repos: list[Path] = []
    for root, dirs, _ in os.walk(ws_src):
        root_p = Path(root)
        if (root_p / ".git").is_dir():
            repos.append(root_p)
            dirs[:] = []  # don’t recurse into repo
    return repos


# MAIN
def update(**_) -> bool:
    ws_root = get_workspace_root()
    if ws_root is None:
        print_workspace_error()
        return False

    ws_src = Path(ws_root) / "src"
    print_header(f"Updating every git repo under {ws_src}")

    repos = collect_repos(ws_src)
    if not repos:
        print_info("No git repositories found.")
        return True

    # PARALLEL PHASE
    total = len(repos)
    _BAR_START = time.monotonic()

    # Calculate columns once to avoid system calls in loop
    cols = shutil.get_terminal_size((80, 20)).columns

    def _progress(idx: int):
        bar_len = max(10, min(50, cols - 30))
        filled = int(bar_len * idx / total)
        bar = (
            ("=" * filled + ">" + " " * (bar_len - filled - 1))
            if idx < total
            else "=" * bar_len
        )
        percent = (idx * 100) // total
        elapsed = time.monotonic() - _BAR_START
        print(
            f"\r[{bar}] {percent:3d}% {idx}/{total} | {elapsed:4.0f}s",
            end="",
            flush=True,
        )

    results: list[RepoResult] = []
    done = 0
    _progress(done)

    max_workers = min(32, (os.cpu_count() or 1) * 2)
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_map = {pool.submit(process_repo, p): p for p in repos}
            for fut in as_completed(fut_map):
                results.append(fut.result())
                done += 1
                _progress(done)
    except KeyboardInterrupt:
        print_error("Update interrupted by user. Cancelling outstanding tasks…")
        return False
    finally:
        print()  # newline after progress bar

    # SEQUENTIAL PHASE
    overall_ok = True
    for res in sorted(results, key=lambda r: r.path):
        rel = res.path.relative_to(ws_src)
        print_subheader(f"{rel} {Colors.LPURPLE}({res.branch})")

        if res.error:
            print_error(res.error)
            overall_ok = False
            continue

        # fetch status
        if not res.fetch_ok:
            print_error("git fetch failed – repository might be out of date:")
            if res.stderr.strip():
                print(res.stderr.rstrip())
            overall_ok = False
            continue

        # pull status
        if res.pull_attempted:
            if not res.pull_ok:
                print_error("git pull failed:")
                if res.stderr.strip():
                    print(res.stderr.rstrip())
                overall_ok = False
            else:
                if res.stdout.strip():
                    print_info(res.stdout.rstrip())
        else:
            print_info("skipped pull – current branch has no upstream")

        # branch-specific warnings
        for msg in res.warnings:
            print_warn(msg)

        # candidate branches for deletion
        if res.deletable:
            msg = (
                "The following local branches are deleted on the remote and "
                "have no extra commits:\n"
                + "\n".join(f"  {b}" for b in res.deletable)
                + "\nDelete them now?"
            )
            if confirm(msg):
                repo = git.Repo(res.path)
                for b in res.deletable:
                    try:
                        repo.delete_head(b, force=True)
                        print_info(f"  deleted {b}")
                    except Exception as exc:
                        print_error(f"  failed to delete {b}: {exc}")
                        overall_ok = False

    return overall_ok


if __name__ == "__main__":
    update()
