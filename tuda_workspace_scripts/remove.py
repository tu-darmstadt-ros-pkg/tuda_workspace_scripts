import shutil
import subprocess
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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
    mainline: str = "unknown"
    is_git: bool = False

    # local changes / risks
    has_changes: bool = False
    untracked_count: int = 0
    stash_count: int = 0
    changes_summary: List[str] = field(default_factory=list)

    # only meaningful if fetch_remotes=True
    unpushed_branches: List[str] = field(default_factory=list)
    local_only_branches: List[str] = field(default_factory=list)
    # Stores tuples of (branch_name, merge_hint)
    deleted_upstream_branches: List[Tuple[str, str]] = field(default_factory=list)

    is_clean: bool = True


def _get_repo_root(path: Path, workspace_src: Path) -> Optional[Path]:
    """
    Return the git working tree root for `path`, but ONLY if the repo root is
    inside `workspace_src` (or equals it). Otherwise return None.

    This prevents accidentally picking up e.g. /home/user as a repo root.
    """
    workspace_src = workspace_src.resolve()
    current = path.resolve()

    # must be within ws/src
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


def _collect_worktree_changes(repo: Repo) -> Tuple[List[str], int, int]:
    """
    Return (changes_summary, modified_count, untracked_count) using
    `git status --porcelain`.
    """
    try:
        out = repo.git.status("--porcelain=v1").splitlines()
    except git.exc.GitCommandError:
        out = []
    changes_summary, modified_count, untracked_count = [], 0, 0
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


def _remote_head_mainline_ref(repo: git.Repo, remote_name: str) -> str | None:
    """
    Resolve the remote's configured mainline via refs/remotes/<remote>/HEAD.
    Returns a ref like '<remote>/<branch>' (e.g. 'origin/ros2') or None.
    """
    head_ref = f"refs/remotes/{remote_name}/HEAD"
    prefix = f"refs/remotes/{remote_name}/"

    def try_resolve():
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
    try:
        subprocess.run(
            ["git", "remote", "set-head", remote_name, "-a"],
            cwd=repo.working_tree_dir,
            capture_output=True,
            timeout=10,
        )
        return try_resolve()
    except Exception:
        return None


def _get_dynamic_mainline(repo: git.Repo) -> str:
    """
    Detects the mainline branch name (e.g. 'main') dynamically.
    Prioritizes remote-tracking HEAD, falls back to common names.
    """
    for remote in repo.remotes:
        mainline_ref = _remote_head_mainline_ref(repo, remote.name)
        if mainline_ref:
            return mainline_ref.split("/", 1)[1]
    ros_distro = os.environ.get("ROS_DISTRO", "").lower()
    for candidate in [ros_distro, "main", "master"]:
        if candidate and candidate in repo.heads:
            return candidate
    return "main"


def _find_merge_evidence(
    repo: git.Repo, branch: git.Head, mainline: str
) -> Tuple[bool, str]:
    try:
        local_mainline = repo.heads[mainline]
        tracking_ref = local_mainline.tracking_branch()
        target = tracking_ref.name if tracking_ref else mainline

        # 1. Direct Ancestry
        if repo.is_ancestor(branch.commit, target):
            return True, f"merged into {target}"

        # 2. Squash Merge Search
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


def _collect_repo_status(
    repo_path: Path, workspace_root: Path, fetch: bool
) -> RepoStatus:
    rel_path = str(repo_path.relative_to(workspace_root))
    try:
        repo = Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return RepoStatus(rel_path=rel_path, branch="unknown", is_git=False)

    mainline = _get_dynamic_mainline(repo)
    try:
        branch_name = (
            f"detached ({repo.head.commit.hexsha[:7]})"
            if repo.head.is_detached
            else repo.active_branch.name
        )
    except Exception:
        branch_name = "unknown"

    # local working tree status
    changes_summary, mod_count, untracked_count = _collect_worktree_changes(repo)

    # stashes
    stash_count = 0
    try:
        stash_out = repo.git.stash("list")
        stash_count = len(stash_out.splitlines()) if stash_out else 0
    except git.exc.GitCommandError:
        pass

    unpushed, local_only, deleted_upstream = [], [], []
    if fetch:
        try:
            # use subprocess for speed and timeout
            subprocess.run(
                ["git", "fetch", "--prune", "--all", "--quiet"],
                cwd=str(repo_path),
                capture_output=True,
                timeout=30,
            )
        except Exception as e:
            print_warn(f"Fetch failed for {rel_path}: {e}")

        for branch in repo.branches:
            tracking = branch.tracking_branch()
            if not tracking:
                if branch.name != mainline:
                    local_only.append(branch.name)
                continue

            try:
                # Use tracking.path (refs/remotes/...) to verify physical existence
                repo.git.show_ref("--verify", tracking.path, with_exceptions=True)
            except Exception:
                _, hint = _find_merge_evidence(repo, branch, mainline)
                deleted_upstream.append((branch.name, hint))
                continue
            try:
                if (
                    int(repo.git.rev_list("--count", f"{tracking.name}..{branch.name}"))
                    > 0
                ):
                    unpushed.append(branch.name)
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


def _print_status_report(status: RepoStatus, packages: List[str], fetched: bool):
    print_info(
        f"Repo: {status.rel_path} (local: {status.branch} | mainline: {status.mainline})"
    )
    if not status.is_git:
        print_warn("  [!] Not a git repository")
        return

    labels = []
    if status.is_clean:
        labels.append("Clean")
    else:
        if status.changes_summary or status.untracked_count:
            labels.append("Working tree dirty")
        if status.stash_count:
            labels.append("Stashed changes")
        if fetched:
            if status.unpushed_branches:
                labels.append("Unpushed commits")
            if status.local_only_branches:
                labels.append("Local-only branches")
            if status.deleted_upstream_branches:
                labels.append("Upstream missing")

    print_info(f"Status: {', '.join(labels)}")
    if status.has_changes:
        if fetched:
            for b in status.unpushed_branches:
                print_color(Colors.RED, f"  Unpushed: {b}")
            for b in status.local_only_branches:
                print_color(Colors.LRED, f"  No Upstream: {b}")
            for b, hint in status.deleted_upstream_branches:
                color = Colors.GREEN if "merged" in hint else Colors.YELLOW
                print_color(color, f"  Upstream Missing: {b} ({hint})")
        else:
            print_color(Colors.LGRAY, "  (Hint: run with fetch_remotes=True)")

        for change in status.changes_summary[:50]:
            print_color(Colors.ORANGE, f"  {change}")
        if status.untracked_count:
            print_color(Colors.LGRAY, f"  {status.untracked_count} untracked files")
        if status.stash_count:
            print_color(Colors.LGRAY, f"  {status.stash_count} stash entries")
    print("Packages in this repo:")
    for p in sorted(packages):
        print(f"  - {p}")


def remove_packages(
    workspace_root_str: str, items: List[str], fetch_remotes: bool = False
) -> int:
    if not workspace_root_str:
        print_error("No workspace configured!")
        return 1
    workspace_root, src_root = (
        Path(workspace_root_str).resolve(),
        (Path(workspace_root_str) / "src").resolve(),
    )
    if not items:
        print_error("No packages specified.")
        return 1

    items = list(dict.fromkeys(items))
    repo_map, repos_explicitly_selected, missing_items = {}, set(), []

    # 1) Resolve items to repos
    for item in items:
        pkg_path_str = get_package_path(item, str(workspace_root))
        if pkg_path_str:
            repo_root = _get_repo_root(Path(pkg_path_str), src_root)
            if not repo_root:
                print_error(f"Package '{item}' is not in a git repo within {src_root}.")
                return 1
            repo_map.setdefault(repo_root, []).append(item)
            continue
        candidate_ws, candidate_src = workspace_root / item, src_root / item
        found_path = (
            candidate_ws
            if candidate_ws.is_dir()
            else (candidate_src if candidate_src.is_dir() else None)
        )
        if not found_path:
            missing_items.append(item)
            continue
        real_repo = _get_repo_root(found_path, src_root)
        if not real_repo:
            print_error(f"Path '{item}' is not a git repository inside {src_root}.")
            return 1
        repos_explicitly_selected.add(real_repo)
        repo_map.setdefault(real_repo, [])

    if missing_items:
        print_error(f"Not found: {', '.join(missing_items)}")
        return 1

    final_repos = []
    for repo_root, requested in repo_map.items():
        all_pkgs = find_packages_in_directory(str(repo_root))
        if repo_root not in repos_explicitly_selected:
            extra = [p for p in all_pkgs if p not in requested]
            if extra:
                print_warn(
                    f"Repo '{repo_root.relative_to(workspace_root)}' contains other packages: {', '.join(extra)}"
                )
                if not confirm("Remove the entire repository and all these packages?"):
                    continue
        final_repos.append((repo_root, all_pkgs))

    success = True
    for repo_root, packages in final_repos:
        repo_rel = repo_root.relative_to(workspace_root)
        status = _collect_repo_status(repo_root, workspace_root, fetch_remotes)
        _print_status_report(status, packages, fetched=fetch_remotes)

        unmerged_deleted = [
            b for b, hint in status.deleted_upstream_branches if "merged" not in hint
        ]
        has_local_work = (
            bool(status.changes_summary)
            or status.untracked_count > 0
            or status.stash_count > 0
            or bool(unmerged_deleted)
            or bool(status.unpushed_branches)
            or bool(status.local_only_branches)
        )

        if has_local_work:
            print_error(
                "WARNING: local work will be lost (dirty/stash/unpushed/unmerged)."
            )
            if not confirm(f"Proceed with deletion of {repo_rel} anyway?"):
                continue

        if not confirm(f"DELETE {repo_rel}?"):
            continue

        # clean build artifacts first
        if packages:
            if not clean_packages(str(workspace_root), packages, force=True):
                print_error("Failed to clean build artifacts.")
        # then delete the repo itself
        print_info(f"Deleting {repo_rel}...")
        try:
            shutil.rmtree(repo_root)
            print_info("Deleted.")
        except OSError as e:
            print_error(f"Failed to delete {repo_root}: {e}")
            success = False
    return 0 if success else 1
