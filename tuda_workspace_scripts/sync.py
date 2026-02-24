import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

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


@dataclass
class PackageInfo:
    """Pre-fetched info about a package (local or remote)."""

    path: Optional[Path] = None
    branch: Optional[str] = None
    dirty: Optional[bool] = None
    changed_files: List[str] = field(default_factory=list)


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


def _batch_query_remote(
    ssh_command: str, packages: List[str]
) -> Dict[str, PackageInfo]:
    """
    Resolve all packages on a remote in a single SSH call.

    For each package, fetches: path, git branch, git status (dirty files).
    Uses a delimiter-based protocol to parse the combined output.
    """
    DELIM = "---SYNC_PKG_DELIM---"
    # Build a shell script that processes each package
    # For each package:
    #   1. Resolve path via the helper script
    #   2. If path found and is a directory, get branch and dirty status
    #   3. Print delimited output
    script_parts = []
    for package in packages:
        safe_pkg = shlex.quote(package)
        script_parts.append(
            f"""
PKG_PATH=$(python3 "$TUDA_WSS_BASE_SCRIPTS/helpers/get_package_path.py" {safe_pkg} 2>/dev/null)
echo "PKG_PATH:$PKG_PATH"
if [ -n "$PKG_PATH" ] && [ -d "$PKG_PATH" ]; then
    BRANCH=$(cd "$PKG_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null)
    echo "BRANCH:$BRANCH"
    STATUS=$(cd "$PKG_PATH" && git status --porcelain -- "$PKG_PATH" 2>/dev/null)
    echo "STATUS_BEGIN"
    [ -n "$STATUS" ] && echo "$STATUS"
    echo "STATUS_END"
else
    echo "BRANCH:"
    echo "STATUS_BEGIN"
    echo "STATUS_END"
fi
echo "{DELIM}"
"""
        )

    combined_script = "\n".join(script_parts)
    remote_script = f"bash -i -c {shlex.quote(combined_script)}"

    result = _run_ssh_command(ssh_command, remote_script)
    if result is None:
        return {pkg: PackageInfo() for pkg in packages}

    # Parse output — split by delimiter, one block per package
    output = result.stdout
    blocks = output.split(DELIM)

    results: Dict[str, PackageInfo] = {}
    for i, package in enumerate(packages):
        info = PackageInfo()
        if i >= len(blocks):
            results[package] = info
            continue

        block = blocks[i]
        lines = block.strip().splitlines()

        in_status = False
        status_lines: List[str] = []

        for line in lines:
            if line.startswith("PKG_PATH:"):
                path_str = line[9:].strip()
                if path_str:
                    info.path = Path(path_str)
            elif line.startswith("BRANCH:"):
                branch_str = line[7:].strip()
                if branch_str:
                    info.branch = branch_str
            elif line == "STATUS_BEGIN":
                in_status = True
            elif line == "STATUS_END":
                in_status = False
            elif in_status and line.strip():
                status_lines.append(line)

        info.changed_files = status_lines
        info.dirty = len(status_lines) > 0 if info.path else None
        results[package] = info

    return results


def _batch_query_local(
    packages: List[str], workspace_root: str
) -> Dict[str, PackageInfo]:
    """Resolve all packages locally."""
    results: Dict[str, PackageInfo] = {}

    for package in packages:
        info = PackageInfo()
        path_str = get_package_path(package, workspace_root)
        if path_str:
            info.path = Path(path_str)
            try:
                result = subprocess.run(
                    ["git", "-C", path_str, "rev-parse", "--abbrev-ref", "HEAD"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                info.branch = result.stdout.strip() or None
            except subprocess.CalledProcessError:
                pass
            try:
                result = subprocess.run(
                    ["git", "-C", path_str, "status", "--porcelain", "--", path_str],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                lines = [l for l in result.stdout.strip().splitlines() if l]
                info.changed_files = lines
                info.dirty = len(lines) > 0
            except subprocess.CalledProcessError:
                pass
        results[package] = info

    return results


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

    source_label = from_target if from_target else "local"
    dest_label = to_target if to_target else "local"
    print_info(f"Syncing: {source_label} -> {dest_label}")

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

    # Batch-query all package info upfront (1 SSH call per remote side)
    print_info("Resolving packages...")
    if source_ssh is not None:
        source_info = _batch_query_remote(source_ssh, packages)
    else:
        source_info = _batch_query_local(packages, source_workspace)

    if dest_ssh is not None:
        dest_info = _batch_query_remote(dest_ssh, packages)
    else:
        dest_info = _batch_query_local(packages, dest_workspace)

    failed: List[str] = []
    skipped: List[str] = []
    succeeded: List[str] = []

    for package in packages:
        print_header(f"Syncing: {package}")

        src = source_info[package]
        dst = dest_info[package]

        if src.path is None:
            print_error(f"Package '{package}' not found on source.")
            failed.append(package)
            continue

        if dst.path is None:
            # Package does not exist on destination — derive path from source
            source_src = Path(source_workspace) / "src"
            try:
                source_rel = src.path.relative_to(source_src)
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
            dest_pkg_path = dst.path

            # Check if source and destination are on the same branch
            if src.branch and dst.branch and src.branch != dst.branch:
                print_warn(
                    f"Branch mismatch: source is on '{src.branch}', "
                    f"destination is on '{dst.branch}'. "
                    f"This may transfer more files than necessary."
                )
                if not confirm(f"Continue syncing '{package}'?"):
                    print_info(f"Skipping {package}.")
                    skipped.append(package)
                    continue

            # Check for uncommitted changes on destination
            if dst.dirty is None:
                print_error(
                    f"Could not check git status for '{package}' on destination. Skipping."
                )
                failed.append(package)
                continue

            if dst.dirty:
                print_warn(
                    f"Package '{package}' has uncommitted changes on the destination:"
                )
                _print_changed_files(dst.changed_files)

                if not confirm(f"Overwrite changes in '{package}' on destination?"):
                    print_info(f"Skipping {package}.")
                    skipped.append(package)
                    continue

        # Build and run rsync
        rsync_cmd = _build_rsync_command(
            source_path=str(src.path),
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
