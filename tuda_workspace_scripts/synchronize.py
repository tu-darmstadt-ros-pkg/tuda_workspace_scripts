import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from .print import (
    Colors,
    confirm,
    print_color,
    print_error,
    print_header,
    print_info,
    print_success,
    print_warn,
)
from .robots import RemotePC, load_robots
from .workspace import get_package_path


def _resolve_target(target_name: str) -> RemotePC:
    """
    Resolve a target name to a RemotePC using the robots.yaml configuration.

    The target can be:
      - A robot name (e.g. "athena") — only if the robot has exactly one PC.
      - A PC name (e.g. "athena-main") — looked up across all robots.

    Raises ValueError if the target cannot be resolved.
    """
    robots = load_robots()

    if target_name in robots:
        robot = robots[target_name]
        if len(robot.remote_pcs) == 1:
            return next(iter(robot.remote_pcs.values()))
        raise ValueError(
            f"Robot '{target_name}' has multiple PCs: {list(robot.remote_pcs.keys())}. "
            f"Please specify a PC name directly."
        )

    for robot in robots.values():
        if target_name in robot.remote_pcs:
            return robot.remote_pcs[target_name]

    raise ValueError(f"Target '{target_name}' not found in robot configuration.")


def _build_ssh_command(pc: RemotePC) -> str:
    """Build an SSH command string from a RemotePC."""
    return f"ssh -p {pc.port} {pc.user}@{pc.hostname}"


def _run_ssh_command(
    ssh_command: str, remote_script: str
) -> Optional[subprocess.CompletedProcess]:
    """
    Run a command on a remote machine via SSH.
    Returns the CompletedProcess on success, None on failure.
    """
    cmd_base = shlex.split(ssh_command)
    full_command = cmd_base + [remote_script]
    try:
        return subprocess.run(
            full_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print_error(f"SSH command failed: {e.stderr.strip()}")
        return None


def _get_package_path_on_remote(ssh_command: str, package: str) -> Optional[Path]:
    """Resolve a package path on a remote machine via SSH."""
    safe_package = shlex.quote(package)
    remote_script = f"bash -i -c 'python3 $TUDA_WSS_BASE_SCRIPTS/helpers/get_package_path.py {safe_package}'"
    result = _run_ssh_command(ssh_command, remote_script)
    if result is None:
        return None
    output_lines = result.stdout.strip().splitlines()
    if not output_lines:
        return None
    return Path(output_lines[-1].strip())


def _get_workspace_on_remote(ssh_command: str) -> Optional[str]:
    """Get the workspace root path on a remote machine via SSH."""
    result = _run_ssh_command(
        ssh_command, "bash -ic 'echo $(_tuda_wss_get_workspace_root)'"
    )
    if result is None:
        return None
    output_lines = result.stdout.strip().splitlines()
    if not output_lines:
        return None
    remote_ws = output_lines[-1].strip()
    if "/" not in remote_ws:
        return None
    return remote_ws


def _get_uncommitted_changes_on_remote(
    ssh_command: str, package_path: str
) -> Tuple[Optional[bool], List[str]]:
    """
    Check if a package directory on a remote has uncommitted changes.

    Uses git status --porcelain scoped to the package directory.
    Returns (is_dirty, changed_files) where is_dirty is None on error.
    """
    safe_path = shlex.quote(package_path)
    remote_script = f"cd {safe_path} && git status --porcelain -- {safe_path}"
    result = _run_ssh_command(ssh_command, remote_script)
    if result is None:
        return None, []
    lines = [line for line in result.stdout.strip().splitlines() if line]
    return len(lines) > 0, lines


def _get_uncommitted_changes_locally(
    package_path: str,
) -> Tuple[Optional[bool], List[str]]:
    """
    Check if a local package directory has uncommitted changes.

    Returns (is_dirty, changed_files) where is_dirty is None on error.
    """
    try:
        result = subprocess.run(
            ["git", "-C", package_path, "status", "--porcelain", "--", package_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        lines = [line for line in result.stdout.strip().splitlines() if line]
        return len(lines) > 0, lines
    except subprocess.CalledProcessError:
        return None, []


def _get_git_branch_on_remote(ssh_command: str, package_path: str) -> Optional[str]:
    """Get the current git branch for a package directory on a remote machine."""
    safe_path = shlex.quote(package_path)
    result = _run_ssh_command(
        ssh_command, f"cd {safe_path} && git rev-parse --abbrev-ref HEAD"
    )
    if result is None:
        return None
    output = result.stdout.strip()
    return output if output else None


def _get_git_branch_locally(package_path: str) -> Optional[str]:
    """Get the current git branch for a local package directory."""
    try:
        result = subprocess.run(
            ["git", "-C", package_path, "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        output = result.stdout.strip()
        return output if output else None
    except subprocess.CalledProcessError:
        return None


def _print_changed_files(changed_files: List[str]) -> None:
    """Print a list of changed files from git status --porcelain output."""
    for line in changed_files:
        print_color(Colors.ORANGE, f"  {line}")


def _build_rsync_command(
    source_path: str,
    dest_path: str,
    source_pc: Optional[RemotePC],
    dest_pc: Optional[RemotePC],
    dry_run: bool,
    use_gitignore_filter: bool,
) -> List[str]:
    """
    Build an rsync command for syncing a package directory.

    Exactly one of source_pc/dest_pc may be non-None (local-to-remote or remote-to-local).
    Both None means local-to-local.
    """
    # Order matters: rsync processes rules first-match-wins,
    # so --include=.gitignore must come before --exclude=.*
    cmd = [
        "rsync",
        "-avz",
        "--delete",
        "--include=.gitignore",
        "--exclude=.*",
    ]

    if use_gitignore_filter:
        cmd.append("--filter=:- .gitignore")

    if dry_run:
        cmd.append("--dry-run")

    remote_pc = source_pc or dest_pc
    if remote_pc is not None:
        cmd.extend(["-e", f"ssh -p {remote_pc.port}"])

    if source_pc is not None:
        rsync_source = f"{source_pc.user}@{source_pc.hostname}:{source_path}/"
    else:
        rsync_source = f"{source_path}/"

    if dest_pc is not None:
        rsync_dest = f"{dest_pc.user}@{dest_pc.hostname}:{dest_path}/"
    else:
        rsync_dest = f"{dest_path}/"

    cmd.append(rsync_source)
    cmd.append(rsync_dest)
    return cmd


def sync(
    workspace_root: str,
    packages: List[str],
    from_target: Optional[str],
    to_target: Optional[str],
    dry_run: bool = False,
    use_gitignore_filter: bool = True,
) -> int:
    """
    Synchronize packages between local machine and remote targets using rsync.

    At least one of from_target/to_target must be set. The omitted one defaults
    to the local machine. Returns 0 on full success, 1 if any package failed.
    """
    # Resolve endpoints
    source_pc: Optional[RemotePC] = None
    dest_pc: Optional[RemotePC] = None
    source_ssh: Optional[str] = None
    dest_ssh: Optional[str] = None

    try:
        if from_target is not None:
            source_pc = _resolve_target(from_target)
            source_ssh = _build_ssh_command(source_pc)
        if to_target is not None:
            dest_pc = _resolve_target(to_target)
            dest_ssh = _build_ssh_command(dest_pc)
    except ValueError as e:
        print_error(str(e))
        return 1

    if source_pc is not None and dest_pc is not None:
        print_error(
            "Remote-to-remote sync is not supported. One side must be the local machine."
        )
        return 1

    # Resolve workspace roots
    if source_ssh is not None:
        print_info(f"Resolving workspace on source ({from_target})...")
        source_workspace = _get_workspace_on_remote(source_ssh)
        if source_workspace is None:
            print_error("Could not determine workspace root on source.")
            return 1
    else:
        source_workspace = workspace_root

    if dest_ssh is not None:
        print_info(f"Resolving workspace on destination ({to_target})...")
        dest_workspace = _get_workspace_on_remote(dest_ssh)
        if dest_workspace is None:
            print_error("Could not determine workspace root on destination.")
            return 1
    else:
        dest_workspace = workspace_root

    # Deduplicate packages while preserving order
    packages = list(dict.fromkeys(packages))

    failed: List[str] = []
    skipped: List[str] = []
    succeeded: List[str] = []

    for package in packages:
        print_header(f"Syncing: {package}")

        # Resolve source package path
        if source_ssh is not None:
            source_pkg_path = _get_package_path_on_remote(source_ssh, package)
        else:
            result = get_package_path(package, source_workspace)
            source_pkg_path = Path(result) if result else None

        if source_pkg_path is None:
            print_error(f"Package '{package}' not found on source.")
            failed.append(package)
            continue

        # Resolve destination package path
        if dest_ssh is not None:
            dest_pkg_path = _get_package_path_on_remote(dest_ssh, package)
        else:
            result = get_package_path(package, dest_workspace)
            dest_pkg_path = Path(result) if result else None

        if dest_pkg_path is None:
            # Package does not exist on destination — derive path from source
            source_src = Path(source_workspace) / "src"
            try:
                source_rel = source_pkg_path.relative_to(source_src)
            except ValueError:
                print_error(
                    f"Package '{package}' is not inside src/ on the source. "
                    f"Cannot derive destination path."
                )
                failed.append(package)
                continue

            dest_pkg_path = Path(dest_workspace) / "src" / source_rel
            print_warn(
                f"Package '{package}' does not exist on destination. "
                f"It will be created at: {dest_pkg_path}"
            )
            if not dry_run and not confirm(f"Create '{package}' on destination?"):
                print_info(f"Skipping {package}.")
                skipped.append(package)
                continue
        else:
            # Check if source and destination are on the same branch
            if source_ssh is not None:
                source_branch = _get_git_branch_on_remote(
                    source_ssh, str(source_pkg_path)
                )
            else:
                source_branch = _get_git_branch_locally(str(source_pkg_path))

            if dest_ssh is not None:
                dest_branch = _get_git_branch_on_remote(dest_ssh, str(dest_pkg_path))
            else:
                dest_branch = _get_git_branch_locally(str(dest_pkg_path))

            if source_branch and dest_branch and source_branch != dest_branch:
                print_warn(
                    f"Branch mismatch: source is on '{source_branch}', "
                    f"destination is on '{dest_branch}'. "
                    f"This may transfer more files than necessary."
                )
                if not confirm(f"Continue syncing '{package}'?"):
                    print_info(f"Skipping {package}.")
                    skipped.append(package)
                    continue

            # Package exists on destination — check for uncommitted changes
            if dest_ssh is not None:
                has_changes, changed_files = _get_uncommitted_changes_on_remote(
                    dest_ssh, str(dest_pkg_path)
                )
            else:
                has_changes, changed_files = _get_uncommitted_changes_locally(
                    str(dest_pkg_path)
                )

            if has_changes is None:
                print_error(
                    f"Could not check git status for '{package}' on destination. Skipping."
                )
                failed.append(package)
                continue

            if has_changes:
                print_warn(
                    f"Package '{package}' has uncommitted changes on the destination:"
                )
                _print_changed_files(changed_files)

                if not confirm(f"Overwrite changes in '{package}' on destination?"):
                    print_info(f"Skipping {package}.")
                    skipped.append(package)
                    continue

        # Build and run rsync
        rsync_cmd = _build_rsync_command(
            source_path=str(source_pkg_path),
            dest_path=str(dest_pkg_path),
            source_pc=source_pc,
            dest_pc=dest_pc,
            dry_run=dry_run,
            use_gitignore_filter=use_gitignore_filter,
        )

        print_info(f"Running: {' '.join(rsync_cmd)}")
        try:
            subprocess.run(rsync_cmd, check=True)
            if dry_run:
                print_info(f"[DRY RUN] Would sync '{package}'.")
            else:
                print_success(f"Successfully synced '{package}'.")
            succeeded.append(package)
        except subprocess.CalledProcessError as e:
            print_error(f"rsync failed for '{package}': {e}")
            failed.append(package)

    # Summary
    print("")
    if succeeded:
        action = "would be synced" if dry_run else "synced"
        print_success(f"Packages {action}: {', '.join(succeeded)}")
    if skipped:
        print_info(f"Packages skipped: {', '.join(skipped)}")
    if failed:
        print_error(f"Packages failed: {', '.join(failed)}")

    return 1 if failed else 0
