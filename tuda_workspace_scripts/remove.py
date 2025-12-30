import shutil
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
    is_git: bool = False

    # local changes / risks
    has_changes: bool = False
    untracked_count: int = 0
    stash_count: int = 0
    changes_summary: List[str] = field(default_factory=list)

    # only meaningful if fetch_remotes=True
    unpushed_branches: List[str] = field(default_factory=list)
    local_only_branches: List[str] = field(default_factory=list)
    deleted_upstream_branches: List[str] = field(default_factory=list)

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

    # accept only if repo root is within ws/src (or equals)
    if repo_root == workspace_src or repo_root.is_relative_to(workspace_src):
        return repo_root

    return None


def _collect_worktree_changes(repo: Repo) -> Tuple[List[str], int, int]:
    """
    Return (changes_summary, modified_count, untracked_count) using
    `git status --porcelain` (robust, fast, works even if HEAD is unborn).
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

        # Untracked: "?? path"
        if line.startswith("?? "):
            untracked_count += 1
            continue

        # Format: XY <path> (or rename "R  old -> new")
        xy = line[:2]
        rest = line[3:] if len(line) > 3 else ""

        modified_count += 1

        # very simple labels (keep it readable)
        if "R" in xy and "->" in rest:
            changes_summary.append(f"Renamed: {rest}")
        elif "D" in xy:
            changes_summary.append(f"Deleted: {rest}")
        elif "A" in xy:
            changes_summary.append(f"Added: {rest}")
        else:
            changes_summary.append(f"Modified: {rest}")

    return changes_summary, modified_count, untracked_count


def _collect_repo_status(
    repo_path: Path, workspace_root: Path, fetch: bool
) -> RepoStatus:
    rel_path = str(repo_path.relative_to(workspace_root))

    try:
        repo = Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return RepoStatus(rel_path=rel_path, branch="unknown", is_git=False)

    # Branch info
    try:
        if repo.head.is_detached:
            branch_name = f"detached ({repo.head.commit.hexsha[:7]})"
        else:
            branch_name = repo.active_branch.name
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
        stash_count = 0

    # remote-related checks only if fetch=True (avoid lying when refs are stale)
    unpushed: List[str] = []
    local_only: List[str] = []
    deleted_upstream: List[str] = []

    if fetch:
        for remote in repo.remotes:
            try:
                remote.fetch(prune=True)
            except git.exc.GitCommandError as e:
                print_warn(f"Fetch failed for {remote.name} in {rel_path}: {e}")

        for branch in repo.branches:
            tracking = branch.tracking_branch()
            if not tracking:
                local_only.append(branch.name)
                continue

            # tracking ref might still not exist locally; treat as deleted/unknown
            try:
                # "git show-ref --verify refs/remotes/..."
                repo.git.show_ref(
                    "--verify",
                    f"refs/remotes/{tracking.remote_head}",
                    with_exceptions=True,
                )
            except Exception:
                # safer: just label as deleted/unknown if tracking cannot be verified after fetch
                deleted_upstream.append(branch.name)
                continue

            try:
                commits_ahead = int(
                    repo.git.rev_list("--count", f"{tracking.name}..{branch.name}")
                )
                if commits_ahead > 0:
                    unpushed.append(branch.name)
            except Exception:
                # ignore; keep script simple
                pass

    has_changes = (
        (mod_count > 0)
        or (untracked_count > 0)
        or (stash_count > 0)
        or bool(unpushed)
        or bool(local_only)
        or bool(deleted_upstream)
    )

    return RepoStatus(
        rel_path=rel_path,
        branch=branch_name,
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
    print_info(f"Repo: {status.rel_path} ({status.branch})")

    if not status.is_git:
        print_warn("  [!] Not a git repository")
        return

    labels: List[str] = []
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
        else:
            if (
                status.unpushed_branches
                or status.local_only_branches
                or status.deleted_upstream_branches
            ):
                # shouldn't happen, but keep logic consistent
                labels.append("Remote status unknown")

    print_info(f"Status: {', '.join(labels)}")

    if status.has_changes:
        if fetched:
            for b in status.unpushed_branches:
                print_color(Colors.RED, f"  Unpushed: {b}")
            for b in status.local_only_branches:
                print_color(Colors.LRED, f"  No Upstream: {b}")
            for b in status.deleted_upstream_branches:
                print_color(Colors.YELLOW, f"  Upstream Missing: {b}")
        else:
            # gentle hint
            print_color(
                Colors.LGRAY,
                "  (Hint: run with fetch_remotes=True to check upstream state)",
            )

        for change in status.changes_summary[:50]:
            print_color(Colors.ORANGE, f"  {change}")
        if len(status.changes_summary) > 50:
            print_color(
                Colors.LGRAY, f"  ... +{len(status.changes_summary) - 50} more changes"
            )

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

    workspace_root = Path(workspace_root_str).resolve()
    src_root = (workspace_root / "src").resolve()

    if not items:
        print_error("No packages specified.")
        return 1

    items = list(dict.fromkeys(items))  # deduplicate while preserving order

    repo_map: Dict[Path, List[str]] = {}
    repos_explicitly_selected: Set[Path] = set()
    missing_items: List[str] = []

    # 1) Resolve items to repos
    for item in items:
        pkg_path_str = get_package_path(item, str(workspace_root))

        if pkg_path_str:
            repo_root = _get_repo_root(Path(pkg_path_str), src_root)
            if not repo_root:
                print_error(f"Package '{item}' is not in a git repo within {src_root}.")
                return 1
            repo_map.setdefault(repo_root, [])
            if item not in repo_map[repo_root]:
                repo_map[repo_root].append(item)
            continue

        # treat as path (relative to ws or src)
        candidate_ws = workspace_root / item
        candidate_src = src_root / item

        found_path: Optional[Path] = None
        if candidate_ws.is_dir():
            found_path = candidate_ws
        elif candidate_src.is_dir():
            found_path = candidate_src

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

    # 2) Determine final repos and packages to clean
    final_repos_to_process: List[Tuple[Path, List[str]]] = []

    for repo_root, requested_pkgs in repo_map.items():
        all_pkgs_in_repo = find_packages_in_directory(str(repo_root))

        if repo_root in repos_explicitly_selected:
            final_repos_to_process.append((repo_root, all_pkgs_in_repo))
            continue

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

    # 3) Execute deletions
    for repo_root, packages in final_repos_to_process:
        repo_root = repo_root.resolve()
        repo_rel = repo_root.relative_to(workspace_root)

        # final safety guard
        if not repo_root.is_relative_to(src_root):
            print_error(
                f"SAFETY GUARD: Refusing to delete {repo_root} (outside {src_root})"
            )
            continue

        status = _collect_repo_status(repo_root, workspace_root, fetch_remotes)
        _print_status_report(status, packages, fetched=fetch_remotes)

        # Decide whether to warn
        has_uncommitted = bool(status.changes_summary) or status.untracked_count > 0
        has_local_work = has_uncommitted or (status.stash_count > 0)
        has_unpushed = bool(status.unpushed_branches) or bool(
            status.local_only_branches
        )

        if has_local_work or has_unpushed:
            print_error("WARNING: local work will be lost (dirty/stash/unpushed).")
            if not confirm(f"Proceed with deletion of {repo_rel} anyway?"):
                continue

        if not confirm(f"DELETE {repo_rel}?"):
            continue

        # clean build artifacts first
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
