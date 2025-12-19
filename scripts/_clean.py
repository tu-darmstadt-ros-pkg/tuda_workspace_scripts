#!/usr/bin/env python3
from tuda_workspace_scripts.build import clean_logs, clean_packages
from tuda_workspace_scripts.print import print_error, print_workspace_error
from tuda_workspace_scripts.workspace import (
    get_workspace_root,
    PackageChoicesCompleter,
    find_package_containing,
    find_packages_in_directory,
)
from helpers.remove_packages_from_env import *
import argcomplete
import argparse
import os


if __name__ == "__main__":
    workspace_root = get_workspace_root()
    parser = argparse.ArgumentParser(
        prog="clean", description="Clean the workspace or specific packages."
    )
    packages_arg = parser.add_argument(
        "packages", nargs="*", help="If specified only these packages are cleaned."
    )
    packages_arg.completer = PackageChoicesCompleter(workspace_root)
    parser.add_argument(
        "--this",
        default=False,
        action="store_true",
        help="Clean the package(s) in the current directory.",
    )
    parser.add_argument("--force", default=False, action="store_true")
    parser.add_argument(
        "--logs",
        default=False,
        action="store_true",
        help="If specified only the logs are cleaned",
    )

    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if workspace_root is None:
        print_workspace_error()
        exit(1)

    packages = args.packages or []
    if args.this:
        packages = find_packages_in_directory(os.getcwd())
        if len(packages) == 0:
            # No packages in the current folder but maybe the current folder is in a package
            package = find_package_containing(os.getcwd())
            packages = [package] if package else []
        if len(packages) == 0:
            print_error("No package found in the current directory!")
            exit(1)

    if args.logs:
        exit(clean_logs(workspace_root, packages, force=args.force))
    else:
        exit(clean_packages(workspace_root, packages, force=args.force))
