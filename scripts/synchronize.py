#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete

from ssh import RemotePCChoicesCompleter
from tuda_workspace_scripts import get_workspace_root
from tuda_workspace_scripts.workspace import PackageChoicesCompleter
from tuda_workspace_scripts.print import print_error, print_workspace_error
from tuda_workspace_scripts.synchronize import sync


if __name__ == "__main__":
    workspace_root = get_workspace_root()
    parser = argparse.ArgumentParser(
        description="Synchronize packages between local machine and remote targets."
    )

    pkg_arg = parser.add_argument(
        "packages", nargs="+", help="The packages to synchronize."
    )
    pkg_arg.completer = PackageChoicesCompleter(workspace_root)

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

    parser.add_argument(
        "--dry-run",
        default=False,
        action="store_true",
        help="Show what would be copied without actually copying.",
    )

    parser.add_argument(
        "--force",
        "-f",
        default=False,
        action="store_true",
        help="Overwrite uncommitted changes on the destination.",
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

    exit(
        sync(
            workspace_root=workspace_root,
            packages=args.packages,
            from_target=args.from_target,
            to_target=args.to_target,
            dry_run=args.dry_run,
            force=args.force,
            use_gitignore_filter=not args.no_gitignore_filter,
        )
    )
