"""
Git Repository Helper Module.

This module provides reusable functions for git repository management within
a ROS 2 workspace. It consolidates common git operations used by e.g. the status,
update and remove scripts.

Key Features:
    - Mainline branch detection with optional auto-configuration
    - Repository status printing (dirty state, unpushed commits, etc.)
    - Branch tracking and merge evidence detection
    - Safe subprocess execution with timeout handling
    - Repository discovery within workspace boundaries

Example Usage:
    >>> from tuda_workspace_scripts.git_utils import (
    ...     get_mainline_branch,
    ...     get_repo_status,
    ...     print_repo_status,
    ... )
    >>> repo = git.Repo("/path/to/repo")
    >>> mainline = get_mainline_branch(repo, auto_set=True)
    >>> status = get_repo_status(Path("/path/to/repo"), workspace_root)
    >>> print_repo_status(status)
"""

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
        "GitPython is required! Install using 'pip3 install --user gitpython' or 'apt install python3-git'"
    ) from e

from tuda_workspace_scripts.print import (
    print_error,
    print_info,
    print_color,
    Colors,
)


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
        untracked_files: List of untracked file paths.
        stash_count: Number of stash entries.
        has_branches: Whether the repository has any local branches.
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
    untracked_files: List[str] = field(default_factory=list)
    stash_count: int = 0
    changes_summary: List[str] = field(default_factory=list)
    has_branches: bool = True

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
            pass  # HEAD ref not configured; fall through to return None
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
            pass  # Auto-set failed (network, permissions, etc.); fall through

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

    Checks for merge evidence using multiple strategies:
    - Direct ancestry: branch is reachable from mainline
    - Squash merge detection: commit message contains branch name
    - Squash merge detection: commit messages contain all branch commit titles

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

        # Strategy 2: Squash Merge Search (by branch name)
        # Find commits on target that mention branch name
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

        # Strategy 3: Squash Merge Search (by commit contents)
        # GitHub adds all commit titles to the squash commit message
        # Find all commits on branch not in target
        unique_commits = list(repo.iter_commits(f"{target}..{branch.name}"))
        if unique_commits:
            # Extract titles, filtering out empty/whitespace-only ones
            titles = [
                c.summary.strip()
                for c in unique_commits
                if c.summary and c.summary.strip()
            ]

            if titles:
                # Search commits in target since branch creation/update
                for commit in repo.iter_commits(target, since=since_date):
                    if isinstance(commit.message, bytes):
                        msg = commit.message.decode("utf-8", "replace")
                    else:
                        msg = commit.message

                    # Check if ALL titles are present in this commit's message
                    if all(title in msg for title in titles):
                        return True, f"merged into {target} (squashed)"

        return False, f"merge into {target} unverified"
    except Exception:
        pass  # Branch or mainline ref invalid; report as unverified

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
# REPOSITORY STATUS PRINTING
# =============================================================================


def get_repo_status(
    repo_path: Path,
    root_path: Path,
) -> RepoStatus:
    """Collect status information for a single git repository.

    Pure data collection without any console output. Use print_repo_status()
    if you also need formatted printing.

    Args:
        repo_path: Absolute path to the repository.
        root_path: Root path for computing relative display path.

    Returns:
        RepoStatus with all fields populated. If the path is not a valid
        git repository, returns a RepoStatus with is_git=False.
    """
    rel_path = str(repo_path.relative_to(root_path) if root_path else repo_path)

    try:
        repo = git.Repo(repo_path, search_parent_directories=False)
    except git.exc.InvalidGitRepositoryError:
        return RepoStatus(rel_path=rel_path, branch="unknown", is_git=False)

    # Determine current branch name
    if not repo.head.is_valid():
        branch_name = "unknown"
    elif repo.head.is_detached:
        branch_name = f"detached@{repo.head.commit.hexsha[:7]}"
    else:
        branch_name = repo.head.ref.name

    # Collect stash info
    try:
        stash = repo.git.stash("list")
        stash_count = len(stash.splitlines()) if stash else 0
    except git.exc.GitCommandError as e:
        if "not a git repository" in e.stderr:
            return RepoStatus(rel_path=rel_path, branch=branch_name, is_git=False)
        return RepoStatus(rel_path=rel_path, branch=branch_name, is_git=False)
    except Exception:
        stash_count = 0

    # Collect changes using repo.index.diff
    try:
        changes = repo.index.diff(None)
    except git.exc.GitCommandError:
        return RepoStatus(rel_path=rel_path, branch=branch_name, is_git=False)

    try:
        # Need to reverse using R=True, otherwise we get the diff from tree to HEAD
        # meaning deleted files are added and vice versa
        changes += repo.index.diff("HEAD", R=True)
    except git.BadName:
        pass  # Repo has no HEAD (probably just initialized)

    # Detect mainline branch
    mainline = get_mainline_branch(repo)

    # Check branches for unpushed commits, local-only, and deleted upstream
    unpushed_branches: List[Tuple[str, int]] = []
    local_only_branches: List[str] = []
    deleted_branches: List[Tuple[str, str]] = []

    for branch in repo.branches:
        tracking = branch.tracking_branch()
        if tracking is None:
            local_only_branches.append(branch.name)
            continue
        if not tracking.is_valid():
            # Check for merge evidence
            _, hint = find_merge_evidence(repo, branch, mainline)
            deleted_branches.append((branch.name, hint))
            continue
        try:
            # Count unpushed commits using iter_commits logic
            if any(
                True for _ in repo.iter_commits(f"{branch.name}@{{u}}..{branch.name}")
            ):
                # To get the count we can use len or rev_list count
                count = int(
                    repo.git.rev_list("--count", f"{tracking.name}..{branch.name}")
                )
                unpushed_branches.append((branch.name, count))
        except Exception as e:
            error_msg = getattr(e, "message", str(e))
            print_error(f"{repo_path} has error on branch {branch.name}: {error_msg}")

    # Determine if there's anything to report
    untracked = list(repo.untracked_files)
    untracked_count = len(untracked)
    has_branches = len(repo.branches) > 0

    has_issues = (
        untracked_count > 0
        or stash_count > 0
        or bool(unpushed_branches)
        or bool(local_only_branches)
        or bool(deleted_branches)
        or bool(changes)
    )

    # Build changes_summary
    changes_summary_str: List[str] = []
    for item in changes:
        if item.change_type.startswith("M"):
            changes_summary_str.append(f"Modified: {item.a_path}")
        elif item.change_type.startswith("D"):
            changes_summary_str.append(f"Deleted: {item.a_path}")
        elif item.change_type.startswith("R"):
            changes_summary_str.append(f"Renamed: {item.a_path} -> {item.b_path}")
        elif item.change_type.startswith("A"):
            changes_summary_str.append(f"Added: {item.a_path}")
        elif item.change_type.startswith("U"):
            changes_summary_str.append(f"Unmerged: {item.a_path}")
        elif item.change_type.startswith("C"):
            changes_summary_str.append(f"Copied: {item.a_path} -> {item.b_path}")
        elif item.change_type.startswith("T"):
            changes_summary_str.append(f"Type changed: {item.a_path}")
        else:
            changes_summary_str.append(
                f"Unhandled change type '{item.change_type}': {item.a_path}"
            )

    return RepoStatus(
        rel_path=rel_path,
        branch=branch_name,
        mainline=mainline,
        is_git=True,
        has_changes=has_issues,
        untracked_count=untracked_count,
        untracked_files=untracked,
        stash_count=stash_count,
        changes_summary=changes_summary_str,
        has_branches=has_branches,
        unpushed_branches=unpushed_branches,
        local_only_branches=local_only_branches,
        deleted_upstream_branches=deleted_branches,
        is_clean=not has_issues,
    )


def print_repo_status(
    status: RepoStatus,
    always_print_header: bool = False,
) -> None:
    """Print formatted status information for a repository.

    Pure display function that takes a RepoStatus from get_repo_status()
    and prints it with color formatting.

    Args:
        status: RepoStatus object from get_repo_status().
        always_print_header: If True, print repo header even when clean.
    """
    if not status.is_git:
        print_error(f"Failed to obtain git info for: {status.rel_path}")
        return

    if status.is_clean and not always_print_header:
        return

    # Print header with branch info
    print_info(
        f"{status.rel_path} {Colors.LPURPLE}({status.branch} | mainline: {status.mainline})"
    )

    if status.is_clean:
        print_color(Colors.GREEN, "  Clean")
        print("")
        return

    # Print warnings
    if not status.has_branches:
        print_color(Colors.LRED, "  Repository has no local branches.")

    for branch, count in status.unpushed_branches:
        commits_str = "commit" if count == 1 else "commits"
        print_color(
            Colors.RED,
            f"  Unpushed commits on branch {branch}! ({count} {commits_str})",
        )

    for branch in status.local_only_branches:
        print_color(Colors.LRED, f"  Local branch with no remote set up: {branch}")

    for branch, hint in status.deleted_upstream_branches:
        color = Colors.GREEN if "merged" in hint else Colors.LRED
        print_color(
            color, f"  Local branch for which remote was deleted: {branch} ({hint})"
        )

    if status.stash_count > 0:
        if status.stash_count == 1:
            print_color(Colors.LCYAN, "  Stashed changes")
        else:
            print_color(
                Colors.LCYAN, f"  Stashed changes ({status.stash_count} entries)"
            )

    # Print file changes with specific colors
    for summary in status.changes_summary:
        if summary.startswith("Modified:"):
            print_color(Colors.ORANGE, f"  {summary}")
        elif summary.startswith("Deleted:"):
            print_color(Colors.RED, f"  {summary}")
        elif (
            summary.startswith("Renamed:")
            or summary.startswith("Added:")
            or summary.startswith("Copied:")
        ):
            print_color(Colors.GREEN, f"  {summary}")
        elif summary.startswith("Unmerged:"):
            print_error(f"  {summary}")
        elif summary.startswith("Type changed:"):
            print_color(Colors.ORANGE, f"  {summary}")
        else:
            print_color(Colors.RED, f"  {summary}")

    # Print untracked files
    if status.untracked_count > 0:
        if status.untracked_count < 10:
            for file in status.untracked_files:
                print_color(Colors.LGRAY, f"  Untracked: {file}")
        else:
            print_color(Colors.LGRAY, f"  {status.untracked_count} untracked files.")

    print("")
