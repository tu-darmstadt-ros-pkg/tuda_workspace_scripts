#!/usr/bin/env python3
from tuda_workspace_scripts.print import print_header, print_info, print_warn
from tuda_workspace_scripts.workspace import (
    get_workspace_root,
    get_packages_in_workspace,
)
import os
import shutil


def fix() -> tuple[int, int]:
    print_header("Checking for stale build/install artifacts")
    workspace_root = get_workspace_root()
    if workspace_root is None:
        print_info("No workspace found.")
        return 0, 0

    src_packages = set(get_packages_in_workspace(workspace_root))
    stale_packages = set()

    for folder in ("build", "install"):
        folder_path = os.path.join(workspace_root, folder)
        if not os.path.exists(folder_path):
            continue
        for entry in os.listdir(folder_path):
            entry_path = os.path.join(folder_path, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry not in src_packages:
                stale_packages.add(entry)

    if not stale_packages:
        print_info("All good.")
        return 0, 0

    print_warn(
        f"Found {len(stale_packages)} stale package artifact(s) with no corresponding source package:"
    )
    for pkg in sorted(stale_packages):
        locations = []
        for folder in ("build", "install"):
            if os.path.isdir(os.path.join(workspace_root, folder, pkg)):
                locations.append(folder)
        print_warn(f"  - {pkg} ({', '.join(locations)})")

    print_info("Stale artifacts can cause issues. Removing them.")
    count_removed = 0
    for pkg in sorted(stale_packages):
        for folder in ("build", "install"):
            pkg_path = os.path.join(workspace_root, folder, pkg)
            if os.path.isdir(pkg_path):
                shutil.rmtree(pkg_path)
                count_removed += 1
    print_info(f"Removed {count_removed} stale artifact folder(s).")
    return len(stale_packages), count_removed


if __name__ == "__main__":
    fix()
