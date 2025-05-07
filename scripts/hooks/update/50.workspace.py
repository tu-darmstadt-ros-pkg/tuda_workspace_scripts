#!/usr/bin/env python3
"""
This script updates all git repositories under the *src* directory of the workspace.
- it fetches all remotes
- it pulls the current branch (if it has an upstream)
- it detects branches that are deleted on the remote and have no new commits
    - it offers to delete those branches
- it runs in parallel for all repositories 
"""
from __future__ import annotations

import os
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List
import time
import shutil
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.workspace import get_workspace_root

try:
    import git
except ImportError:
    print(
        "GitPython is required! Install using 'pip3 install --user gitpython' or 'apt install python3-git'"
    )
    raise


def launch_subprocess(cmd: list[str] | tuple[str, ...], cwd: str | Path):
    """Run *cmd* in *cwd* forwarding *SIGINT* to the child process group."""
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setpgrp,
        )
    except KeyboardInterrupt:
        # propagate Ctrl‑C to the subprocess group so *git* exits cleanly
        os.killpg(0, signal.SIGINT)
        raise


def _is_deleted_branch(repo: "git.Repo", branch: "git.Head") -> bool:
    """Return *True* if *branch* was deleted upstream and has no unique commits."""
    try:
        tracking_branch = branch.tracking_branch()
        if tracking_branch is None:
            return False  # not tracking → ignore

        for remote in repo.remotes:
            if remote.name == tracking_branch.remote_name:
                if (
                    tracking_branch in remote.refs
                    and tracking_branch not in remote.stale_refs
                ):
                    # upstream still exists & not stale
                    return False
                break
    except (git.exc.GitCommandError, Exception) as exc:
        print_error(
            f"{os.path.basename(repo.working_tree_dir)} has error on branch {branch.name}: {exc}"
        )
        return False

    # Upstream appears gone – do we have local commits not pushed anywhere?
    try:
        if any(True for _ in repo.iter_commits("{0}@{{u}}..{0}".format(branch.name))):
            print_warn(
                f"Branch {branch.name} seems to be deleted on remote but still has commits that were not pushed."
            )
            return False
    except git.exc.GitCommandError:
        pass  # Ignore error if branch is not tracking anything
    return True


class RepoResult:
    __slots__ = (
        "path",
        "branch",
        "fetch_ok",
        "pull_attempted",
        "pull_ok",
        "deletable",
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
        deletable: List[str],
        stdout: str,
        stderr: str,
        error: str | None = None,
    ) -> None:
        self.path = path
        self.branch = branch
        self.fetch_ok = fetch_ok
        self.pull_attempted = pull_attempted
        self.pull_ok = pull_ok
        self.deletable = deletable
        self.stdout = stdout
        self.stderr = stderr
        self.error = error


def process_repo(repo_path: Path) -> RepoResult:
    """Fetch + optional pull + stale‑branch detection (runs in a worker)."""
    try:
        repo = git.Repo(repo_path)

        if not repo.head.is_valid():
            return RepoResult(repo_path, "no-HEAD", True, False, True, [], "", "", None)

        branch_name = (
            f"detached@{repo.head.commit.hexsha[:7]}"
            if repo.head.is_detached
            else repo.head.ref.name
        )

        # -- always fetch/prune first so other branches are updated --------- #
        fetch = launch_subprocess(["git", "fetch", "--all", "--prune"], cwd=repo_path)
        fetch_ok = fetch.returncode == 0

        # ------------------------------------------------------------------ #
        pull_attempted = False
        pull_ok = True  # will stay True when pull is skipped
        pull_out, pull_err = "", ""

        if not repo.head.is_detached:
            upstream = repo.head.ref.tracking_branch()
            if upstream is not None and upstream in repo.refs:
                pull_attempted = True
                pull = launch_subprocess(["git", "pull", "--ff-only"], cwd=repo_path)
                pull_ok = pull.returncode == 0
                pull_out = pull.stdout or ""
                pull_err = pull.stderr or ""

        # deletable branches – only when fetch succeeded so refs are current
        deletable: List[str] = []
        if fetch_ok:
            deletable = [
                br.name for br in repo.branches if _is_deleted_branch(repo, br)
            ]

        stdout_combined = (fetch.stdout or "") + pull_out
        stderr_combined = (fetch.stderr or "") + pull_err

        return RepoResult(
            path=repo_path,
            branch=branch_name,
            fetch_ok=fetch_ok,
            pull_attempted=pull_attempted,
            pull_ok=pull_ok,
            deletable=deletable,
            stdout=stdout_combined,
            stderr=stderr_combined,
        )

    except Exception as exc:  # broad catch for isolation between threads
        return RepoResult(repo_path, "?", False, False, False, [], "", "", str(exc))


def collect_repos(ws_src: Path) -> List[Path]:
    """Return absolute paths of *top‑level* git work‑trees under *ws_src*."""
    repos: List[Path] = []
    for root, dirs, _ in os.walk(ws_src):
        root_p = Path(root)
        if (root_p / ".git").is_dir():
            repos.append(root_p)
            dirs[:] = []  # prune recursion into this repo
    return repos


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

    # ----------------------- parallel phase ------------------------------- #
    total = len(repos)

    _BAR_START = time.monotonic()

    def _progress(idx: int):
        """Draw a simple progress bar that lives on one terminal line."""
        cols = shutil.get_terminal_size((80, 20)).columns
        bar_len = max(10, min(50, cols - 30))  # leave space for counters & percent
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

    results: List[RepoResult] = []
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

    # ----------------------- sequential phase ----------------------------- #
    overall_ok = True
    for res in sorted(results, key=lambda r: r.path):
        rel = res.path.relative_to(ws_src)
        print_subheader(f"{rel} {Colors.LPURPLE}({res.branch})")

        if res.error:
            print_error(res.error)
            overall_ok = False
            continue

        # -- fetch status --------------------------------------------------- #
        if not res.fetch_ok:
            print_error("git fetch failed – repository might be out of date:")
            if res.stderr.strip():
                print(res.stderr.rstrip())
            overall_ok = False
            continue  # pull & deletion checks rely on fresh refs

        # -- pull status ---------------------------------------------------- #
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

        # -- stale branches ------------------------------------------------- #
        if res.deletable:
            msg = (
                "The following local branches are deleted on the remote and have no extra commits:\n"
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
