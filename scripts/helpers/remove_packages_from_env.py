#!/usr/bin/env python3
from tuda_workspace_scripts.workspace import *
import argparse
import os


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    packages_arg = parser.add_argument(
        "packages", nargs="*", help="If specified only these packages are built."
    )
    parser.add_argument("--logs", default=False, action="store_true")
    parser.add_argument("--force", default=False, action="store_true")

    args = parser.parse_args()
    workspace_root = get_workspace_root()
    packages = args.packages or get_packages_in_workspace()
    ament_prefix_path = get_ament_prefix_path_without_packages(packages)
    if ament_prefix_path is not None:
        print(f"export AMENT_PREFIX_PATH={ament_prefix_path};")
    cmake_prefix_path = get_cmake_prefix_path_without_packages(packages)
    if cmake_prefix_path is not None:
        print(f"export CMAKE_PREFIX_PATH={cmake_prefix_path};")
