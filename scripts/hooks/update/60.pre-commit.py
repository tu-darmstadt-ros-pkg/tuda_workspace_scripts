#!/usr/bin/env python3
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.workspace import get_workspace_root
import os
import subprocess
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

"""
This script installs and autoupdates pre-commit hooks in all git repositories
that contain a `.pre-commit-config.yaml` file.
"""


def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def has_pre_commit_config(path: Path) -> bool:
    return (path / ".pre-commit-config.yaml").is_file()


def is_pre_commit_installed(path: Path) -> bool:
    hook_path = path / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    try:
        return "pre-commit" in hook_path.read_text()
    except Exception:
        return False


def run_pre_commit_cmd(path: Path, args: list[str], label: str) -> bool:
    try:
        subprocess.run(
            ["pre-commit"] + args,
            cwd=str(path),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print_info(f"{label} in {path.name}")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"{label} failed in {path.name}:\n{e.stderr.decode()}")
        return False


def ensure_pre_commit_available():
    if shutil.which("pre-commit") is not None:
        return True

    print_info("'pre-commit' not found. Installing via apt...")

    try:
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "pre-commit"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to install 'pre-commit' via apt:\n{e.stderr.decode()}")
        return False

    if shutil.which("pre-commit") is None:
        print_error("'pre-commit' installation completed but still not in PATH.")
        return False

    return True


def collect_precommit_repos(base_path: Path) -> list[Path]:
    repos = []
    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        if is_git_repo(root_path) and has_pre_commit_config(root_path):
            repos.append(root_path)
            if ".git" in dirs:
                dirs.remove(".git")
    return repos


def update(**_) -> bool:
    print_header("Installing & Updating Pre-commit Hooks")
    base_path = get_workspace_root()
    if base_path is None:
        print_workspace_error()
        return False
    if not ensure_pre_commit_available():
        print_error(
            "Failed to ensure 'pre-commit' is available. Cannot install pre-commit hooks."
        )
        return False

    repos = collect_precommit_repos(base_path)

    installed_count = 0
    updated_count = 0
    success = True

    # First: install hooks sequentially
    for repo in repos:
        if not is_pre_commit_installed(repo):
            if run_pre_commit_cmd(repo, ["install"], "Installing pre-commit"):
                installed_count += 1
            else:
                success = False

    # Then: update hooks in parallel
    print_header("Running autoupdate in parallel")
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(
                run_pre_commit_cmd, repo, ["autoupdate"], "Autoupdating pre-commit"
            ): repo
            for repo in repos
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                result = future.result()
                if result:
                    updated_count += 1
                else:
                    success = False
            except Exception as e:
                print_error(f"Exception in autoupdate for {repo}: {e}")
                success = False

    print_info(
        f"Installed {installed_count} and updated {updated_count} pre-commit hooks."
    )
    return success
