#!/usr/bin/env python3
import psutil
from tuda_workspace_scripts.print import (
    confirm,
    print_error,
    print_header,
    print_info,
    print_warn,
)
from tuda_workspace_scripts.workspace import get_workspace_root

_ZOMBIE_STATUSES = {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
_ROS_PREFIXES = (
    "/opt/hector/",
    "/opt/ros/",
    get_workspace_root().rstrip("/") + "/install/",
)
_MAX_LISTED_NODES = 10
# Matched exactly rather than by a 'gz' prefix, which would also catch gzip.
_GZ_PROCESS_NAMES = frozenset({"gzserver", "gzclient"})
# Names a process is reparented to when its original (shell) parent dies. A
# user-started launch keeps its interactive shell as parent instead.
_REPARENT_TARGETS = {"systemd", "init"}


def _kill_processes(processes: list[psutil.Process], label: str) -> int:
    """Kill processes with escalation: SIGTERM -> wait -> SIGKILL -> wait."""
    if not processes:
        return 0
    count_killed = 0
    for p in processes:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(processes, timeout=3)
    count_killed += len(gone)
    if alive:
        print_warn(
            f"{len(alive)} {label} did not respond to SIGTERM, sending SIGKILL..."
        )
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        gone, alive = psutil.wait_procs(alive, timeout=3)
        count_killed += len(gone)
        if alive:
            pids = ", ".join(str(p.pid) for p in alive)
            print_error(f"Failed to kill {len(alive)} {label}: {pids}")
    return count_killed


def _kill_with_parents(processes: list[psutil.Process], label: str) -> int:
    """Kill parent processes first to prevent respawning, then kill children."""
    parents = _collect_parent_processes(processes)
    if parents:
        print_info("Killing parent processes first to prevent respawning...")
        for p in parents:
            try:
                print(f"  Parent: PID {p.pid} ({p.name()})")
            except psutil.NoSuchProcess:
                pass
        _kill_processes(parents, f"{label} parent processes")
    return _kill_processes(processes, label)


def _collect_parent_processes(
    processes: list[psutil.Process],
) -> list[psutil.Process]:
    """Collect unique parent processes, excluding init (PID 1) and self."""
    own_pid = psutil.Process().pid
    seen_pids = {p.pid for p in processes} | {1, own_pid}
    parents = []
    for p in processes:
        try:
            ppid = p.ppid()
            if ppid not in seen_pids:
                seen_pids.add(ppid)
                parent = psutil.Process(ppid)
                if parent.name() != "ros2":
                    # Only kill whitelisted process parents, e.g. ros2 launch
                    # Blindly killing them could hit important processes like systemd as orphans are reparented
                    continue
                parents.append(parent)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return parents


def _is_ros2_launch(cmdline: list[str]) -> bool:
    """Check whether a command line is a 'ros2 launch' invocation."""
    for arg, following in zip(cmdline, cmdline[1:]):
        if (arg == "ros2" or arg.endswith("/ros2")) and following == "launch":
            return True
    return False


def _launch_label(cmdline: list[str]) -> str:
    """Return 'ros2 launch <package> <launch_file>' for a launch command line."""
    rest = cmdline[cmdline.index("launch") + 1 :]
    positional = []
    skip_next = False
    for tok in rest:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            skip_next = "=" not in tok  # option may consume the following value
            continue
        positional.append(tok)
        if len(positional) == 2:
            break
    return " ".join(["ros2", "launch", *positional])


def _cgroup_of(pid: int) -> str:
    """Return the cgroup path of a process, or an empty string if unreadable."""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            return f.read().strip()
    except OSError:
        return ""


def _is_systemd_unit(p: psutil.Process) -> bool:
    """Whether a process was started by systemd as a service.

    A service has no controlling terminal and sits under systemd, so it looks
    exactly like an orphan. On a robot the nodes and the launch manager run as
    units, and killing them would take down a healthy system.

    The leaf of the cgroup path distinguishes the two: a unit ends in
    '<name>.service', while an interactive session ends in '<name>.scope' even
    though its path passes through 'user@<uid>.service'.
    """
    leaf = _cgroup_of(p.pid).rsplit("/", 1)[-1]
    return leaf.endswith(".service")


def _is_orphaned(p: psutil.Process) -> bool:
    """Whether a process is a reparented leftover.

    A user-driven ROS process keeps whatever started it, an interactive shell
    or a launcher, as its parent. Once that dies the process is reparented to
    init/systemd, the same way a zombie is, and nothing is left to shut it down.

    A controlling terminal is not evidence to the contrary. A leftover keeps the
    pty it inherited, so gzserver outliving its launcher still reports the
    shell's terminal. Processes systemd started on purpose look like orphans too
    and are excluded by _is_systemd_unit instead.
    """
    if _is_systemd_unit(p):
        return False
    try:
        parent = p.parent()
        if parent is None:
            return True
        return parent.pid <= 1 or parent.name() in _REPARENT_TARGETS
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True


def _is_gazebo(name: str, exe: str) -> bool:
    """Whether a process belongs to a gazebo simulation.

    The server and client are standalone binaries, shipped both by gazebo
    itself and as ros_gz_sim wrappers under a ROS prefix, so they must be
    recognised before the ROS prefix would claim them as a node. 'gz sim' runs
    through a ruby wrapper and reports ruby as its name instead.
    """
    if name in _GZ_PROCESS_NAMES:
        return True
    return name == "ruby" and exe.startswith("gz sim")


def _classify_process(p: psutil.Process) -> str | None:
    """Classify a process as 'gz', 'node' or None.

    A process is a cleanup candidate only when it is both a ROS/gazebo process
    and orphaned: reparented to init/systemd after the shell that started it
    died, the same way a zombie is. A live, user-driven process keeps its shell
    as parent and is deliberately left alone.
    """
    name = p.info.get("name") or ""
    cmdline = p.info.get("cmdline") or []
    exe = cmdline[0] if cmdline else ""
    if _is_gazebo(name, exe):
        kind = "gz"
    elif exe.startswith(_ROS_PREFIXES) or (
        "python" in exe and len(cmdline) > 1 and cmdline[1].startswith(_ROS_PREFIXES)
    ):
        # Direct node/tool under a ROS install, or a python-wrapped one such as
        # `ros2 launch` (interpreter is the exe, ros2 is argv[1]).
        kind = "node"
    else:
        return None
    return kind if _is_orphaned(p) else None


def _get_process_label(p: psutil.Process) -> str:
    """Return a human-readable label for a process."""
    name = p.info.get("name", "")
    cmdline = p.info.get("cmdline") or []
    try:
        if _is_ros2_launch(cmdline):
            return _launch_label(cmdline)
        if name.startswith("python") and cmdline:
            name = cmdline[0].split("/")[-1]
        if name == "gz" and len(cmdline) > 1:
            # The subcommand carries the meaning, e.g. 'gz sim'. Other gz*
            # binaries name themselves fully and only gain noise from it.
            name += " " + cmdline[1]
        if name.startswith("ros2") and len(cmdline) > 2:
            name += " " + " ".join(cmdline[1:3])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return name


def _print_node_processes(processes: list[psutil.Process]) -> None:
    """Print a bounded sample of node processes."""
    print_info("Found ROS nodes:")
    for p in processes[:_MAX_LISTED_NODES]:
        print(f"  Node: {_get_process_label(p)}")
    remaining = len(processes) - _MAX_LISTED_NODES
    if remaining > 0:
        print(f"  ... and {remaining} more nodes")


def fix() -> tuple[int, int]:
    print_header("Checking for zombies")
    gz_processes = []
    node_processes = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "status", "ppid"]):
        try:
            if p.status() in _ZOMBIE_STATUSES:
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        kind = _classify_process(p)
        if kind == "gz":
            gz_processes.append(p)
        elif kind == "node":
            node_processes.append(p)

    issues_found = 0
    issues_resolved = 0
    if gz_processes:
        if not confirm(
            "Found gazebo processes. Are you expecting gazebo to be running?"
        ):
            issues_found += 1
            print_error("Found gazebo zombies.")
            killed = _kill_with_parents(gz_processes, "gazebo processes")
            print_info(f"Killed {killed}/{len(gz_processes)} gazebo zombies.")
            issues_resolved += 1 if killed == len(gz_processes) else 0
    if node_processes:
        _print_node_processes(node_processes)
        if not confirm("Are you expecting nodes to be running?"):
            issues_found += 1
            print_error("Found node zombies.")
            killed = _kill_with_parents(node_processes, "node processes")
            print_info(f"Killed {killed}/{len(node_processes)} node zombies.")
            issues_resolved += 1 if killed == len(node_processes) else 0
    if not gz_processes and not node_processes:
        print_info("No zombies found.")
    return issues_found, issues_resolved


if __name__ == "__main__":
    fix()
