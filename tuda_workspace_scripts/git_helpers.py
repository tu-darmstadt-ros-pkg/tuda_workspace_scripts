"""
Git Repository Helper Module.

This module provides reusable functions for git repository management within
a ROS 2 workspace. It consolidates common git operations used by the update
and remove scripts.

Key Features:
    - Mainline branch detection with optional auto-configuration
    - Repository status collection (dirty state, unpushed commits, etc.)
    - Branch tracking and merge evidence detection
    - Safe subprocess execution with timeout handling
    - Repository discovery within workspace boundaries

Example Usage:
    >>> from tuda_workspace_scripts.git_helpers import (
    ...     get_mainline_branch,
    ...     collect_repo_status,
    ...     RepoStatus,
    ... )
    >>> repo = git.Repo("/path/to/repo")
    >>> mainline = get_mainline_branch(repo, auto_set=True)
    >>> status = collect_repo_status(Path("/path/to/repo"), workspace_root)
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import git
    from git import Repo
except ImportError as e:
    raise ImportError(
        "GitPython is required! Install using 'pip install gitpython' "
        "or 'apt install python3-git'"
    ) from e


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class RepoStatus:
    """Structured container for repository status.

    This dataclass holds comprehensive information about a git repository's
    current state, including local changes, remote synchronization status,
    and branch information.

    Attributes:
        rel_path: Repository path relative to workspace root.
        branch: Current branch name or detached HEAD description.
        mainline: Detected mainline branch name (e.g., 'main', 'ros2').
        is_git: Whether the path is a valid git repository.
        has_changes: Whether there are any uncommitted or unpushed changes.
        untracked_count: Number of untracked files.
        stash_count: Number of stash entries.
        changes_summary: List of human-readable change descriptions.
        unpushed_branches: Tuples of (branch_name, commit_count) for branches
            with commits not pushed to remote.
        local_only_branches: Branch names with no upstream configured.
        deleted_upstream_branches: Tuples of (branch_name, merge_hint) for
            branches whose upstream was deleted.
        is_clean: Whether the repository is in a clean state.
    """

    rel_path: str
    branch: str
    mainline: str = "unknown"
    is_git: bool = False

    # Local changes / risks
    has_changes: bool = False
    untracked_count: int = 0
    stash_count: int = 0
    changes_summary: List[str] = field(default_factory=list)

    # Remote synchronization (only meaningful if fetch was performed)
    unpushed_branches: List[Tuple[str, int]] = field(default_factory=list)
    local_only_branches: List[str] = field(default_factory=list)
    deleted_upstream_branches: List[Tuple[str, str]] = field(default_factory=list)

    is_clean: bool = True


# =============================================================================
# SUBPROCESS UTILITIES
# =============================================================================


def launch_subprocess(
    cmd: list[str] | tuple[str, ...],
    cwd: str | Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a command in a subprocess with proper signal handling.

    This function executes a command in a new process group, allowing proper
    cleanup on KeyboardInterrupt. It also disables git credential prompts
    to prevent hanging in non-interactive contexts.

    Args:
        cmd: Command and arguments to execute.
        cwd: Working directory for the command.
        timeout: Maximum seconds to wait for command completion.

    Returns:
        CompletedProcess with returncode, stdout, and stderr.

    Raises:
        KeyboardInterrupt: If the user interrupts execution.

    Example:
        >>> result = launch_subprocess(["git", "fetch", "--all"], "/path/to/repo")
        >>> if result.returncode == 0:
        ...     print("Fetch successful")
    """
    # Prevent git from hanging by asking for credentials
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        with subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=env,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.kill()
                stdout, stderr = process.communicate()
                return subprocess.CompletedProcess(
                    process.args, 1, stdout or "", stderr or "Command timed out"
                )
            except KeyboardInterrupt:
                os.killpg(process.pid, signal.SIGINT)
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


# =============================================================================
# REPOSITORY DISCOVERY
# =============================================================================


def get_repo_root(path: Path, workspace_src: Path) -> Optional[Path]:
    """Find the git repository root for a path within workspace boundaries.

    This function searches for the git working tree root of the given path,
    but only returns it if the root is inside the workspace src directory.
    This prevents accidentally picking up parent repositories (e.g., /home/user).

    Args:
        path: Path to search from.
        workspace_src: Workspace src directory (e.g., /workspace/src).

    Returns:
        The repository root Path if found within workspace, None otherwise.

    Example:
        >>> repo_root = get_repo_root(
        ...     Path("/workspace/src/my_pkg/src/file.py"),
        ...     Path("/workspace/src")
        ... )
        >>> print(repo_root)  # /workspace/src/my_pkg
    """
    workspace_src = workspace_src.resolve()
    current = path.resolve()

    # Must be within workspace src
    if not current.is_relative_to(workspace_src):
        return None

    try:
        repo = Repo(current, search_parent_directories=True)
        repo_root = Path(repo.working_tree_dir).resolve()
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        return None

    if repo_root == workspace_src or repo_root.is_relative_to(workspace_src):
        return repo_root

    return None


def collect_repos(ws_src: Path) -> list[Path]:
    """Discover all top-level git repositories under a workspace src directory.

    Walks the directory tree and identifies git repositories. Does not recurse
    into found repositories (i.e., nested repos are not returned).

    Args:
        ws_src: Workspace source directory to search.

    Returns:
        List of absolute paths to git repository roots.

    Example:
        >>> repos = collect_repos(Path("/workspace/src"))
        >>> for repo in repos:
        ...     print(repo.name)
    """
    repos: list[Path] = []
    for root, dirs, _ in os.walk(ws_src):
        root_p = Path(root)
        git_entry = root_p / ".git"

        # Check for directory (standard repo) OR file (submodule/worktree)
        if git_entry.is_dir() or git_entry.is_file():
            repos.append(root_p)
            dirs[:] = []  # Don't recurse into repo

    return repos


# =============================================================================
# MAINLINE DETECTION
# =============================================================================


def get_remote_head_mainline(
    repo: git.Repo,
    remote_name: str,
    auto_set: bool = False,
) -> str | None:
    """Resolve the remote's configured mainline branch via refs/remotes/<remote>/HEAD.

    This function checks for a symbolic reference at refs/remotes/<remote>/HEAD
    which points to the default branch of the remote repository.

    Args:
        repo: GitPython Repo instance.
        remote_name: Name of the remote (e.g., 'origin').
        auto_set: If True and HEAD is not set, attempt to auto-configure it
            using 'git remote set-head <remote> -a'.

    Returns:
        Remote ref like '<remote>/<branch>' (e.g., 'origin/ros2'), or None
        if not resolvable.

    Example:
        >>> repo = git.Repo("/path/to/repo")
        >>> mainline_ref = get_remote_head_mainline(repo, "origin", auto_set=True)
        >>> print(mainline_ref)  # 'origin/main'
    """
    head_ref = f"refs/remotes/{remote_name}/HEAD"
    prefix = f"refs/remotes/{remote_name}/"

    def try_resolve() -> str | None:
        try:
            sym = repo.git.symbolic_ref("-q", head_ref).strip()
            if sym and sym.startswith(prefix):
                return f"{remote_name}/{sym[len(prefix):]}"
        except git.exc.GitCommandError:
            pass
        return None

    resolved = try_resolve()
    if resolved:
        return resolved

    if auto_set:
        try:
            subprocess.run(
                ["git", "remote", "set-head", remote_name, "-a"],
                cwd=repo.working_tree_dir,
                capture_output=True,
                timeout=10,
            )
            return try_resolve()
        except Exception:
            pass

    return None


def get_mainline_branch(repo: git.Repo, auto_set: bool = False) -> str:
    """Detect the mainline branch name dynamically.

    Attempts to determine the mainline branch using multiple strategies:
    1. Check remote HEAD symbolic ref (most reliable)
    2. Look for ROS_DISTRO environment variable as branch name
    3. Fall back to common names: 'main', 'master'

    Args:
        repo: GitPython Repo instance.
        auto_set: If True and remote HEAD is not set, attempt to
            auto-configure it.

    Returns:
        The mainline branch name (e.g., 'main', 'ros2', 'master').

    Example:
        >>> repo = git.Repo("/path/to/repo")
        >>> mainline = get_mainline_branch(repo, auto_set=True)
        >>> print(f"Mainline is: {mainline}")
    """
    # Strategy 1: Check remote HEAD
    for remote in repo.remotes:
        mainline_ref = get_remote_head_mainline(repo, remote.name, auto_set=auto_set)
        if mainline_ref:
            return mainline_ref.split("/", 1)[1]

    # Strategy 2: Try ROS_DISTRO and common names
    ros_distro = os.environ.get("ROS_DISTRO", "").lower()
    for candidate in [ros_distro, "main", "master"]:
        if candidate and candidate in repo.heads:
            return candidate

    return "main"


# =============================================================================
# WORKTREE CHANGES
# =============================================================================


def collect_worktree_changes(repo: Repo) -> Tuple[List[str], int, int]:
    """Collect working tree changes using git status.

    Parses git status porcelain output to identify modified, added, deleted,
    and renamed files.

    Args:
        repo: GitPython Repo instance.

    Returns:
        Tuple of (changes_summary, modified_count, untracked_count) where:
        - changes_summary: List of human-readable change descriptions
        - modified_count: Number of tracked files with changes
        - untracked_count: Number of untracked files

    Example:
        >>> repo = git.Repo("/path/to/repo")
        >>> changes, modified, untracked = collect_worktree_changes(repo)
        >>> for change in changes:
        ...     print(change)
    """
    try:
        out = repo.git.status("--porcelain=v1").splitlines()
    except git.exc.GitCommandError:
        out = []

    changes_summary: List[str] = []
    modified_count = 0
    untracked_count = 0

    for line in out:
        if not line:
            continue
        if line.startswith("?? "):
            untracked_count += 1
            continue

        xy, rest = line[:2], line[3:]
        modified_count += 1

        if "R" in xy:
            changes_summary.append(f"Renamed: {rest}")
        elif "D" in xy:
            changes_summary.append(f"Deleted: {rest}")
        elif "A" in xy:
            changes_summary.append(f"Added: {rest}")
        else:
            changes_summary.append(f"Modified: {rest}")

    return changes_summary, modified_count, untracked_count


# =============================================================================
# BRANCH STATUS
# =============================================================================


def has_commits_not_on_remote(repo: git.Repo, branch_name: str) -> bool:
    """Check if a branch has commits not on any remote.

    Uses git rev-list to count commits that are reachable from the branch
    but not from any remote tracking branch.

    Args:
        repo: GitPython Repo instance.
        branch_name: Name of the branch to check.

    Returns:
        True if the branch has commits unknown to any remote.

    Example:
        >>> if has_commits_not_on_remote(repo, "feature-branch"):
        ...     print("Branch has unpushed commits")
    """
    try:
        cnt = int(
            repo.git.rev_list("--count", branch_name, "--not", "--remotes").strip()
            or "0"
        )
        return cnt > 0
    except git.exc.GitCommandError:
        return False


def is_ancestor(repo: git.Repo, ancestor: str, descendant: str) -> bool:
    """Check if one commit is an ancestor of another.

    Args:
        repo: GitPython Repo instance.
        ancestor: Ref or SHA of potential ancestor commit.
        descendant: Ref or SHA of potential descendant commit.

    Returns:
        True if ancestor is reachable from descendant.

    Example:
        >>> if is_ancestor(repo, "feature-branch", "origin/main"):
        ...     print("Branch is merged into main")
    """
    try:
        repo.git.merge_base("--is-ancestor", ancestor, descendant)
        return True
    except git.exc.GitCommandError:
        return False


def find_merge_evidence(
    repo: git.Repo,
    branch: git.Head,
    mainline: str,
) -> Tuple[bool, str]:
    """Detect if a branch has been merged into the mainline.

    Checks for merge evidence using two strategies:
    1. Direct ancestry (branch is reachable from mainline)
    2. Squash merge detection (commit message contains branch name)

    Args:
        repo: GitPython Repo instance.
        branch: Branch to check for merge evidence.
        mainline: Mainline branch name to check against.

    Returns:
        Tuple of (is_merged, hint_message) where:
        - is_merged: True if merge evidence was found
        - hint_message: Human-readable description of merge status

    Example:
        >>> merged, hint = find_merge_evidence(repo, repo.heads["feature"], "main")
        >>> if merged:
        ...     print(f"Branch was {hint}")
    """
    try:
        local_mainline = repo.heads[mainline]
        tracking_ref = local_mainline.tracking_branch()
        target = tracking_ref.name if tracking_ref else mainline

        # Strategy 1: Direct Ancestry
        if repo.is_ancestor(branch.commit, target):
            return True, f"merged into {target}"

        # Strategy 2: Squash Merge Search
        since_date = branch.commit.committed_datetime.isoformat()
        found = repo.git.log(
            target,
            f"--grep={branch.name}",
            f"--since={since_date}",
            "--format=%H",
            "-n",
            "1",
        )
        if found:
            return True, f"merged into {target} (squashed)"

        return False, f"merge into {target} unverified"
    except Exception:
        pass

    return False, f"merge into {mainline} unverified"


def get_deleted_branch_status(
    repo: git.Repo,
    branch: git.Head,
) -> Tuple[bool, str | None]:
    """Check if a branch's upstream was deleted and if it's safe to delete locally.

    A branch is considered safely deletable if:
    - Its upstream tracking branch no longer exists on the remote
    - It is not the current branch
    - It has no commits unknown to any remote
    - It is merged into the remote's HEAD mainline

    Args:
        repo: GitPython Repo instance.
        branch: Local branch to check.

    Returns:
        Tuple of (deletable, warning) where:
        - deletable: True if branch can be safely deleted
        - warning: Explanatory message when not deletable, None otherwise

    Example:
        >>> deletable, warning = get_deleted_branch_status(repo, branch)
        >>> if deletable:
        ...     repo.delete_head(branch, force=True)
        >>> elif warning:
        ...     print(warning)
    """
    tracking = branch.tracking_branch()
    if tracking is None:
        return False, None

    try:
        if not tracking.remote_name:
            return False, None

        remote = repo.remotes[tracking.remote_name]
        remote_ref_names = {r.name for r in remote.refs}

        if tracking.name in remote_ref_names:
            return False, None

    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        if not repo.head.is_detached and branch.name == repo.head.ref.name:
            warn = (
                f"Remote '{tracking.remote_name}' for current branch {branch.name} "
                "does not exist anymore. Skipping deletion."
            )
            return False, warn
        return False, None

    # Check if it's the current branch
    if not repo.head.is_detached and branch.name == repo.head.ref.name:
        warn = (
            f"Current branch {branch.name} was deleted on the remote. "
            "Skipping deletion."
        )
        return False, warn

    # Check for unpushed commits
    if has_commits_not_on_remote(repo, branch.name):
        warn = (
            f"Branch {branch.name} was deleted on the remote but still has "
            "commits that are not present on any remote."
        )
        return False, warn

    # Check if merged into remote HEAD mainline
    mainline = get_remote_head_mainline(repo, tracking.remote_name)
    if mainline is None:
        warn = (
            f"Branch {branch.name} was deleted on the remote but remote "
            f"'{tracking.remote_name}' HEAD mainline could not be resolved. "
            "Skipping deletion."
        )
        return False, warn

    if not is_ancestor(repo, branch.name, mainline):
        warn = (
            f"Branch {branch.name} was deleted on the remote but is not merged into "
            f"{mainline}. Skipping deletion."
        )
        return False, warn

    return True, None


# =============================================================================
# REPOSITORY STATUS COLLECTION
# =============================================================================


def collect_repo_status(
    repo_path: Path,
    workspace_root: Path,
    fetch: bool = False,
) -> RepoStatus:
    """Collect comprehensive status information for a repository.

    Gathers all relevant status information including local changes,
    branch status, and optionally fetches from remotes to detect
    synchronization issues.

    Args:
        repo_path: Absolute path to the repository.
        workspace_root: Workspace root for relative path calculation.
        fetch: If True, fetch from all remotes before checking status.

    Returns:
        RepoStatus dataclass with complete repository state.

    Example:
        >>> status = collect_repo_status(Path("/workspace/src/my_pkg"), workspace_root)
        >>> if not status.is_clean:
        ...     print(f"Repository has changes: {status.changes_summary}")
    """
    rel_path = str(repo_path.relative_to(workspace_root))

    try:
        repo = Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return RepoStatus(rel_path=rel_path, branch="unknown", is_git=False)

    mainline = get_mainline_branch(repo)

    # Determine current branch
    try:
        branch_name = (
            f"detached ({repo.head.commit.hexsha[:7]})"
            if repo.head.is_detached
            else repo.active_branch.name
        )
    except Exception:
        branch_name = "unknown"

    # Collect local working tree status
    changes_summary, mod_count, untracked_count = collect_worktree_changes(repo)

    # Count stashes
    stash_count = 0
    try:
        stash_out = repo.git.stash("list")
        stash_count = len(stash_out.splitlines()) if stash_out else 0
    except git.exc.GitCommandError:
        pass

    unpushed: List[Tuple[str, int]] = []
    local_only: List[str] = []
    deleted_upstream: List[Tuple[str, str]] = []

    if fetch:
        # Fetch with prune
        try:
            subprocess.run(
                ["git", "fetch", "--prune", "--all", "--quiet"],
                cwd=str(repo_path),
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass  # Fetch failures are handled gracefully

        # Check branch synchronization
        for branch in repo.branches:
            tracking = branch.tracking_branch()
            if not tracking:
                if branch.name != mainline:
                    local_only.append(branch.name)
                continue

            # Verify tracking ref exists
            try:
                repo.git.show_ref("--verify", tracking.path, with_exceptions=True)
            except Exception:
                _, hint = find_merge_evidence(repo, branch, mainline)
                deleted_upstream.append((branch.name, hint))
                continue

            # Check for unpushed commits
            try:
                count = int(
                    repo.git.rev_list("--count", f"{tracking.name}..{branch.name}")
                )
                if count > 0:
                    unpushed.append((branch.name, count))
            except Exception:
                pass

    has_changes = (
        mod_count > 0
        or untracked_count > 0
        or stash_count > 0
        or bool(unpushed)
        or bool(local_only)
        or bool(deleted_upstream)
    )

    return RepoStatus(
        rel_path=rel_path,
        branch=branch_name,
        mainline=mainline,
        is_git=True,
        has_changes=has_changes,
        untracked_count=untracked_count,
        stash_count=stash_count,
        unpushed_branches=unpushed,
        local_only_branches=local_only,
        deleted_upstream_branches=deleted_upstream,
        changes_summary=changes_summary,
        is_clean=not has_changes,
    )
