import os
import shutil

from .build import clean_packages
from .print import Colors, confirm, print_error, print_info, print_warn, print_color
from .workspace import find_packages_in_directory, get_package_path

try:
    import git
except ImportError:
    print_error(
        "GitPython is required! Install using 'pip3 install --user gitpython' or 'apt install python3-git'"
    )
    raise


def _repo_root_from_package_path(package_path: str, workspace_root: str) -> str | None:
    try:
        repo = git.Repo(package_path, search_parent_directories=True)
        return repo.working_tree_dir
    except git.exc.InvalidGitRepositoryError:
        src_root = os.path.realpath(os.path.join(workspace_root, "src"))
        path = os.path.realpath(package_path)
        while path and path != src_root:
            parent = os.path.realpath(os.path.dirname(path))
            if parent == src_root:
                return path
            if parent == path:
                break
            path = parent
    return None


def _repo_root_from_item(item: str, workspace_root: str) -> str | None:
    if os.path.isdir(item):
        return os.path.realpath(item)
    if os.path.isabs(item):
        return None
    candidates = [
        os.path.join(workspace_root, "src", item),
        os.path.join(workspace_root, item),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.realpath(candidate)
    return None


def _repo_has_changes(repo_root: str, workspace_root: str) -> bool:
    try:
        repo = git.Repo(repo_root, search_parent_directories=False)
    except git.exc.InvalidGitRepositoryError:
        print_warn(f"{os.path.relpath(repo_root, workspace_root)} is not a git repo.")
        return True

    try:
        stash_list = repo.git.stash("list")
        changes = list(repo.index.diff(None))
    except git.exc.GitCommandError as e:
        print_error(
            f"Failed to obtain changes for {os.path.relpath(repo_root, workspace_root)}: {e}"
        )
        return True

    try:
        changes += list(repo.index.diff("HEAD", R=True))
    except git.BadName:
        pass

    untracked = repo.untracked_files
    unpushed_branches = []
    local_branches = []
    deleted_branches = []
    for branch in repo.branches:
        tracking = branch.tracking_branch()
        if tracking is None:
            local_branches.append(branch)
            continue
        if not tracking.is_valid():
            deleted_branches.append(branch)
            continue
        try:
            if any(
                True for _ in repo.iter_commits(f"{branch.name}@{{u}}..{branch.name}")
            ):
                unpushed_branches.append(branch)
        except git.exc.GitCommandError as e:
            print_error(
                f"{os.path.relpath(repo_root, workspace_root)} has error on branch {branch.name}: {e}"
            )
            return True

    has_changes = (
        any(untracked)
        or bool(stash_list)
        or any(unpushed_branches)
        or any(local_branches)
        or any(deleted_branches)
        or any(changes)
    )

    if not has_changes:
        return False

    if not repo.head.is_valid():
        branch_name = "unknown"
    elif repo.head.is_detached:
        branch_name = f"detached at {repo.head.commit}"
    else:
        branch_name = repo.head.ref.name

    print_info(
        f"{os.path.relpath(repo_root, workspace_root)} {Colors.LPURPLE}({branch_name})"
    )
    for branch in unpushed_branches:
        print_color(Colors.RED, f"  Unpushed commits on branch {branch}!")
    for branch in local_branches:
        print_color(Colors.LRED, f"  Local branch with no upstream: {branch}")
    for branch in deleted_branches:
        print_color(Colors.LRED, f"  Local branch with deleted upstream: {branch}")
    if bool(stash_list):
        print_color(Colors.LCYAN, "  Stashed changes")
    for item in changes:
        if item.change_type.startswith("M"):
            print_color(Colors.ORANGE, f"  Modified: {item.a_path}")
        elif item.change_type.startswith("D"):
            print_color(Colors.RED, f"  Deleted: {item.a_path}")
        elif item.change_type.startswith("R"):
            print_color(Colors.GREEN, f"  Renamed: {item.a_path} -> {item.b_path}")
        elif item.change_type.startswith("A"):
            print_color(Colors.GREEN, f"  Added: {item.a_path}")
        elif item.change_type.startswith("U"):
            print_error(f"  Unmerged: {item.a_path}")
        elif item.change_type.startswith("C"):
            print_color(Colors.GREEN, f"  Copied: {item.a_path} -> {item.b_path}")
        elif item.change_type.startswith("T"):
            print_color(Colors.ORANGE, f"  Type changed: {item.a_path}")
        else:
            print_color(
                Colors.RED,
                f"  Unhandled change type '{item.change_type}': {item.a_path}",
            )
    if len(untracked) < 10:
        for file in untracked:
            print_color(Colors.LGRAY, f"  Untracked: {file}")
    else:
        print_color(Colors.LGRAY, f"  {len(untracked)} untracked files.")
    print("")
    return True


def remove_packages(workspace_root: str, items: list[str]) -> int:
    if workspace_root is None:
        print_error("No workspace configured!")
        return 1

    if not items:
        print_error("No packages or repositories specified for removal.")
        return 1

    items_unique = []
    seen = set()
    for item in items:
        if item not in seen:
            items_unique.append(item)
            seen.add(item)

    repo_map: dict[str, list[str]] = {}
    selected_repo_roots: set[str] = set()
    missing_items = []
    for item in items_unique:
        package_path = get_package_path(item, workspace_root)
        if package_path is not None:
            repo_root = _repo_root_from_package_path(package_path, workspace_root)
            if repo_root is None:
                print_error(f"Failed to locate repository for {item}.")
                return 1
            repo_root = os.path.realpath(repo_root)
            if repo_root not in selected_repo_roots:
                repo_packages = repo_map.setdefault(repo_root, [])
                if item not in repo_packages:
                    repo_packages.append(item)
            continue

        repo_root = _repo_root_from_item(item, workspace_root)
        if repo_root is not None:
            repo_root = os.path.realpath(repo_root)
            selected_repo_roots.add(repo_root)
            repo_map[repo_root] = find_packages_in_directory(repo_root)
            continue

        missing_items.append(item)

    if missing_items:
        print_error(f"Packages or repositories not found: {', '.join(missing_items)}")
        return 1

    src_root = os.path.realpath(os.path.join(workspace_root, "src"))
    for repo_root in list(repo_map.keys()):
        if repo_root not in selected_repo_roots:
            repo_packages = find_packages_in_directory(repo_root)
            extra_packages = [p for p in repo_packages if p not in items_unique]
            if extra_packages:
                repo_rel = os.path.relpath(repo_root, workspace_root)
                if not confirm(
                    f"Repository '{repo_rel}' contains additional packages "
                    f"not requested for removal: {', '.join(extra_packages)}. "
                    "Remove entire repository anyway?"
                ):
                    print_info(f"Skipping repository {repo_rel}.")
                    del repo_map[repo_root]
                    continue
            repo_map[repo_root] = repo_packages
        else:
            repo_map[repo_root] = find_packages_in_directory(repo_root)

    for repo_root in list(repo_map.keys()):
        if _repo_has_changes(repo_root, workspace_root):
            if not confirm(
                "Repository has local changes, stashes, or unpushed commits. "
                "Remove anyway (brute-force)?"
            ):
                print_info(
                    f"Skipping repository {os.path.relpath(repo_root, workspace_root)}."
                )
                del repo_map[repo_root]

    for repo_root, repo_packages in repo_map.items():
        repo_root_real = os.path.realpath(repo_root)
        if not repo_root_real.startswith(src_root + os.path.sep):
            print_error(
                f"Refusing to remove non-src repository: {os.path.relpath(repo_root, workspace_root)}"
            )
            continue

        repo_rel = os.path.relpath(repo_root, workspace_root)
        print_info(f"About to clean {repo_rel}.")
        print("Includes the following packages:")
        for package in sorted(repo_packages):
            print(f"- {package}")
        if not confirm(f"Are you sure you want to clean {repo_rel}?"):
            print_info(f"Skipping repository {repo_rel}.")
            continue

        if not repo_packages:
            print_warn(f"No packages found in {repo_rel}. Skipping cleanup.")
            continue

        if not clean_packages(workspace_root, repo_packages, force=True):
            print_error(f"Failed to clean build/install for {repo_rel}.")
            continue

        print_info(f"Removing source at {repo_rel}...")
        shutil.rmtree(repo_root)
        print_info(f"Removed {repo_rel}.")

    return 0
