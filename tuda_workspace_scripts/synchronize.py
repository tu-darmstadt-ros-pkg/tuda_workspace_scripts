import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import shlex

from .build import clean_packages
from .print import Colors, confirm, print_error, print_info, print_warn, print_color
from .workspace import find_packages_in_directory, get_package_path
from .robots import load_robots

try:
    import git
    from git import Repo
except ImportError:
    print_error("GitPython is required! Install using 'pip install gitpython'")
    raise


@dataclass
class RepoStatus:
    """Structured container for repository status."""

    rel_path: str
    branch: str
    is_git: bool = False

    # local changes / risks
    has_changes: bool = False
    untracked_count: int = 0
    stash_count: int = 0
    changes_summary: List[str] = field(default_factory=list)

    # only meaningful if fetch_remotes=True
    unpushed_branches: List[str] = field(default_factory=list)
    local_only_branches: List[str] = field(default_factory=list)
    deleted_upstream_branches: List[str] = field(default_factory=list)

    is_clean: bool = True


def _get_repo_root(path: Path, workspace_src: Path) -> Optional[Path]:
    """
    Return the git working tree root for `path`, but ONLY if the repo root is
    inside `workspace_src` (or equals it). Otherwise return None.

    This prevents accidentally picking up e.g. /home/user as a repo root.
    """
    workspace_src = workspace_src.resolve()
    current = path.resolve()

    # must be within ws/src
    if not current.is_relative_to(workspace_src):
        return None

    try:
        repo = Repo(current, search_parent_directories=True)
        repo_root = Path(repo.working_tree_dir).resolve()
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        return None

    # accept only if repo root is within ws/src (or equals)
    if repo_root == workspace_src or repo_root.is_relative_to(workspace_src):
        return repo_root

    return None

def _get_repo_root_on_remote(ssh_command: str, package_path: str) -> Optional[str]:
    cmd_base = shlex.split(ssh_command)
    remote_script = f"cd {package_path} && git rev-parse --show-toplevel"

    full_command = cmd_base + [remote_script]

    try:
        result = subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output_lines = result.stdout.strip().splitlines()
        if not output_lines:
            print_error(f"SSH command failed. Could not get remote repo root for package path {package_path}.")
            return None

        remote_repo_root = output_lines[-1].strip()
        return Path(remote_repo_root)

    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed. Could not get remote repo root for package path {package_path}.")
        print_error(f"Stderr: {e.stderr.strip()}")
        return None

def _get_current_branch_on_remote(ssh_command: str, package_path: str) -> Optional[str]:
    cmd_base = shlex.split(ssh_command)
    remote_script = f"cd {package_path} && git rev-parse --abbrev-ref HEAD"

    full_command = cmd_base + [remote_script]

    try:
        result = subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output_lines = result.stdout.strip().splitlines()
        if not output_lines:
            print_error(f"SSH command failed. Could not get current branch for package path {package_path}.")
            return None

        remote_branch = output_lines[-1].strip()
        return remote_branch

    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed. Could not get current branch for package path {package_path}.")
        print_error(f"Stderr: {e.stderr.strip()}")
        return None

def _get_package_path_on_remote(ssh_command: str, package: str) -> Optional[str]:
    cmd_base = shlex.split(ssh_command)
    remote_script = f"bash -i -c 'python3 $TUDA_WSS_BASE_SCRIPTS/helpers/get_package_path.py {package}'"

    full_command = cmd_base + [remote_script]

    try:
        result = subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output_lines = result.stdout.strip().splitlines()
        if not output_lines:
            print_error(f"SSH command failed. Could not get remote package path for package {package}.")
            return None

        remote_package_path = output_lines[-1].strip()
        return Path(remote_package_path)

    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed. Could not get remote package path for package {package}.")
        print_error(f"Stderr: {e.stderr.strip()}")
        return None

def _collect_worktree_changes(repo: Repo) -> Tuple[List[str], int, int]:
    """
    Return (changes_summary, modified_count, untracked_count) using
    `git status --porcelain` (robust, fast, works even if HEAD is unborn).
    """
    try:
        out = repo.git.status("--porcelain=v1").splitlines()
    except git.exc.GitCommandError:
        out = []

    changes_summary: List[str] = []
    modified_count = 0
    untracked_count = 0

    for line in out:
        if not line:
            continue

        # Untracked: "?? path"
        if line.startswith("?? "):
            untracked_count += 1
            continue

        # Format: XY <path> (or rename "R  old -> new")
        xy = line[:2]
        rest = line[3:] if len(line) > 3 else ""

        modified_count += 1

        # very simple labels (keep it readable)
        if "R" in xy and "->" in rest:
            changes_summary.append(f"Renamed: {rest}")
        elif "D" in xy:
            changes_summary.append(f"Deleted: {rest}")
        elif "A" in xy:
            changes_summary.append(f"Added: {rest}")
        else:
            changes_summary.append(f"Modified: {rest}")

    return changes_summary, modified_count, untracked_count


def _collect_repo_status(
    repo_path: Path, workspace_root: Path, fetch: bool
) -> RepoStatus:
    rel_path = str(repo_path.relative_to(workspace_root))

    try:
        repo = Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return RepoStatus(rel_path=rel_path, branch="unknown", is_git=False)

    # Branch info
    try:
        if repo.head.is_detached:
            branch_name = f"detached ({repo.head.commit.hexsha[:7]})"
        else:
            branch_name = repo.active_branch.name
    except Exception:
        branch_name = "unknown"

    # local working tree status
    changes_summary, mod_count, untracked_count = _collect_worktree_changes(repo)

    # stashes
    stash_count = 0
    try:
        stash_out = repo.git.stash("list")
        stash_count = len(stash_out.splitlines()) if stash_out else 0
    except git.exc.GitCommandError:
        stash_count = 0

    # remote-related checks only if fetch=True (avoid lying when refs are stale)
    unpushed: List[str] = []
    local_only: List[str] = []
    deleted_upstream: List[str] = []

    if fetch:
        for remote in repo.remotes:
            try:
                remote.fetch(prune=True)
            except git.exc.GitCommandError as e:
                print_warn(f"Fetch failed for {remote.name} in {rel_path}: {e}")

        for branch in repo.branches:
            tracking = branch.tracking_branch()
            if not tracking:
                local_only.append(branch.name)
                continue

            # tracking ref might still not exist locally; treat as deleted/unknown
            try:
                # "git show-ref --verify refs/remotes/..."
                repo.git.show_ref(
                    "--verify",
                    f"refs/remotes/{tracking.remote_head}",
                    with_exceptions=True,
                )
            except Exception:
                # safer: just label as deleted/unknown if tracking cannot be verified after fetch
                deleted_upstream.append(branch.name)
                continue

            try:
                commits_ahead = int(
                    repo.git.rev_list("--count", f"{tracking.name}..{branch.name}")
                )
                if commits_ahead > 0:
                    unpushed.append(branch.name)
            except Exception:
                # ignore; keep script simple
                pass

    has_changes = (
        (mod_count > 0)
        or (untracked_count > 0)
        or (stash_count > 0)
        or bool(unpushed)
        or bool(local_only)
        or bool(deleted_upstream)
    )

    return RepoStatus(
        rel_path=rel_path,
        branch=branch_name,
        is_git=True,
        has_changes=has_changes,
        untracked_count=untracked_count,
        stash_count=stash_count,
        unpushed_branches=unpushed,
        local_only_branches=local_only,
        deleted_upstream_branches=deleted_upstream,
        changes_summary=changes_summary,
        is_clean=not has_changes,
    )


def _print_status_report(status: RepoStatus, packages: List[str], fetched: bool):
    print_info(f"Repo: {status.rel_path} ({status.branch})")

    if not status.is_git:
        print_warn("  [!] Not a git repository")
        return

    labels: List[str] = []
    if status.is_clean:
        labels.append("Clean")
    else:
        if status.changes_summary or status.untracked_count:
            labels.append("Working tree dirty")
        if status.stash_count:
            labels.append("Stashed changes")
        if fetched:
            if status.unpushed_branches:
                labels.append("Unpushed commits")
            if status.local_only_branches:
                labels.append("Local-only branches")
            if status.deleted_upstream_branches:
                labels.append("Upstream missing")
        else:
            if (
                status.unpushed_branches
                or status.local_only_branches
                or status.deleted_upstream_branches
            ):
                # shouldn't happen, but keep logic consistent
                labels.append("Remote status unknown")

    print_info(f"Status: {', '.join(labels)}")

    if status.has_changes:
        if fetched:
            for b in status.unpushed_branches:
                print_color(Colors.RED, f"  Unpushed: {b}")
            for b in status.local_only_branches:
                print_color(Colors.LRED, f"  No Upstream: {b}")
            for b in status.deleted_upstream_branches:
                print_color(Colors.YELLOW, f"  Upstream Missing: {b}")
        else:
            # gentle hint
            print_color(
                Colors.LGRAY,
                "  (Hint: run with fetch_remotes=True to check upstream state)",
            )

        for change in status.changes_summary[:50]:
            print_color(Colors.ORANGE, f"  {change}")
        if len(status.changes_summary) > 50:
            print_color(
                Colors.LGRAY, f"  ... +{len(status.changes_summary) - 50} more changes"
            )

        if status.untracked_count:
            print_color(Colors.LGRAY, f"  {status.untracked_count} untracked files")
        if status.stash_count:
            print_color(Colors.LGRAY, f"  {status.stash_count} stash entries")

    print("Packages in this repo:")
    for p in sorted(packages):
        print(f"  - {p}")

def _create_git_diff_on_remote(ssh_command: str, repo_path: str) -> int:
    cmd_base = shlex.split(ssh_command)
    remote_script = f"cd {repo_path} && git diff > changes.diff && git diff"

    full_command = cmd_base + [remote_script]

    try:
        out = subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        out_lines = out.stdout.strip().splitlines()
        if not out_lines:
            print_info(f"No changes found in {repo_path}")
            return 1

        diff = out_lines[-1].strip()
        if not diff:
            print_info(f"No changes found in {repo_path}")
            return 1
        return 0

    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed. Could not create git diff for repo path {repo_path}.")
        print_error(f"Stderr: {e.stderr.strip()}")
        return 1

def _delete_git_diff_on_remote(ssh_command: str, repo_path: str) -> None:
    cmd_base = shlex.split(ssh_command)
    remote_script = f"cd {repo_path} && rm -f changes.diff"

    full_command = cmd_base + [remote_script]

    try:
        subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed. Could not delete git diff for repo path {repo_path}.")
        print_error(f"Stderr: {e.stderr.strip()}")


def _get_workspace_on_remote(ssh_command: str) -> Optional[str]:
    cmd_base = shlex.split(ssh_command)
    remote_script = "bash -ic 'echo $(_tuda_wss_get_workspace_root)'"

    full_command = cmd_base + [remote_script]
    print_info(f"Getting remote workspace root via SSH...")

    try:
        result = subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output_lines = result.stdout.strip().splitlines()
        if not output_lines:
            print_error(f"SSH command failed. Could not get workspace root via SSH.")
            return None

        remote_ws = output_lines[-1].strip()
        if "/" not in remote_ws:
            print_error(f"SSH command failed. Could not get workspace root via SSH.")
            return None
        print_info(f"Remote workspace: {remote_ws}")
        return remote_ws

    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed. Could not find the remote workspace.")
        print_error(f"Stderr: {e.stderr.strip()}")
        return None

    # cmd_base = shlex.split(ssh_command)
    # remote_script = "echo $(_tuda_wss_get_workspace_root) \n"
    #
    # print_info(f"Getting remote workspace root via SSH...")
    #
    # try:
    #     sshProcess = subprocess.Popen(
    #         cmd_base,
    #         stdin=subprocess.PIPE,
    #         stdout=subprocess.PIPE,
    #         stderr=subprocess.PIPE,
    #         universal_newlines=True,
    #         bufsize=0,
    #         text=True,
    #     )
    #
    #     sshProcess.stdin.write(remote_script)
    #     sshProcess.stdin.write("exit\n")
    #     sshProcess.stdin.close()
    #
    #     last_line = ""
    #
    #     for line in sshProcess.stdout:
    #         if not line.strip():
    #             continue
    #         if "# exit" in line:
    #             break
    #         last_line = line
    #         #print_info(line.strip())
    #
    #     remote_workspace_root = last_line.strip()
    #     # check if output is empty or invalid
    #     if not remote_workspace_root or "/" not in remote_workspace_root:
    #         print_error(f"Could not determine remote workspace root.")
    #         return None
    #     print_info(f"Remote workspace root: {remote_workspace_root}")
    #
    #     exit()
    #
    #     return remote_workspace_root
    #
    # except subprocess.CalledProcessError as e:
    #     print_error(f"SSH command failed. Could not get remote workspace root.")
    #     print_error(f"Stderr: {e.stderr.strip()}")
    #     return None


def synchronize(
    workspace_root_str: str, items: List[str], remote_name: str, port: int, fetch_remotes: bool = False
) -> int:
    ssh_command = "ssh -p {} {}".format(port, remote_name)

    if not workspace_root_str:
        print_error("No workspace configured!")
        return 1

    workspace_root = Path(workspace_root_str).resolve()
    src_root = (workspace_root / "src").resolve()

    if not items:
        print_error("No packages specified.")
        return 1

    items = list(dict.fromkeys(items))  # deduplicate while preserving order

    repo_map: Dict[Path, List[str]] = {}
    repos_explicitly_selected: Set[Path] = set()
    missing_items: List[str] = []

    # 1) Resolve items to repos
    for item in items:
        pkg_path_str = get_package_path(item, str(workspace_root))

        if pkg_path_str:
            repo_root = _get_repo_root(Path(pkg_path_str), src_root)
            if not repo_root:
                print_error(f"Package '{item}' is not in a git repo within {src_root}.")
                return 1
            repo_map.setdefault(repo_root, [])
            if item not in repo_map[repo_root]:
                repo_map[repo_root].append(item)
            continue

        # treat as path (relative to ws or src)
        candidate_ws = workspace_root / item
        candidate_src = src_root / item

        found_path: Optional[Path] = None
        if candidate_ws.is_dir():
            found_path = candidate_ws
        elif candidate_src.is_dir():
            found_path = candidate_src

        if not found_path:
            missing_items.append(item)
            continue

        real_repo = _get_repo_root(found_path, src_root)
        if not real_repo:
            print_error(f"Path '{item}' is not a git repository inside {src_root}.")
            return 1

        repos_explicitly_selected.add(real_repo)
        repo_map.setdefault(real_repo, [])

    if missing_items:
        print_error(f"Not found: {', '.join(missing_items)}")
        return 1

    # 2) Determine final repos and packages to synchronize TODO: currently always all packages in repo, change to only requested ones?
    final_repos_to_process: List[Tuple[Path, List[str]]] = []

    for repo_root, requested_pkgs in repo_map.items():
        all_pkgs_in_repo = find_packages_in_directory(str(repo_root))

        if repo_root in repos_explicitly_selected:
            final_repos_to_process.append((repo_root, all_pkgs_in_repo))
            continue

        final_repos_to_process.append((repo_root, all_pkgs_in_repo))

    target_workspace = _get_workspace_on_remote(ssh_command)
    if not target_workspace:
        return 1

    # 3) Execute synchronization
    for repo_root, packages in final_repos_to_process:
        repo_root = repo_root.resolve()
        repo_rel = repo_root.relative_to(workspace_root)

        status = _collect_repo_status(repo_root, workspace_root, fetch_remotes)
        _print_status_report(status, packages, fetched=fetch_remotes)

        # Decide whether to warn
        has_uncommitted = bool(status.changes_summary) or status.untracked_count > 0
        has_local_work = has_uncommitted or (status.stash_count > 0)
        has_unpushed = bool(status.unpushed_branches) or bool(
            status.local_only_branches
        )

        if has_local_work or has_unpushed:
            print_error("ERROR: local repro has local work (dirty/stash/unpushed).")
            continue

        # get remote package path
        remote_package_path = _get_package_path_on_remote(ssh_command, packages[0])

        if remote_package_path is None:
            continue

        # check if package is inside the workspace on remote
        remote_ws_path = Path(target_workspace).resolve()
        if not remote_package_path.is_relative_to(remote_ws_path / "src"):
            print_error(f"Remote package path '{remote_package_path}' is not inside the remote workspace '{remote_ws_path}/src'.")
            continue

        # get current branch on remote
        remote_branch = _get_current_branch_on_remote(ssh_command, remote_package_path)
        if remote_branch is None:
            continue

        # switch to correct branch locally
        repo = Repo(repo_root)
        try:
            if repo.head.is_detached or repo.active_branch.name != remote_branch:
                print_info(f"Switching local repo '{repo_rel}' to branch '{remote_branch}'")
                repo.git.checkout(remote_branch)
        except Exception as e:
            print_error(f"Failed to switch branch in local repo '{repo_rel}': {e}")
            continue

        # get remote repo root
        remote_repo_root = _get_repo_root_on_remote(ssh_command, remote_package_path)
        if remote_repo_root is None:
            continue

        ## perform rsync from remote to local
        #remote_path = str(remote_repo_root) + "/"
        #local_path = str(repo_root) + "/"
        #print_info(f"Synchronizing repository '{repo_rel}' from remote...")
        #rsync_command = f"rsync -a --delete --exclude '.git' -e 'ssh -p {port}' {remote_name}:{remote_path} {local_path}"
        #try:
        #    subprocess.run(shlex.split(rsync_command), check=True)
        #    print_info(f"Synchronization of '{repo_rel}' completed successfully.")
        #except subprocess.CalledProcessError as e:
        #    print_error(f"Synchronization of '{repo_rel}' failed: {e}")
        #    continue

        # create git diff on remote and check if there are changes
        if _create_git_diff_on_remote(ssh_command, str(remote_repo_root)):
            continue

        # get git diff file from remote
        remote_diff_path = str(remote_repo_root / "changes.diff")
        local_diff_path = str(workspace_root / "temp_changes.diff")
        print_info(f"Retrieving changes diff from remote for repository '{repo_rel}'...")
        scp_command = f"scp -P {port} {remote_name}:{remote_diff_path} {local_diff_path}"
        try:
            subprocess.run(shlex.split(scp_command), check=True)
            print_info(f"Retrieval of changes diff for '{repo_rel}' completed successfully.")
        except subprocess.CalledProcessError as e:
            print_error(f"Retrieval of changes diff for '{repo_rel}' failed: {e}")
            _delete_git_diff_on_remote(ssh_command, str(remote_repo_root))
            continue

        # apply git diff locally
        print_info(f"Applying changes diff to local repository '{repo_rel}'...")
        try:
            with open(local_diff_path, 'r') as diff_file:
                subprocess.run(['git', '-C', str(repo_root), 'apply'], stdin=diff_file, check=True)
            print_info(f"Applied changes diff to '{repo_rel}' successfully.")
            os.remove(local_diff_path)
        except subprocess.CalledProcessError as e:
            print_error(f"Applying changes diff to '{repo_rel}' failed: {e}")
            _delete_git_diff_on_remote(ssh_command, str(remote_repo_root))
            os.remove(local_diff_path)
            continue

        # delete git diff on remote
        _delete_git_diff_on_remote(ssh_command, str(remote_repo_root))


    return 0
