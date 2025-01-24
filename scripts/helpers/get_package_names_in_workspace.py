#!/usr/bin/env python3
from ament_index_python.packages import get_packages_with_prefixes
from tuda_workspace_scripts.workspace import get_packages_in_workspace

if __name__ == "__main__":
    pkgs = set(get_packages_with_prefixes().keys())
    pkgs.update(get_packages_in_workspace())
    print("\n".join(pkgs))
