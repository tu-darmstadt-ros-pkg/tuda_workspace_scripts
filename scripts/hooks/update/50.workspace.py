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
    """
    Run *cmd* in *cwd*, forwarding Ctrl-C to the child process group.
    Sets GIT_TERMINAL_PROMPT=0 to prevent hanging on missing credentials.
    """
    # Prevent git from hanging by asking for credentials in a background thread
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    # Use Popen to allow proper cleanup on KeyboardInterrupt
    try:
        with subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # Sets the child as a new process group leader
            env=env,
        ) as process:
            try:
                stdout, stderr = process.communicate()
            except KeyboardInterrupt:
                # Forward the interrupt to the entire child process group.
                # Since start_new_session=True, the PGID is the same as the PID.
                os.killpg(process.pid, signal.SIGINT)

                # Wait briefly for it to exit, otherwise let the context manager kill it
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise

            return subprocess.CompletedProcess(
                process.args, process.returncode, stdout, stderr
            )
    except KeyboardInterrupt:
        raise


def _has_commits_not_on_any_remote(repo: git.Repo, branch_name: str) -> bool:
    """True iff *branch_name* contains commits unknown to **any** remote."""
    try:
        cnt = int(
            repo.git.rev_list("--count", branch_name, "--not", "--remotes").strip()
            or "0"
        )
        return cnt > 0
    except git.exc.GitCommandError:
        return False


def _remote_head_mainline_ref(repo: git.Repo, remote_name: str) -> str | None:
    """
    Resolve the remote's configured mainline via refs/remotes/<remote>/HEAD.
    Returns a ref like '<remote>/<branch>' (e.g. 'origin/ros2') or None.
    """
    head_ref = f"refs/remotes/{remote_name}/HEAD"
    try:
        sym = repo.git.symbolic_ref("-q", head_ref).strip()
        if not sym:
            return None
        prefix = f"refs/remotes/{remote_name}/"
        if sym.startswith(prefix):
            return f"{remote_name}/{sym[len(prefix):]}"
        return None
    except git.exc.GitCommandError:
        return None


def _is_ancestor(repo: git.Repo, ancestor: str, descendant: str) -> bool:
    """True iff ancestor is reachable from descendant."""
    try:
        repo.git.merge_base("--is-ancestor", ancestor, descendant)
        return True
    except git.exc.GitCommandError:
        # If refs are missing or invalid, fail safe (return False)
        return False


def _is_deleted_branch(repo: git.Repo, branch: git.Head) -> tuple[bool, str | None]:
    """
    Returns (deletable, warning)

    * deletable → upstream vanished **and** branch is safe to delete:
      - not the current branch
      - no commits unknown to any remote
      - merged into remote's HEAD mainline (if resolvable)
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

        # Check if the tracking ref actually exists in the remote's refs (name-based)
        remote_ref_names = {r.name for r in remote.refs}
        if tracking.name in remote_ref_names:
            return False, None

    except (
        KeyError,
        IndexError,
        ValueError,
        AttributeError,
        TypeError,
    ):
        # Best-effort detection: if remote config is lost or invalid, assume not deletable.
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

    if _has_commits_not_on_any_remote(repo, branch.name):
        warn = (
            f"Branch {branch.name} was deleted on the remote but still has "
            "commits that are not present on any remote."
        )
        return False, warn

    # only delete if merged into remote HEAD mainline
    mainline = _remote_head_mainline_ref(repo, tracking.remote_name)
    if mainline is None:
        warn = (
            f"Branch {branch.name} was deleted on the remote but remote "
            f"'{tracking.remote_name}' HEAD mainline could not be resolved. "
            "Skipping deletion."
        )
        return False, warn

    if not _is_ancestor(repo, branch.name, mainline):
        warn = (
            f"Branch {branch.name} was deleted on the remote but is not merged into "
            f"{mainline}. Skipping deletion."
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
        fetch = launch_subprocess(["git", "fetch", "--all", "--prune"], cwd=repo_path)
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
            current_branch_deleted_remote=current_branch_deleted_remote,
            current_branch_remote=current_branch_remote,
        )

    except Exception as exc:
        # Catch-all to prevent one failing repo from crashing the thread pool
        return RepoResult(repo_path, "?", False, False, False, [], [], "", "", str(exc))


# DISCOVERY
def collect_repos(ws_src: Path) -> list[Path]:
    """Return absolute paths of *top-level* git repos under ws_src."""
    repos: list[Path] = []
    for root, dirs, _ in os.walk(ws_src):
        root_p = Path(root)
        git_entry = root_p / ".git"

        # Check for directory (standard repo) OR file (submodule/worktree)
        if git_entry.is_dir() or git_entry.is_file():
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
                mainline = _remote_head_mainline_ref(repo, res.current_branch_remote)

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
                                can_del, warn = _is_deleted_branch(
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
