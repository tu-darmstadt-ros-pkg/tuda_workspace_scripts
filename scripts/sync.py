#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import os

import argcomplete

from ssh import RemotePCChoicesCompleter
from tuda_workspace_scripts import get_workspace_root
from tuda_workspace_scripts.workspace import (
    PackageChoicesCompleter,
    PackagePathCompleter,
    find_package_containing,
    find_packages_in_directory,
)
from tuda_workspace_scripts.print import print_error, print_workspace_error
from tuda_workspace_scripts.sync import sync


if __name__ == "__main__":
    workspace_root = get_workspace_root()
    parser = argparse.ArgumentParser(
        description="Synchronize packages between local machine and remote targets. "
        "Uses rsync with --delete, so files on the destination that do not exist "
        "on the source will be removed. Use --dry-run to preview changes.",
    )

    pkg_arg = parser.add_argument(
        "packages", nargs="*", help="The packages to synchronize."
    )
    pkg_arg.completer = PackageChoicesCompleter(workspace_root)

    parser.add_argument(
        "--this",
        default=False,
        action="store_true",
        help="Sync the package(s) in the current directory.",
    )

    from_arg = parser.add_argument(
        "--from",
        dest="from_target",
        default=None,
        help="Source target (robot PC name from robots.yaml). Defaults to local machine if omitted.",
    )
    from_arg.completer = RemotePCChoicesCompleter()

    to_arg = parser.add_argument(
        "--to",
        dest="to_target",
        default=None,
        help="Destination target (robot PC name from robots.yaml). Defaults to local machine if omitted.",
    )
    to_arg.completer = RemotePCChoicesCompleter()

    path_arg = parser.add_argument(
        "--path",
        default=None,
        help="Sync only a specific file or folder within a package, "
        "given as a relative path from the package root (e.g. 'src/module.py' or 'config/').",
    )
    path_arg.completer = PackagePathCompleter(workspace_root)

    parser.add_argument(
        "--dry-run",
        default=False,
        action="store_true",
        help="Show what would be copied without actually copying.",
    )

    parser.add_argument(
        "--no-gitignore-filter",
        default=False,
        action="store_true",
        help="Do not exclude .gitignore'd files from sync.",
    )

    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if args.from_target is None and args.to_target is None:
        print_error("At least one of --from or --to must be specified.")
        exit(1)

    if workspace_root is None:
        print_workspace_error()
        exit(1)

    packages = args.packages or []
    if args.this:
        this_packages = find_packages_in_directory(os.getcwd())
        if not this_packages:
            package = find_package_containing(os.getcwd())
            this_packages = [package] if package else []
        if not this_packages:
            print_error(
                "No package found in the current directory or containing the current directory!"
            )
            exit(1)
        for pkg in this_packages:
            if pkg not in packages:
                packages.append(pkg)
    if not packages:
        print_error("No packages specified. Use package names or --this.")
        exit(1)

    if args.path is not None and len(packages) != 1:
        print_error(
            f"--path can only be used with a single package, "
            f"but {len(packages)} were resolved: {', '.join(packages)}"
        )
        exit(1)

    exit(
        sync(
            workspace_root=workspace_root,
            packages=packages,
            from_target=args.from_target,
            to_target=args.to_target,
            dry_run=args.dry_run,
            use_gitignore_filter=not args.no_gitignore_filter,
            subpath=args.path,
        )
    )
