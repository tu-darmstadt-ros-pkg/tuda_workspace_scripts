#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
Remove specified packages and their repositories from the workspace.
Prompts for confirmation if other packages are present in the same repository.
Before removal, checks if the repository is dirty (uncommitted changes, unpushed commits, stash entries).
"""
from tuda_workspace_scripts.remove import remove_packages
from tuda_workspace_scripts.print import print_error, print_workspace_error
from tuda_workspace_scripts.workspace import (
    find_package_containing,
    find_packages_in_directory,
    get_workspace_root,
    CombinedPackageReposCompleter,
)
from tuda_workspace_scripts.completion import SmartCompletionFinder
import argparse
import os


if __name__ == "__main__":
    workspace_root = get_workspace_root()
    parser = argparse.ArgumentParser(
        prog="remove", description="Remove packages and their repositories."
    )
    items_arg = parser.add_argument(
        "items",
        nargs="*",
        help="If specified only these packages or repositories are removed.",
    )
    items_arg.completer = CombinedPackageReposCompleter(workspace_root)
    parser.add_argument(
        "--this",
        default=False,
        action="store_true",
        help="Remove the package(s) in the current directory.",
    )
    parser.add_argument(
        "--no-fetch",
        default=False,
        action="store_true",
        help="Do not fetch remotes before checking mainline merge state.",
    )

    completer = SmartCompletionFinder(parser)
    completer(parser)
    args = parser.parse_args()

    if workspace_root is None:
        print_workspace_error()
        exit(1)

    if args.this and args.items:
        parser.error("--this cannot be combined with positional items")

    if args.this:
        items = find_packages_in_directory(os.getcwd())
        if len(items) == 0:
            package = find_package_containing(os.getcwd())
            items = [package] if package else []
        if len(items) == 0:
            print_error(
                "No package found in the current directory or containing the current directory!"
            )
            exit(1)
    else:
        items = args.items

    if len(items) == 0:
        print_error("No packages or repositories specified for removal.")
        exit(1)

    exit(remove_packages(workspace_root, items, fetch_remotes=not args.no_fetch))
