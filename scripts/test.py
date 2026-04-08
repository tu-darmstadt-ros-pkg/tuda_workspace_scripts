#!/usr/bin/env python3
from tuda_workspace_scripts.build import (
    build_packages,
    clean_packages,
    clean_test_results,
)
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.workspace import *
import argcomplete
import argparse
import os
import subprocess
import sys


def main():
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
        help="Test the packages in the current directory.",
    )
    parser.add_argument(
        "--memory-check",
        default=False,
        action="store_true",
        help="Check for memory issues during test execution using asan.",
    )
    parser.add_argument(
        "--thread-check",
        default=False,
        action="store_true",
        help="Check for data race issues during test execution using tsan.",
    )
    parser.add_argument(
        "--clean", default=False, action="store_true", help="Clean before building."
    )
    parser.add_argument(
        "--yes",
        "-y",
        default=False,
        action="store_true",
        help="Automatically answer yes to all questions.",
    )
    parser.add_argument(
        "--list-tests",
        "-l",
        default=False,
        action="store_true",
        help="List the tests instead of running them.",
    )
    parser.add_argument(
        "--filter",
        "-k",
        type=str,
        help="Only run tests matching the given pattern (ctest -R, pytest -k).",
    )

    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if workspace_root is None:
        print_workspace_error()
        exit()

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

    build_folder = "build"
    install_folder = "install"
    mixin = []
    if args.memory_check and args.thread_check:
        print_error("Memory and thread check cannot be enabled at the same time!")
        exit(1)
    elif args.memory_check:
        # Apply workaround for asan issue in rcutils
        asan_options = os.environ.get("ASAN_OPTIONS", "")
        if len(asan_options) > 0:
            asan_options += ":"
        os.environ["ASAN_OPTIONS"] = (
            asan_options + "new_delete_type_mismatch=0:verify_asan_link_order=0"
        )
        mixin.append("asan-gcc")
        build_folder = "build/asan"
        install_folder = "install/asan"
    elif args.thread_check:
        mixin.append("tsan")
        build_folder = "build/tsan"
        install_folder = "install/tsan"

    os.chdir(workspace_root)
    if args.clean and not clean_packages(
        workspace_root,
        packages,
        force=args.yes,
        build_base=build_folder,
        install_base=install_folder,
    ):
        sys.exit(1)
    print_info(">>> Building packages")
    returncode = build_packages(
        workspace_root,
        packages=packages if len(packages) > 0 else None,
        mixin=mixin,
        build_tests=True,
        build_base=build_folder,
        install_base=install_folder,
    )
    if returncode != 0:
        print_error(">>> Failed to build packages")
        exit(returncode)

    print_info(">>> Running tests")
    colcon_test_args = []
    if build_folder is not None:
        colcon_test_args.extend(["--build-base", build_folder])
    if install_folder is not None:
        colcon_test_args.extend(["--install-base", install_folder])
    if len(packages) > 0:
        colcon_test_args.extend(["--packages-select"] + packages)

    if args.list_tests:
        colcon_test_args.extend(["--ctest-args", " -N"])
        colcon_test_args.extend(["--pytest-args", " --collect-only"])
        colcon_test_args.extend(["--event-handlers", "console_direct+"])
    elif args.filter:
        colcon_test_args.extend(["--ctest-args", f" -R {args.filter}"])
        colcon_test_args.extend(["--pytest-args", f" -k {args.filter}"])

    print_info(">>> Cleaning old test results")
    clean_test_results(workspace_root, packages, build_folder)

    colcon_command = (
        f". {install_folder}/setup.sh && colcon test {' '.join(colcon_test_args)}"
    )
    print_info(f">>> Command: {colcon_command}")
    command = subprocess.run(
        colcon_command,
        stdout=sys.stdout,
        stderr=sys.stderr,
        shell=True,
    )
    returncode = command.returncode

    build_folder = build_folder or "build"
    if not args.list_tests:
        if len(packages) > 0:
            for package in packages:
                print_info(f">>> {package}")
                command = subprocess.run(
                    f"colcon test-result --verbose --test-result-base {build_folder}/{package}",
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    shell=True,
                )
                returncode |= command.returncode
        else:
            command = subprocess.run(
                f"colcon test-result --verbose --test-result-base {build_folder}",
                stdout=sys.stdout,
                stderr=sys.stderr,
                shell=True,
            )
            returncode |= command.returncode

    sys.exit(returncode)


if __name__ == "__main__":
    main()
