#!/usr/bin/env python3
from tuda_workspace_scripts.print import print_header, print_info
from tuda_workspace_scripts.workspace import get_workspace_root
import os


def symlink_target_valid(link_path: str, visited=None) -> bool:
    if visited is None:
        visited = set()
    if os.path.isfile(link_path) or os.path.isdir(link_path):
        return True
    if os.path.islink(link_path):
        if link_path in visited:
            return False  # Circular symlink detected
        visited.add(link_path)
        target_path = os.readlink(link_path)
        return symlink_target_valid(target_path, visited)
    return False


def fix() -> int:
    print_header("Checking for unclean links")
    workspace_root = get_workspace_root()
    install_folder = os.path.join(workspace_root, "install")
    if not os.path.exists(install_folder):
        print_info("No install folder found.")
        return 0
    cleaned = False
    for root, dirs, files in os.walk(install_folder):
        for d in dirs:
            link_path = os.path.join(root, d)
            if os.path.islink(link_path) and not symlink_target_valid(link_path):
                os.unlink(link_path)
                cleaned = True
        for f in files:
            link_path = os.path.join(root, f)
            if os.path.islink(link_path) and not symlink_target_valid(link_path):
                os.unlink(link_path)
                cleaned = True
    if cleaned:
        print_info("Found some broken links in the install space and removed them.")
        return 1
    print_info("All good.")
    return 0


if __name__ == "__main__":
    fix()
