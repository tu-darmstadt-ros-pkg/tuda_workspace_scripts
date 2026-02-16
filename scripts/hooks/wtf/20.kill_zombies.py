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


def _kill_processes(processes: list[psutil.Process], label: str) -> int:
    """Kill processes with escalation: SIGTERM -> wait -> SIGKILL -> wait."""
    if not processes:
        return 0
    count_killed = 0
    for p in processes:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            count_killed += 1
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
                count_killed += 1
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
                parents.append(psutil.Process(ppid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return parents


def _is_zombie_node(cmdline: list[str]) -> bool:
    """Heuristic check whether a command line belongs to a ROS node."""
    score = 1 if len(cmdline) > 5 else 0
    for item in cmdline:
        if item.startswith("/tmp/launch_params_"):
            return True
        if item.startswith("__node:="):
            score += 1
    return score >= 2


def _get_process_label(p: psutil.Process) -> str:
    """Return a human-readable label for a process."""
    name = p.info.get("name", "")
    cmdline = p.info.get("cmdline") or []
    try:
        if name.startswith("python") and cmdline:
            name = cmdline[0].split("/")[-1]
        if name.startswith("gz") and len(cmdline) > 1:
            name += " " + cmdline[1]
        if name.startswith("ros2") and len(cmdline) > 2:
            name += " " + " ".join(cmdline[1:3])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return name


def fix() -> int:
    print_header("Checking for zombies")
    gz_processes = []
    node_processes = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "status", "ppid"]):
        try:
            if p.status() in _ZOMBIE_STATUSES:
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        cmdline = p.info.get("cmdline") or []
        exe = cmdline[0] if cmdline else ""

        if p.info["name"] == "ruby" and exe.startswith("gz sim"):
            gz_processes.append(p)
        elif exe.startswith(_ROS_PREFIXES) and _is_zombie_node(cmdline):
            node_processes.append(p)
        elif (
            "python" in exe
            and len(cmdline) > 1
            and cmdline[1].startswith(_ROS_PREFIXES)
            and _is_zombie_node(cmdline)
        ):
            node_processes.append(p)

    count_killed = 0
    if gz_processes:
        if not confirm(
            "Found gazebo processes. Are you expecting gazebo to be running?"
        ):
            print_error("Found gazebo zombies.")
            killed = _kill_with_parents(gz_processes, "gazebo processes")
            print_info(f"Killed {killed} gazebo zombies.")
            count_killed += killed
    if node_processes:
        if not confirm("Found ROS nodes. Are you expecting nodes to be running?"):
            print_error("Found node zombies.")
            for p in node_processes:
                print(f"  Node: {_get_process_label(p)}")
            count_killed += _kill_with_parents(node_processes, "node processes")
    if not gz_processes and not node_processes:
        print_info("No zombies found.")
    return count_killed


if __name__ == "__main__":
    fix()
