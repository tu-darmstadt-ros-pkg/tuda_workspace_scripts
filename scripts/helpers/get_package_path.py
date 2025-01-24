#!/usr/bin/env python3
from ament_index_python.packages import get_package_share_directory
from tuda_workspace_scripts.workspace import get_package_path, get_workspace_root
from os.path import realpath
import sys

if __name__ == "__main__":
    try:
        path = get_package_share_directory(sys.argv[1])
    except:
        path = None

    # Check if path is in workspace, if so return path to source directory 
    workspace_root = get_workspace_root()
    if path is None or realpath(path).startswith(realpath(workspace_root)):
        path = get_package_path(sys.argv[1])

    print(path or None)
