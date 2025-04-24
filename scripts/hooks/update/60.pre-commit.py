#!/usr/bin/env python3
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.workspace import get_workspace_root
import os
import subprocess
from pathlib import Path

"""
This scripts makes sure that pre-commit hooks are installed in all git repositories (if they exist).
"""


def is_git_repo(path):
    return (path / ".git").is_dir()


def has_pre_commit_config(path):
    return (path / ".pre-commit-config.yaml").is_file()


def is_pre_commit_installed(path):
    # Check for the presence of .git/hooks/pre-commit installed by pre-commit
    hook_path = path / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    try:
        content = hook_path.read_text()
        return "pre-commit" in content
    except Exception:
        return False


def install_pre_commit(path):
    try:
        subprocess.run(
            ["pre-commit", "install"],
            cwd=str(path),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print_info(f"Installed pre-commit hook in: {path}")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to install pre-commit in {path}:\n{e.stderr.decode()}")
        return False


def update(**_) -> bool:
    print_header("Updating pre-commit hooks")
    success = True
    count = 0
    base_path = get_workspace_root()
    if base_path is None:
        print_workspace_error()
        return False
    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        if is_git_repo(root_path):
            if has_pre_commit_config(root_path):
                if not is_pre_commit_installed(root_path):
                    success &= install_pre_commit(root_path)
                    count = count + 1 if success else count
    if count > 0:
        print_info(f"Installed pre-commit hooks in {count} repositories.")
    elif count == 0:
        print_info("No pre-commit hooks to install.")
    return success
