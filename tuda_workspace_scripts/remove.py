import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Set

from .build import clean_packages
from .print import Colors, confirm, print_error, print_info, print_warn, print_color
from .workspace import find_packages_in_directory, get_package_path

try:
    import git
    from git import Repo
except ImportError:
    print_error("GitPython is required! Install using 'pip install gitpython'")
    raise


@dataclass
class RepoStatus:
    """Structured container for repository status."""

    rel_path: str
    branch: str
    is_git: bool = False
    has_changes: bool = False
    untracked_count: int = 0
    stash_count: int = 0

    # Detailed lists for display
    unpushed_branches: List[str] = field(default_factory=list)
    local_only_branches: List[str] = field(default_factory=list)
    deleted_upstream_branches: List[str] = field(default_factory=list)
    changes_summary: List[str] = field(default_factory=list)

    # For safety checks
    is_clean: bool = True


def _get_repo_root(path: Path, workspace_src: Path) -> Optional[Path]:
    """
    Find the git root for a path, but stop searching if we hit the workspace src root.
    This prevents detecting a git repo in the user's home directory by mistake.
    """
    current = path.resolve()
    workspace_src = workspace_src.resolve()

    # Safety check: ensure we are actually inside the workspace src
    if not current.is_relative_to(workspace_src):
        return None

    try:
        # Ask git where the root is directly (fastest method)
        # We use strict boundaries to ensure we don't jump out of the workspace
        repo = git.Repo(current, search_parent_directories=True)
        repo_root = Path(repo.working_tree_dir).resolve()

        # If the found repo root is OUTSIDE our workspace src, ignore it.
        # This handles the case where user has a .git in /home/user/
        if repo_root != workspace_src and not workspace_src.is_relative_to(repo_root):
            # The workspace is inside the repo (nested), or repo is completely outside
            if repo_root.is_relative_to(workspace_src) or repo_root == workspace_src:
                return repo_root
            # If the repo root is higher up than src, we treat this package as not-git-managed
            return None

        return repo_root
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        return None


def _analyze_changes(repo: Repo) -> (List[str], int):
    """
    Summarize file changes (staged and unstaged).
    Returns a list of strings describing changes and total count.
    """
    summary = []
    total_modifications = 0

    # Check index (staged) and working tree (unstaged)
    # R=True finds renames
    for diff_list in [repo.index.diff("HEAD"), repo.index.diff(None)]:
        for diff in diff_list:
            total_modifications += 1
            if diff.change_type == "M":
                summary.append(f"Modified: {diff.a_path}")
            elif diff.change_type == "A":
                summary.append(f"Added: {diff.a_path}")
            elif diff.change_type == "D":
                summary.append(f"Deleted: {diff.a_path}")
            elif diff.change_type == "R":
                summary.append(f"Renamed: {diff.a_path} -> {diff.b_path}")
            else:
                summary.append(f"{diff.change_type}: {diff.a_path}")

    return summary, total_modifications


def _collect_repo_status(
    repo_path: Path, workspace_root: Path, fetch: bool
) -> RepoStatus:
    rel_path = str(repo_path.relative_to(workspace_root))

    try:
        repo = Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return RepoStatus(rel_path=rel_path, branch="unknown", is_git=False)

    # 1. Basic Info
    try:
        if repo.head.is_detached:
            branch_name = f"detached ({repo.head.commit.hexsha[:7]})"
        else:
            branch_name = repo.active_branch.name
    except ValueError:
        branch_name = "empty/unknown"

    # 2. Fetch if requested
    if fetch:
        for remote in repo.remotes:
            try:
                remote.fetch()
            except git.exc.GitCommandError as e:
                print_warn(f"Fetch failed for {remote.name} in {rel_path}: {e}")

    # 3. Analyze Branches
    unpushed = []
    local_only = []
    deleted_upstream = []

    for branch in repo.branches:
        tracking = branch.tracking_branch()
        if not tracking:
            local_only.append(branch.name)
            continue

        if not tracking.is_valid():
            deleted_upstream.append(branch.name)
            continue

        # Check for unpushed commits using rev-list (much faster than iter_commits)
        try:
            # count commits that are reachable from branch but not from tracking
            commits_ahead = repo.git.rev_list(
                "--count", f"{tracking.name}..{branch.name}"
            )
            if int(commits_ahead) > 0:
                unpushed.append(branch.name)
        except git.exc.GitCommandError:
            pass

    # 4. Changes and Stashes
    try:
        stash_count = (
            len(repo.git.stash("list").splitlines()) if repo.git.stash("list") else 0
        )
    except git.exc.GitCommandError:
        stash_count = 0

    untracked_files = repo.untracked_files
    changes_summary, mod_count = _analyze_changes(repo)

    has_changes = (
        bool(untracked_files)
        or bool(stash_count)
        or bool(unpushed)
        or bool(local_only)
        or bool(deleted_upstream)
        or mod_count > 0
    )

    return RepoStatus(
        rel_path=rel_path,
        branch=branch_name,
        is_git=True,
        has_changes=has_changes,
        untracked_count=len(untracked_files),
        stash_count=stash_count,
        unpushed_branches=unpushed,
        local_only_branches=local_only,
        deleted_upstream_branches=deleted_upstream,
        changes_summary=changes_summary,
        is_clean=not has_changes,
    )


def _print_status_report(status: RepoStatus, packages: List[str]):
    print_info(f"Repo: {status.rel_path} ({status.branch})")

    if not status.is_git:
        print_warn("  [!] Not a git repository")
        return

    labels = []
    if status.is_clean:
        labels.append("Clean")
    else:
        if status.unpushed_branches:
            labels.append("Unpushed commits")
        if status.local_only_branches:
            labels.append("Local-only branches")
        if status.deleted_upstream_branches:
            labels.append("Deleted upstream")
        if status.stash_count:
            labels.append("Stashed changes")
        if status.changes_summary or status.untracked_count:
            labels.append("Working tree dirty")

    print_info(f"Status: {', '.join(labels)}")

    # Details
    if status.has_changes:
        for b in status.unpushed_branches:
            print_color(Colors.RED, f"  Unpushed: {b}")
        for b in status.local_only_branches:
            print_color(Colors.LRED, f"  No Upstream: {b}")
        for b in status.deleted_upstream_branches:
            print_color(Colors.YELLOW, f"  Upstream Deleted: {b}")
        for change in status.changes_summary:
            print_color(Colors.ORANGE, f"  {change}")
        if status.untracked_count:
            print_color(Colors.LGRAY, f"  {status.untracked_count} untracked files")

    print("Packages in this repo:")
    for p in sorted(packages):
        print(f"  - {p}")


def remove_packages(
    workspace_root_str: str, items: List[str], fetch_remotes: bool = False
) -> int:
    if not workspace_root_str:
        print_error("No workspace configured!")
        return 1

    workspace_root = Path(workspace_root_str).resolve()
    src_root = workspace_root / "src"

    if not items:
        print_error("No packages specified.")
        return 1

    # Deduplicate items
    items = list(dict.fromkeys(items))

    repo_map: Dict[Path, List[str]] = {}
    repos_explicitly_selected: Set[Path] = set()
    missing_items = []

    # 1. Resolve Items to Repositories
    for item in items:
        # Check if item is a package name
        pkg_path_str = get_package_path(item, str(workspace_root))

        if pkg_path_str:
            repo_root = _get_repo_root(Path(pkg_path_str), src_root)
            if not repo_root:
                print_error(
                    f"Package '{item}' is not in a recognized git repo within src."
                )
                return 1

            if repo_root not in repo_map:
                repo_map[repo_root] = []
            if item not in repo_map[repo_root]:
                repo_map[repo_root].append(item)

        else:
            # Check if item is a directory path (relative to ws or src)
            candidate = workspace_root / item
            candidate_src = src_root / item

            found_repo = None
            if candidate.is_dir():
                found_repo = candidate.resolve()
            elif candidate_src.is_dir():
                found_repo = candidate_src.resolve()

            if found_repo:
                # Verify it's actually a repo or inside one
                real_repo = _get_repo_root(found_repo, src_root)
                if real_repo:
                    repos_explicitly_selected.add(real_repo)
                    # We will populate packages later
                    if real_repo not in repo_map:
                        repo_map[real_repo] = []
                else:
                    print_error(f"Path '{item}' is not a git repository.")
            else:
                missing_items.append(item)

    if missing_items:
        print_error(f"Not found: {', '.join(missing_items)}")
        return 1

    # 2. Check for "Partial" Repo Removals
    # If user asked to remove pkg A, but Repo contains A and B, we must ask.
    final_repos_to_process = []

    for repo_root, requested_pkgs in repo_map.items():
        all_pkgs_in_repo = find_packages_in_directory(str(repo_root))

        # If the user selected the REPO path explicitly, they imply deleting everything.
        if repo_root in repos_explicitly_selected:
            final_repos_to_process.append((repo_root, all_pkgs_in_repo))
            continue

        # Otherwise, check if they missed any packages
        extra_pkgs = [p for p in all_pkgs_in_repo if p not in requested_pkgs]

        if extra_pkgs:
            repo_rel = repo_root.relative_to(workspace_root)
            print_warn(
                f"Repository '{repo_rel}' contains other packages: {', '.join(extra_pkgs)}"
            )
            if not confirm("Remove the entire repository and all these packages?"):
                print_info("Skipping.")
                continue

        final_repos_to_process.append((repo_root, all_pkgs_in_repo))

    # 3. Execution Phase
    for repo_root, packages in final_repos_to_process:
        repo_rel = repo_root.relative_to(workspace_root)

        # Safety: Final check that we are deleting something inside src
        if not repo_root.is_relative_to(src_root):
            print_error(f"SAFETY GUARD: Refusing to delete {repo_root} (outside src)")
            continue

        status = _collect_repo_status(repo_root, workspace_root, fetch_remotes)
        _print_status_report(status, packages)

        has_uncommitted = bool(status.changes_summary) or status.untracked_count > 0
        has_unpushed = bool(status.unpushed_branches) or bool(
            status.local_only_branches
        )
        if has_uncommitted or has_unpushed:
            print_error(
                "WARNING: repository has uncommitted changes or unpushed commits."
            )
            if not confirm(f"Proceed with deletion of {repo_rel} anyway?"):
                continue
        if not confirm(f"DELETE {repo_rel}?"):
            continue

        # Clean build artifacts first -> install and build folders
        if packages:
            if not clean_packages(str(workspace_root), packages, force=True):
                print_error("Failed to clean build artifacts.")

        print_info(f"Deleting {repo_rel}...")
        try:
            shutil.rmtree(repo_root)
            print_info("Deleted.")
        except OSError as e:
            print_error(f"Failed to delete {repo_root}: {e}")

    return 0
