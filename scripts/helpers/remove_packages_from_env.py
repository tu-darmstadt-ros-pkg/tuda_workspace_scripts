#!/usr/bin/env python3
"""Emit shell `export` statements that drop cleaned packages from the env.

`clean.sh` evaluates this script's stdout so that a clean also removes the
affected packages from the current shell's AMENT_PREFIX_PATH / CMAKE_PREFIX_PATH.
The accepted arguments mirror `_clean.py` so the same command line resolves to
the same set of packages.
"""
from tuda_workspace_scripts.workspace import *
import argparse
import os


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "packages", nargs="*", help="If specified only these packages are cleaned."
    )
    parser.add_argument("--this", default=False, action="store_true")
    parser.add_argument("--logs", default=False, action="store_true")
    parser.add_argument("--force", default=False, action="store_true")
    args = parser.parse_args()

    # Cleaning only the logs leaves packages installed, so the environment must
    # not change.
    if args.logs:
        exit(0)

    workspace_root = get_workspace_root()
    if workspace_root is None:
        # _clean.py reports the missing-workspace error; nothing to unset here.
        exit(0)

    if args.this:
        packages = find_packages_in_or_containing_directory(os.getcwd())
        if not packages:
            # No package here; _clean.py reports the error.
            exit(0)
    else:
        packages = args.packages

    if packages:
        ament_prefix_path = get_ament_prefix_path_without_packages(packages)
        cmake_prefix_path = get_cmake_prefix_path_without_packages(packages)
    else:
        # Full clean: drop everything provided by this workspace.
        ament_prefix_path = get_ament_prefix_path_without_workspace(workspace_root)
        cmake_prefix_path = get_cmake_prefix_path_without_workspace(workspace_root)

    if ament_prefix_path is not None:
        print(f"export AMENT_PREFIX_PATH={ament_prefix_path};")
    if cmake_prefix_path is not None:
        print(f"export CMAKE_PREFIX_PATH={cmake_prefix_path};")
