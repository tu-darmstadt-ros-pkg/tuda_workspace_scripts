#!/usr/bin/env python3
"""Clean up tmux sessions left behind by a crashed hector_launch_manager.

The launch manager runs every component in a tmux session named
'<group>__<sanitized_namespace>_<manager_name>' and kills that session on clean
shutdown, so a session without a live manager means the manager crashed or was
killed. Its panes keep components alive and poison the next run.

Runs after '20.kill_zombies', so a manager killed there is already gone by the
time the sessions are scanned and both are cleaned up in a single wtf run.

Known limits, none of which can be resolved from the command line alone:
- A hostname changed since the manager started makes its session look unclaimed.
- A manager inside a container that shares the tmux socket but not the PID
  namespace is invisible here, so all of its sessions look unclaimed.
- A manager started with a non-default --group is not scanned at all. This only
  leaves its session behind, which the next wtf run does not fix either.
"""
import socket

import libtmux
import libtmux.exc
import psutil
from tuda_workspace_scripts.print import (
    confirm,
    print_header,
    print_info,
    print_warn,
)

_SESSION_PREFIX = "launch_manager__"
_MANAGER_PROCESS_NAME = "launch_manager"
_DEFAULT_GROUP = "launch_manager"
_ZOMBIE_STATUSES = {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
_MAX_LISTED_SESSIONS = 10


def _sanitize_ros_name(name: str) -> str:
    """Mirror of hector_launch_manager's sanitize_name.

    Every character that is not an ASCII alphanumeric or '_' becomes '_', an
    empty result becomes '_' and a leading digit is prefixed with 'n'. The ASCII
    restriction matches the byte-wise std::isalnum on the C++ side.
    """
    sanitized = "".join(c if c.isascii() and c.isalnum() else "_" for c in name)
    if not sanitized:
        return "_"
    if sanitized[0].isdigit():
        return "n" + sanitized
    return sanitized


def _tmux_session_name(name: str) -> str:
    """Apply the normalization tmux performs on a session name.

    '.' and ':' are target syntax separators, so tmux stores them as '_'. The
    name a manager asked for is therefore not necessarily the name it got, e.g.
    a manager named after an FQDN host.
    """
    return name.replace(".", "_").replace(":", "_")


def _option_value(cmdline: list[str], option: str) -> str | None:
    """Value of a '--<option> <value>' or '--<option>=<value>' pair.

    The last occurrence wins, matching how the manager's option parser resolves
    duplicates.
    """
    value = None
    flag = f"--{option}"
    for i, token in enumerate(cmdline):
        if token == flag:
            if i + 1 < len(cmdline):
                value = cmdline[i + 1]
        elif token.startswith(f"{flag}="):
            value = token[len(flag) + 1 :]
    return value


def _namespace_from_cmdline(cmdline: list[str]) -> str:
    """The ROS namespace of a node, taken from the last '__ns:=' remapping.

    rclcpp has no namespace environment variable and ros2 launch injects the
    remapping into the child's arguments, so the command line is authoritative.
    """
    namespace = "/"
    for token in cmdline:
        if token.startswith("__ns:="):
            namespace = token[len("__ns:=") :]
    if not namespace.startswith("/"):
        namespace = "/" + namespace
    return namespace


def _session_name_for_manager(cmdline: list[str]) -> str | None:
    """The tmux session name a running launch manager created.

    None when the command line is empty and nothing can be reconstructed. Only
    the namespace is sanitized; group and name are used verbatim.
    """
    if not cmdline:
        return None
    group = _option_value(cmdline, "group") or _DEFAULT_GROUP
    name = _option_value(cmdline, "name") or socket.gethostname()
    namespace = _namespace_from_cmdline(cmdline)
    if namespace != "/":
        launcher = _sanitize_ros_name(namespace[1:]) + "_" + name
    else:
        launcher = name
    return _tmux_session_name(f"{group}__{launcher}")


def _claimed_session_names() -> set[str] | None:
    """Session names claimed by live launch managers.

    None when a live manager's command line could not be read: ownership is then
    unknown and no session may be killed. process_iter reports an inaccessible
    field as None rather than raising, so that is the same empty command line.
    """
    claimed = set()
    for p in psutil.process_iter(["name", "cmdline", "status"]):
        if p.info["name"] != _MANAGER_PROCESS_NAME:
            continue
        if p.info["status"] in _ZOMBIE_STATUSES:
            # A zombie manages nothing, its session is a leftover.
            continue
        name = _session_name_for_manager(p.info["cmdline"] or [])
        if name is None:
            return None
        claimed.add(name)
    return claimed


def _select_leftover_sessions(sessions, claimed: set[str]) -> list:
    """Detached launch manager sessions with no live owner."""
    leftovers = []
    for session in sessions:
        name = session.name or ""
        if not name.startswith(_SESSION_PREFIX) or name in claimed:
            continue
        # Compared against "0" so an unknown attachment state counts as
        # attached and the session is left alone.
        if session.session_attached == "0":
            leftovers.append(session)
    return leftovers


def _kill_sessions(sessions: list) -> int:
    """Kill sessions, returning how many were actually killed."""
    count_killed = 0
    for session in sessions:
        try:
            session.kill()
            count_killed += 1
        except libtmux.exc.LibTmuxException as e:
            # The premise is crashed processes, so a session can disappear
            # between listing and killing.
            print_warn(f"Failed to kill session {session.name}: {e}")
    return count_killed


def _print_sessions(sessions: list) -> None:
    """Print a bounded sample of sessions."""
    print_info("Found leftover launch manager sessions:")
    for session in sessions[:_MAX_LISTED_SESSIONS]:
        print(f"  Session: {session.name}")
    remaining = len(sessions) - _MAX_LISTED_SESSIONS
    if remaining > 0:
        print(f"  ... and {remaining} more sessions")


def fix() -> tuple[int, int]:
    print_header("Checking for leftover launch manager sessions")
    claimed = _claimed_session_names()
    if claimed is None:
        print_warn(
            "Could not read the command line of a running launch manager, "
            "so its sessions can not be identified. Skipping session cleanup."
        )
        return 0, 0
    sessions = _select_leftover_sessions(libtmux.Server().sessions, claimed)
    if not sessions:
        print_info("No leftover launch manager sessions found.")
        return 0, 0
    _print_sessions(sessions)
    if confirm("Are you expecting these launch managers to be running?"):
        return 0, 0
    killed = _kill_sessions(sessions)
    print_info(f"Killed {killed}/{len(sessions)} leftover sessions.")
    return 1, 1 if killed == len(sessions) else 0


if __name__ == "__main__":
    fix()
