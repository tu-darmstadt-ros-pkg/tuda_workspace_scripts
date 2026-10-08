#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
Reset all git repositories in the workspace to a clean state.

For each repository in src/:
  - If there are local changes (staged, unstaged, or untracked files), the user
    is asked whether to stash them, drop them, or leave the repository as-is.
    Choosing "leave" skips the branch check for that repository too.
  - If the repository is not on its default (mainline) branch, the user is asked
    whether to switch back to it.

Afterwards, all packages in modified repositories are rebuilt.
"""
import argparse
from pathlib import Path

import argcomplete
import subprocess

import git

from tuda_workspace_scripts.build import build_packages
from tuda_workspace_scripts.git_utils import (
    get_mainline_branch,
    get_repo_status,
)
from tuda_workspace_scripts.print import (
    Colors,
    print_color,
    print_error,
    print_info,
    print_success,
    print_warn,
    print_workspace_error,
)
from tuda_workspace_scripts.workspace import (
    find_packages_in_directory,
    get_repos_in_workspace,
    get_workspace_root,
)


# =============================================================================
# GIT OPERATIONS
# =============================================================================


def _stash_changes(repo: git.Repo, rel_path: str) -> bool:
    """Stash all local changes, including untracked files."""
    try:
        repo.git.stash("push", "--include-untracked", "-m", "hector reset: auto-stash")
        print_color(Colors.LCYAN, f"  Stashed changes.")
        return True
    except git.exc.GitCommandError as e:
        print_error(f"  Failed to stash changes in {rel_path}: {e}")
        return False


def _drop_changes(repo: git.Repo, rel_path: str) -> bool:
    """Discard all local changes and remove untracked/ignored files."""
    try:
        repo.git.checkout("--", ".")
        repo.git.clean("-fd")
        print_color(Colors.ORANGE, f"  Dropped all local changes.")
        return True
    except git.exc.GitCommandError as e:
        print_error(f"  Failed to drop changes in {rel_path}: {e}")
        return False


def _switch_to_mainline(repo: git.Repo, mainline: str, rel_path: str) -> bool:
    """Switch the repository to the given mainline branch."""
    try:
        repo.git.checkout(mainline)
        print_color(Colors.GREEN, f"  Switched to '{mainline}'.")
        return True
    except git.exc.GitCommandError as e:
        print_error(f"  Failed to switch {rel_path} to '{mainline}': {e}")
        return False


# =============================================================================
# USER PROMPTS
# =============================================================================


def _ask_stash_or_drop(repo_path_str: str) -> str:
    """Ask the user how to handle local changes. Returns 'stash', 'drop', or 'leave'."""
    while True:
        answer = (
            input(
                " Should local changes be stashed (s) or dropped (d) or left (l)? Please answer 's', 'd', or 'l'. Answer 'v' to inspect changes. "
            )
            .lower()
            .strip()
        )
        if answer in ("s", "stash"):
            return "stash"
        if answer in ("d", "drop"):
            return "drop"
        if answer in ("l", "leave"):
            return "leave"
        if answer in ("v", "view"):
            subprocess.run(["git", "diff", "--color=always"], cwd=repo_path_str)
            subprocess.run(
                ["git", "diff", "--staged", "--color=always"], cwd=repo_path_str
            )
            continue


def _ask_switch_branch(current: str, target: str) -> bool:
    """Ask the user whether to switch to the target branch."""
    while True:
        answer = (
            input(f"  Switch from '{current}' to default branch '{target}'? [Y/n]: ")
            .lower()
            .strip()
        )
        if answer in ("y", "yes", ""):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")


# =============================================================================
# MAIN
# =============================================================================


def main(default_yes: bool = False) -> int:
    ws_root_path = get_workspace_root()
    if ws_root_path is None:
        print_workspace_error()
        return 1

    ws_root = Path(ws_root_path)
    ws_src = ws_root / "src"

    repos = sorted(get_repos_in_workspace(str(ws_root)))
    if not repos:
        print_warn("No git repositories found in workspace src/.")
        return 0

    modified_repos: list[str] = []

    for repo_path_str in repos:
        repo_path = Path(repo_path_str)
        rel_path = str(repo_path.relative_to(ws_src))

        try:
            repo = git.Repo(repo_path_str, search_parent_directories=False)
        except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
            print_warn(f"Skipping {rel_path}: not a valid git repository.")
            continue

        repo_modified = False

        # ---- Determine current branch ----------------------------------------
        if not repo.head.is_valid():
            # Empty repo — nothing to reset
            continue

        if repo.head.is_detached:
            current_branch = None
            current_branch_display = f"detached@{repo.head.commit.hexsha[:7]}"
        else:
            current_branch = repo.head.ref.name
            current_branch_display = current_branch

        mainline = get_mainline_branch(repo)

        # ---- Handle local changes --------------------------------------------
        status = get_repo_status(repo_path, ws_src)
        has_working_tree_changes = (
            bool(status.changes_summary) or status.untracked_count > 0
        )

        if has_working_tree_changes:
            print_info(f"\n{rel_path}  ({current_branch_display})")

            # Show what changed
            for summary in status.changes_summary:
                if summary.startswith("Modified:"):
                    print_color(Colors.ORANGE, f"  {summary}")
                elif summary.startswith("Deleted:"):
                    print_color(Colors.RED, f"  {summary}")
                else:
                    print_color(Colors.GREEN, f"  {summary}")
            if status.untracked_count > 0:
                shown = min(status.untracked_count, 5)
                for uf in status.untracked_files[:shown]:
                    print_color(Colors.LGRAY, f"  Untracked: {uf}")
                if status.untracked_count > shown:
                    print_color(
                        Colors.LGRAY,
                        f"  ... and {status.untracked_count - shown} more untracked file(s).",
                    )

            if default_yes:
                action = "stash"
                print_color(Colors.ORANGE, "  Stashing changes (--yes).")
            else:
                action = _ask_stash_or_drop(repo_path_str)

            if action == "stash":
                if _stash_changes(repo, rel_path):
                    repo_modified = True
            elif action == "drop":
                if _drop_changes(repo, rel_path):
                    repo_modified = True
            else:
                # "leave": keep everything as-is, skip this repo entirely
                print_color(Colors.LGRAY, "  Left as-is.")
                if repo_modified:
                    modified_repos.append(repo_path_str)
                continue

        # ---- Handle non-default branch ---------------------------------------
        if current_branch != mainline:
            if not has_working_tree_changes:
                # Print header if we haven't already
                print_info(f"\n{rel_path}  ({current_branch_display})")

            print_warn(f"  Not on default branch '{mainline}'.")

            if default_yes:
                switch = True
                print_color(Colors.GREEN, f"  Switching to '{mainline}' (--yes).")
            else:
                switch = _ask_switch_branch(current_branch_display, mainline)

            if switch:
                if _switch_to_mainline(repo, mainline, rel_path):
                    repo_modified = True

        if repo_modified:
            modified_repos.append(repo_path_str)

    # ---- Rebuild affected packages ------------------------------------------
    print()
    if not modified_repos:
        print_success(
            "All repositories are already clean and on their default branches."
        )
        return 0

    packages_to_build: list[str] = []
    for repo_path_str in modified_repos:
        packages_to_build.extend(find_packages_in_directory(repo_path_str))

    if not packages_to_build:
        print_warn("No packages found in modified repositories — nothing to rebuild.")
        return 0

    pkg_list = ", ".join(packages_to_build)
    print_info(f"Rebuilding {len(packages_to_build)} package(s): {pkg_list}")
    return build_packages(ws_root_path, packages_to_build)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description=(
                "Reset all git repositories in the workspace to a clean state. "
                "Offers to stash or drop local changes and to switch back to the "
                "default branch. Rebuilds all affected packages afterwards."
            )
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help=(
                "Non-interactive mode: drop all local changes and switch every "
                "repository back to its default branch without asking."
            ),
        )
        argcomplete.autocomplete(parser)
        args = parser.parse_args()
        exit(main(default_yes=args.yes) or 0)
    except KeyboardInterrupt:
        print_error("\nCtrl+C received! Exiting...")
        exit(0)
