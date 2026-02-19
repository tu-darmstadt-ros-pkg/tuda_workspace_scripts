#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete

from ssh import RemotePCChoicesCompleter
from tuda_workspace_scripts import get_workspace_root
from tuda_workspace_scripts.workspace import (
    CombinedPackageReposCompleter,
)
from tuda_workspace_scripts.print import print_error, print_workspace_error
from tuda_workspace_scripts.synchronize import synchronize


if __name__ == "__main__":
    workspace_root = get_workspace_root()
    parser = argparse.ArgumentParser()

    target_arg = parser.add_argument(
        "target", nargs=1, help="The robot or pc to synchronize to."
    )
    target_arg.completer = RemotePCChoicesCompleter()

    pkg_arg = parser.add_argument(
        "packages", nargs="*", help="The packages to synchronize."
    )
    pkg_arg.completer = CombinedPackageReposCompleter(workspace_root)
    parser.add_argument(
        "--fetch",
        default=False,
        action="store_true",
        help="Fetch remotes before checking mainline merge state.",
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    target = args.target
    items = args.packages

    if workspace_root is None:
        print_workspace_error()
        exit(1)

    if len(items) == 0:
        print_error("No packages or repositories specified for removal.")
        exit(1)


    exit(synchronize(workspace_root, items, "root@localhost", 2222, fetch_remotes=args.fetch))
