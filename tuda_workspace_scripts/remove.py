import shutil
from pathlib import Path
from typing import List

from .build import clean_packages
from .git_utils import (
    get_repo_root,
    get_repo_status,
    launch_subprocess,
    print_repo_status,
)
from .print import confirm, print_error, print_info, print_warn
from .workspace import find_packages_in_directory, get_package_path


def remove_packages(
    workspace_root_str: str, items: List[str], fetch_remotes: bool = False
) -> int:
    """Remove specified items (packages or repositories) from the workspace.

    For git repositories, checks for dirty state (uncommitted changes, unpushed
    commits, stash entries) and warns before deletion. For non-git targets
    (loose directories under src/), warns explicitly that contents cannot be
    recovered and requires confirmation.

    Args:
        workspace_root_str: Path to the workspace root as a string.
        items: List of package names or repository paths to remove.
        fetch_remotes: Whether to fetch remotes before checking mainline merge state.
    Returns:
        0 on success, 1 on failure.
    """
    if not workspace_root_str:
        print_error("No workspace configured!")
        return 1
    if not items:
        print_error("No packages or repositories specified for removal.")
        return 1

    workspace_root = Path(workspace_root_str).resolve()
    src_root = (workspace_root / "src").resolve()

    items = list(dict.fromkeys(items))
    target_map = {}
    targets_explicitly_selected = set()
    non_git_targets = set()
    missing_items = []

    # 1) Resolve items to deletion targets (repo root if git, else item directory)
    for item in items:
        pkg_path_str = get_package_path(item, str(workspace_root))
        if pkg_path_str:
            pkg_path = Path(pkg_path_str).resolve()
            if pkg_path.is_relative_to(src_root):
                repo_root = get_repo_root(pkg_path, src_root)
                if repo_root:
                    target_map.setdefault(repo_root, []).append(item)
                else:
                    target_map.setdefault(pkg_path, []).append(item)
                    non_git_targets.add(pkg_path)
                continue

        candidate = (src_root / item).resolve()
        if not candidate.is_relative_to(src_root) or not candidate.is_dir():
            missing_items.append(item)
            continue
        real_repo = get_repo_root(candidate, src_root)
        if real_repo:
            targets_explicitly_selected.add(real_repo)
            target_map.setdefault(real_repo, [])
        else:
            targets_explicitly_selected.add(candidate)
            target_map.setdefault(candidate, [])
            non_git_targets.add(candidate)

    if missing_items:
        print_error(f"Not found: {', '.join(missing_items)}")
        return 1

    final_targets = []
    for target_path, requested in target_map.items():
        all_pkgs = find_packages_in_directory(str(target_path))
        if target_path not in targets_explicitly_selected:
            extra = [p for p in all_pkgs if p not in requested]
            if extra:
                kind = "Directory" if target_path in non_git_targets else "Repo"
                print_warn(
                    f"{kind} '{target_path.relative_to(workspace_root)}' contains other packages: {', '.join(extra)}"
                )
                if not confirm(
                    f"Remove all of {target_path.relative_to(workspace_root)}?"
                ):
                    continue
        final_targets.append((target_path, all_pkgs))

    success = True
    for target_path, packages in final_targets:
        target_rel = target_path.relative_to(workspace_root)
        is_non_git = target_path in non_git_targets

        if is_non_git:
            print_warn(
                f"'{target_rel}' is not a git repository. "
                "Its contents cannot be recovered after deletion."
            )
            has_local_work = True
        else:
            print_info(f"Collecting status for repo {target_path}...")
            if fetch_remotes:
                fetch_result = launch_subprocess(
                    ["git", "fetch", "--prune", "--all", "--quiet"],
                    cwd=target_path,
                    timeout=180,
                )
                if fetch_result.returncode != 0:
                    print_warn(
                        "Failed to fetch remotes; "
                        "merge / unpushed status may be stale."
                    )
            status = get_repo_status(target_path, workspace_root)
            print_repo_status(status, always_print_header=True)
            if not status.is_git:
                # Defensive: get_repo_root validated this earlier; treat as risky.
                has_local_work = True
            else:
                has_local_work = (
                    status.has_changes or status.has_unmerged_deleted_branches
                )

        if packages:
            print("Packages:")
            for p in sorted(packages):
                print(f"  - {p}")

        if has_local_work:
            if not is_non_git:
                print_error(
                    "WARNING: local work will be lost (dirty/stash/unpushed/unmerged)."
                )
            if not confirm(f"Proceed with deletion of {target_rel} anyway?"):
                continue

        if not confirm(f"DELETE {target_rel}?"):
            continue

        if packages:
            clean_packages(str(workspace_root), packages, force=True)
        print_info(f"Deleting {target_rel}...")
        try:
            shutil.rmtree(target_path)
            print_info("Deleted.")
        except OSError as e:
            print_error(f"Failed to delete {target_path}: {e}")
            success = False
    return 0 if success else 1
