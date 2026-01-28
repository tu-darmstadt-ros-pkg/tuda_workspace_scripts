#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
Display the status of all git repositories in the workspace.

Uses the git_utils module to collect and display repository status
including uncommitted changes, unpushed commits, and branch information.
"""
from pathlib import Path

from tuda_workspace_scripts.git_utils import (
    collect_repos,
    print_repo_status,
)
from tuda_workspace_scripts.print import (
    print_error,
    print_color,
    print_workspace_error,
    Colors,
)
from tuda_workspace_scripts.workspace import get_workspace_root


def main() -> int:
    """Main entry point for the status command."""
    ws_root_path = get_workspace_root()
    if ws_root_path is None:
        print_workspace_error()
        return 1

    ws_root = Path(ws_root_path)

    # Check workspace root itself if it's a git repo
    if (ws_root / ".git").is_dir():
        print_color(Colors.GREEN, f"Looking for changes in {ws_root}...")
        print_repo_status(ws_root, ws_root)

    # Scan workspace src directory
    ws_src = ws_root / "src"
    print_color(Colors.GREEN, f"Looking for changes in {ws_src}...")

    # Use helper to collect all repos
    repos = collect_repos(ws_src)
    for repo_path in sorted(repos):
        print_repo_status(repo_path, ws_src)

    return 0


if __name__ == "__main__":
    try:
        exit(main() or 0)
    except KeyboardInterrupt:
        print_error("Ctrl+C received! Exiting...")
        exit(0)
