#!/usr/bin/env python3
"""
Update every git repository under the *src* directory of a ROS 2 workspace.

* fetches & prunes all remotes
* pulls the current branch (if it has an upstream)
* detects local branches whose upstream was deleted **and** have no commits
  unknown to any remote - offers to delete them
* performs the heavy work in parallel, prints results sequentially
"""
from __future__ import annotations

import os
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
from tuda_workspace_scripts.workspace import get_workspace_root, get_repos_in_workspace
from tuda_workspace_scripts.git_utils import (
    launch_subprocess,
    get_remote_head_mainline,
    get_deleted_branch_status,
)

try:
    import git
except ImportError:
    print(
        "GitPython is required! Install with 'pip3 install --user gitpython' or "
        "'apt install python3-git'"
    )
    raise


# RESULT CONTAINER
# Note: RepoResult is distinct from git_utils.RepoStatus:
# - RepoStatus: Describes the current state of a repo (for status/remove commands)
# - RepoResult: Captures the outcome of update operations (fetch/pull results, errors)
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
        "current_branch_deleted_remote",
        "current_branch_remote",
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
        current_branch_deleted_remote: bool = False,
        current_branch_remote: str | None = None,
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
        self.current_branch_deleted_remote = current_branch_deleted_remote
        self.current_branch_remote = current_branch_remote


# WORKER (PARALLEL)
def process_repo(repo_path: Path) -> RepoResult:
    """Fetch, optional pull, stale-branch detection - runs in a thread."""
    try:
        # 1. Subprocess Fetch (Side effect: updates refs on disk)
        fetch = launch_subprocess(
            ["git", "fetch", "--all", "--prune"], cwd=repo_path, timeout=120
        )
        fetch_ok = fetch.returncode == 0

        # 2. Instantiate GitPython Repo object NOW, after fetch,
        # so it sees the pruned refs correctly.
        repo = git.Repo(repo_path)

        if not repo.head.is_valid():
            return RepoResult(
                repo_path,
                "no-HEAD",
                fetch_ok,
                False,
                True,
                [],
                [],
                fetch.stdout or "",
                fetch.stderr or "",
                None,
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

            if upstream is not None:
                # Verify that the upstream reference actually exists / is resolvable
                # (it might have been pruned)
                try:
                    repo.git.rev_parse(upstream.name)
                    upstream_exists = True
                except git.exc.GitCommandError:
                    upstream_exists = False

                if upstream_exists:
                    pull_attempted = True
                    pull = launch_subprocess(
                        ["git", "pull", "--ff-only"], cwd=repo_path
                    )
                    pull_ok = pull.returncode == 0
                    pull_out = pull.stdout or ""
                    pull_err = pull.stderr or ""

        # 4. Stale-branch detection
        deletable: list[str] = []
        warnings: list[str] = []
        current_branch_deleted_remote = False
        current_branch_remote: str | None = None

        if fetch_ok:
            # Detect "current branch deleted on remote" specifically, so we can offer an interaction later.
            if not repo.head.is_detached:
                head_branch = repo.head.ref
                tracking = head_branch.tracking_branch()
                if tracking is not None:
                    remote_name = getattr(tracking, "remote_name", None)
                    if remote_name:
                        current_branch_remote = remote_name
                        try:
                            remote = repo.remotes[remote_name]
                            remote_ref_names = {r.name for r in remote.refs}
                            if tracking.name not in remote_ref_names:
                                current_branch_deleted_remote = True
                        except (
                            KeyError,
                            IndexError,
                            ValueError,
                            AttributeError,
                            TypeError,
                        ):
                            # Ignore remote config errors for this optional check
                            pass

            for br in repo.branches:
                can_del, warn = get_deleted_branch_status(repo, br)
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
            current_branch_deleted_remote=current_branch_deleted_remote,
            current_branch_remote=current_branch_remote,
        )

    except Exception as exc:
        # Catch-all to prevent one failing repo from crashing the thread pool
        return RepoResult(repo_path, "?", False, False, False, [], [], "", "", str(exc))


# MAIN
def update(**_) -> bool:
    ws_root = get_workspace_root()
    if ws_root is None:
        print_workspace_error()
        return False

    ws_src = Path(ws_root) / "src"
    print_header(f"Updating every git repo under {ws_src}")

    repos = [Path(p) for p in get_repos_in_workspace(ws_root)]
    if not repos:
        print_info("No git repositories found.")
        return True

    # PARALLEL PHASE
    total = len(repos)
    _BAR_START = time.monotonic()

    # Calculate columns once to avoid system calls in loop
    cols = shutil.get_terminal_size((80, 20)).columns

    def _progress(idx: int):
        safe_total = max(total, 1)
        bar_len = max(10, min(50, cols - 30))
        filled = int(bar_len * idx / safe_total)
        bar = (
            ("=" * filled + ">" + " " * (bar_len - filled - 1))
            if idx < total
            else "=" * bar_len
        )
        percent = (idx * 100) // safe_total
        elapsed = time.monotonic() - _BAR_START
        print(
            f"\r[{bar}] {percent:3d}% {idx}/{total} | {elapsed:4.0f}s",
            end="",
            flush=True,
        )

    results: list[RepoResult] = []
    done = 0
    _progress(done)

    # For I/O-bound git operations, allow more threads than CPU cores,
    # but keep a sensible cap.
    cpu_count = os.cpu_count() or 1
    max_workers = min(32, cpu_count * 4)

    fut_map = {}
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_map = {pool.submit(process_repo, p): p for p in repos}
            for fut in as_completed(fut_map):
                results.append(fut.result())
                done += 1
                _progress(done)
    except KeyboardInterrupt:
        print_error("Update interrupted by user. Cancelling outstanding tasks…")
        # Cancel any futures that have not yet started running
        for fut in fut_map:
            fut.cancel()
        return False
    finally:
        print()  # newline after progress bar

    # SEQUENTIAL PHASE
    # NOTE: We intentionally collect all RepoResult objects and print them in
    # a deterministic, path-sorted order instead of streaming output directly
    # from the worker threads. The progress bar above provides live feedback
    # while the parallel work is running, and printing sequentially here keeps
    # the CLI output stable and easier to scan across runs.
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
            print_error("git fetch failed - repository might be out of date:")
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
        elif res.branch.startswith("detached"):
            print_info("skipped pull - detached HEAD")
        else:
            print_info("skipped pull - current branch has no upstream")

        # branch-specific warnings
        for msg in res.warnings:
            print_warn(msg)

        # If current branch is stale on remote, offer checkout of remote mainline + pull + deletion
        if res.current_branch_deleted_remote and res.current_branch_remote:
            try:
                repo = git.Repo(res.path)
                if repo.head.is_detached:
                    continue

                current_branch = repo.head.ref.name
                mainline = get_remote_head_mainline(repo, res.current_branch_remote)

                if current_branch and mainline:
                    mainline_local = mainline.split("/", 1)[1]
                    msg = (
                        f"Current branch {current_branch} was deleted on the remote.\n"
                        f"Do you want to checkout the remote mainline branch '{mainline_local}' now?"
                    )
                    if confirm(msg):
                        co = launch_subprocess(
                            ["git", "checkout", mainline_local], cwd=res.path
                        )
                        if co.returncode != 0:
                            print_error(f"Failed to checkout {mainline_local}:")
                            if co.stderr.strip():
                                print(co.stderr.rstrip())
                            overall_ok = False
                        else:
                            # After checkout: pull (ff-only) if upstream exists
                            pull2 = launch_subprocess(
                                ["git", "pull", "--ff-only"], cwd=res.path
                            )
                            if pull2.returncode != 0:
                                print_error(f"git pull failed on {mainline_local}:")
                                if pull2.stderr.strip():
                                    print(pull2.stderr.rstrip())
                                overall_ok = False
                            else:
                                if pull2.stdout.strip():
                                    print_info(pull2.stdout.rstrip())

                            # Now that we're off the stale branch, offer deletion if safe
                            if current_branch in repo.branches:
                                can_del, warn = get_deleted_branch_status(
                                    repo, repo.branches[current_branch]
                                )
                                if warn:
                                    print_warn(warn)
                                if can_del and confirm(
                                    f"Branch {current_branch} is stale and merged into {mainline}. Delete it now?"
                                ):
                                    try:
                                        repo.delete_head(current_branch, force=True)
                                        print_info(f"  deleted {current_branch}")
                                    except Exception as exc:
                                        print_error(
                                            f"  failed to delete {current_branch}: {exc}"
                                        )
                                        overall_ok = False
                elif current_branch and not mainline:
                    print_warn(
                        f"Current branch {current_branch} was deleted on the remote, but the remote "
                        f"'{res.current_branch_remote}' HEAD mainline could not be resolved. "
                        "Not offering automatic checkout/pull/deletion."
                    )
            except Exception as exc:
                print_error(
                    f"Failed to offer checkout/pull/deletion interaction: {exc}"
                )
                overall_ok = False

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
