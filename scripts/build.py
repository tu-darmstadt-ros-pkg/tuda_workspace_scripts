#!/usr/bin/env python3
from tuda_workspace_scripts.build import build_packages
from tuda_workspace_scripts.print import print_error, print_workspace_error
from tuda_workspace_scripts.workspace import *
from tuda_workspace_scripts.completion import *
from _clean import clean_packages
import argcomplete
import argparse
import os


if __name__ == "__main__":
    workspace_root = get_workspace_root()
    parser = argparse.ArgumentParser()
    packages_arg = parser.add_argument(
        "packages", nargs="*", help="If specified only these packages are built."
    )
    packages_arg.completer = PackageChoicesCompleter(workspace_root)
    parser.add_argument(
        "--this",
        default=False,
        action="store_true",
        help="Build the package(s) in the current directory.",
    )
    parser.add_argument(
        "--build-tests",
        default=False,
        action="store_true",
        help="Enable building tests.",
    )
    build_arg = parser.add_argument(
        "--build-type",
        default=None,
        nargs=1,
        help="The cmake build type.",
    )
    build_arg.completer = PrefixFilteredChoicesCompleter(
        ("Debug", "RelWithDebInfo", "Release")
    )
    parser.add_argument(
        "--no-deps",
        default=False,
        action="store_true",
        help="Build only the specified packages, not their dependencies.",
    )
    parser.add_argument(
        "--continue-on-error",
        default=False,
        action="store_true",
        help="Continue building other packages if a package build fails.",
    )
    parser.add_argument(
        "--clean", default=False, action="store_true", help="Clean before building."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        default=False,
        action="store_true",
        help="Print verbose output.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        default=False,
        action="store_true",
        help="Automatically answer yes to all questions.",
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
            # No packages in the current folder but maybe the current folder is in a package
            package = find_package_containing(os.getcwd())
            packages = [package] if package else []
        if len(packages) == 0:
            print_error("No package found in the current directory or containing the current directory!")
            exit(1)

    if args.clean and not clean_packages(workspace_root, packages, force=args.yes):
        exit(1)
    try:
        exit(
            build_packages(
                workspace_root,
                packages,
                build_type=args.build_type[0] if args.build_type else None,
                no_deps=args.no_deps,
                continue_on_error=args.continue_on_error,
                build_tests=args.build_tests,
                verbose=args.verbose,
            )
        )
    except KeyboardInterrupt:
        print_error("Build interrupted!")
        exit(1)
