#!/usr/bin/env python3
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
    packages_arg = parser.add_argument(
        "packages",
        nargs="*",
        help="If specified only these packages or repositories are removed.",
    )
    packages_arg.completer = CombinedPackageReposCompleter(workspace_root)
    parser.add_argument(
        "--this",
        default=False,
        action="store_true",
        help="Remove the package(s) in the current directory.",
    )

    completer = SmartCompletionFinder(parser)
    completer(parser)
    args = parser.parse_args()

    if workspace_root is None:
        print_workspace_error()
        exit(1)

    packages = args.packages or []
    if args.this:
        packages = find_packages_in_directory(os.getcwd())
        if len(packages) == 0:
            package = find_package_containing(os.getcwd())
            packages = [package] if package else []
        if len(packages) == 0:
            print_error(
                "No package found in the current directory or containing the current directory!"
            )
            exit(1)

    if len(packages) == 0:
        print_error("No packages specified for removal.")
        exit(1)

    exit(remove_packages(workspace_root, packages))
