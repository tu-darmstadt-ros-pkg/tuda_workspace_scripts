#!/usr/bin/env python3
import argcomplete
import argparse
from tuda_workspace_scripts.build import cross_compile
from tuda_workspace_scripts.print import print_workspace_error
from tuda_workspace_scripts.workspace import PackageChoicesCompleter, get_workspace_root
from os import getenv
import os.path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Builds the given packages for the given platform/architecture in a docker image."
    )
    parser.add_argument(
        "--base-image",
        help="Use the given base image instead of the default one generated based on platform and distro.",
    )
    parser.add_argument("--build-type", choices=["Debug", "RelWithDebInfo", "Release"])
    parser.add_argument(
        "--no-cache",
        default=False,
        action="store_true",
        help="Do not use the cache when building. Use with --rebuild for a clean build of the docker image.",
    )
    parser.add_argument(
        "--pull",
        default=False,
        action="store_true",
        help="Pull base image before building.",
    )
    parser.add_argument(
        "--rebuild",
        default=False,
        action="store_true",
        help="Force rebuilding the docker image.",
    )
    parser.add_argument(
        "--clean",
        default=False,
        action="store_true",
        help="Clean build folders before building.",
    )
    parser.add_argument(
        "--platform", choices=["linux/arm64", "linux/amd64"], required=True
    )
    parser.add_argument(
        "--ros-distro",
        choices=["foxy", "galactic", "humble", "iron", "jazzy", "rolling"],
        default=getenv("ROS_DISTRO"),
        help="ROS distro to use for cross-compilation. Defaults to ROS distro on host.",
    )
    workspace_path = get_workspace_root()
    parser.add_argument(
        "--output-base-dir",
        default=os.path.join(workspace_path, "cross-compile-install"),
        help="Base directory where the install output is places. It will be placed in a subdirectory based on the ROS distro and platform.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Use to specify an exact directory where the install output will be placed. Overwrites --output-base-dir.",
    )
    package_arg = parser.add_argument(
        "PACKAGE", nargs="*", help="Packages to cross-compile"
    )
    package_arg.completer = PackageChoicesCompleter(get_workspace_root())
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if workspace_path is None:
        print_workspace_error()
        exit(1)

    try:
        if not cross_compile(
            packages=args.PACKAGE,
            ros_distro=args.ros_distro,
            platform=args.platform,
            clean=args.clean,
            no_cache=args.no_cache,
            rebuild=args.rebuild,
            output_base_dir=args.output_base_dir,
            output_dir=args.output_dir,
            base_image=args.base_image,
            pull=args.pull,
        ):
            exit(1)
    except KeyboardInterrupt:
        pass
