import shutil
from pathlib import Path
from typing import List

from .build import clean_packages
from .git_helpers import (
    RepoStatus,
    collect_repo_status,
    get_repo_root,
    find_merge_evidence,
)
from .print import Colors, confirm, print_error, print_info, print_warn, print_color
from .workspace import find_packages_in_directory, get_package_path

try:
    import git
except ImportError:
    print_error("GitPython is required! Install using 'pip install gitpython'")
    raise


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
            for b, count in status.unpushed_branches:
                commits_str = "commit" if count == 1 else "commits"
                print_color(Colors.RED, f"  Unpushed: {b} ({count} {commits_str})")
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
            repo_root = get_repo_root(Path(pkg_path_str), src_root)
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
        real_repo = get_repo_root(found_path, src_root)
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
        print_info(f"Collecting status for repo {repo_root}...")
        repo_rel = repo_root.relative_to(workspace_root)
        status = collect_repo_status(repo_root, workspace_root, fetch_remotes)
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
