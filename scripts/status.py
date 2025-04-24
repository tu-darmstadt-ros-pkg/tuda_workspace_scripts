#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.workspace import get_workspace_root

try:
    import git
    from git.exc import GitCommandError
except ImportError:
    print(
        "GitPython is required! Install using 'pip3 install --user gitpython' or 'apt install python3-git'"
    )
    raise
import os


def print_changes(path, root_path):
    try:
        repo = git.Repo(path, search_parent_directories=False)
    except git.exc.InvalidGitRepositoryError:
        print_error("Failed to obtain git info for: {}".format(path))
        return
    try:
        stash = repo.git.stash("list")
        changes = repo.index.diff(None)
    except GitCommandError as e:
        if "not a git repository" in e.stderr:
            return
        print_error("Failed to obtain changes for {}: {}".format(path, e))
        return
    try:
        # Need to reverse using R=True, otherwise we get the diff from tree to HEAD meaning deleted files are added and vice versa
        changes += repo.index.diff("HEAD", R=True)
    except git.BadName as e:
        pass  # Repo has no HEAD which means it probably also has no branches yet and was just initialized

    # Check branches for uncommited commits and pure local branches
    uncommited_commits = []
    local_branches = []
    deleted_branches = []
    for branch in repo.branches:
        if branch.tracking_branch() is None:
            local_branches.append(branch)
            continue
        if not branch.tracking_branch().is_valid():
            deleted_branches.append(branch)
            continue
        try:
            if any(
                True for _ in repo.iter_commits("{0}@{{u}}..{0}".format(branch.name))
            ):
                uncommited_commits.append(branch)
        except (git.exc.GitCommandError, Exception) as e:
            print_error(
                "{} has error on branch {}: {}".format(path, branch.name, e.message)
            )

    if (
        any(repo.untracked_files)
        or any(stash)
        or any(uncommited_commits)
        or any(local_branches)
        or any(changes)
    ):
        if not repo.head.is_valid():
            branch_name = "unknown"
        elif repo.head.is_detached:
            branch_name = f"detached at {repo.head.commit}"
        else:
            branch_name = repo.head.ref.name
        print_info(
            f"{os.path.relpath(path, root_path)} {Colors.LPURPLE}({branch_name})"
        )
        if len(repo.branches) == 0:
            print_color(Colors.LRED, "  No branches configured upstream.")
        for branch in uncommited_commits:
            print_color(Colors.RED, "  Unpushed commits on branch {}!".format(branch))
        for branch in local_branches:
            print_color(
                Colors.LRED, "  Local branch with no remote set up: {}".format(branch)
            )
        for branch in deleted_branches:
            print_color(
                Colors.LRED,
                "  Local branch for which remote was deleted: {}".format(branch),
            )
        if any(stash):
            print_color(Colors.LCYAN, "  Stashed changes")
        for item in changes:
            if item.change_type.startswith("M"):
                print_color(Colors.ORANGE, "  Modified: {}".format(item.a_path))
            elif item.change_type.startswith("D"):
                print_color(Colors.RED, "  Deleted: {}".format(item.a_path))
            elif item.change_type.startswith("R"):
                print_color(
                    Colors.GREEN, "  Renamed: {} -> {}".format(item.a_path, item.b_path)
                )
            elif item.change_type.startswith("A"):
                print_color(Colors.GREEN, "  Added: {}".format(item.a_path))
            elif item.change_type.startswith("U"):
                print_error("  Unmerged: {}".format(item.a_path))
            elif item.change_type.startswith("C"):
                print_color(
                    Colors.GREEN, "  Copied: {} -> {}".format(item.a_path, item.b_path)
                )
            elif item.change_type.startswith("T"):
                print_color(Colors.ORANGE, "  Type changed: {}".format(item.a_path))
            else:
                print_color(
                    Colors.RED,
                    "  Unhandled change type '{}': {}".format(
                        item.change_type, item.a_path
                    ),
                )
        if len(repo.untracked_files) < 10:
            for file in repo.untracked_files:
                print_color(Colors.LGRAY, "  Untracked: {}".format(file))
        else:
            print_color(
                Colors.LGRAY, "  {} untracked files.".format(len(repo.untracked_files))
            )
        print("")
    elif repo.is_dirty():
        print_info(path)
        print_error("  Dirty but I don't know why")
        print("")


def main() -> int:
    ws_root_path = get_workspace_root()
    if ws_root_path is None:
        print_workspace_error()
        return 1

    if os.path.isdir(os.path.join(ws_root_path, ".git")):
        print_color(Colors.GREEN, "Looking for changes in {}...".format(ws_root_path))
        print_changes(ws_root_path, None)

    def scan_workspace(path, root_path):
        if not os.path.isdir(path):
            return
        try:
            subdirs = os.listdir(path)
        except Exception as e:
            print_error("Error while scanning '{}'!\nMessage: {}".format(path, str(e)))
            return
        if ".git" in subdirs:
            print_changes(path, root_path)

        for subdir in sorted(subdirs):
            scan_workspace(os.path.join(path, subdir), root_path)

    ws_src_path = os.path.join(ws_root_path, "src")
    print_color(Colors.GREEN, "Looking for changes in {}...".format(ws_src_path))
    scan_workspace(ws_src_path, ws_src_path)
    return 0


if __name__ == "__main__":
    try:
        exit(main() or 0)
    except KeyboardInterrupt:
        print_error("Ctrl+C received! Exiting...")
        exit(0)
