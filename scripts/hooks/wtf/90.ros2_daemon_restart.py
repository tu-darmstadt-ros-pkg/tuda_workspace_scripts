#!/usr/bin/env python3
import psutil

from tuda_workspace_scripts.print import *
from ros2cli.node.daemon import is_daemon_running, spawn_daemon, shutdown_daemon
import asyncio

daemon_timeout = 5  # seconds


def find_ros2_daemon() -> int:
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if cmdline and "ros2-daemon" in cmdline:
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def kill_ros2_daemon() -> bool:
    ros2_daemon_pid = find_ros2_daemon()
    if ros2_daemon_pid:
        try:
            proc = psutil.Process(ros2_daemon_pid)
            proc.kill()
            # Make sure the process has terminated and xmlrpc server port is released
            proc.wait(timeout=1)
            print_info(f"Killed ROS2 daemon with PID {ros2_daemon_pid}.")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print_error(f"Failed to kill ROS2 daemon with PID {ros2_daemon_pid}: {e}")
            return False
    else:
        print_info("No ROS2 daemon process found to kill.")
        return True


async def restart_ros2_daemon() -> int:
    try:
        async with asyncio.timeout(daemon_timeout):
            successful_shutdown = await graceful_daemon_shutdown()
    except TimeoutError:
        successful_shutdown = False

    if not successful_shutdown:
        print_info("ROS2 daemon not responding to shutdown request. Killing it.")
        if not kill_ros2_daemon():
            print_error("Failed to kill ROS2 daemon")
            return 0

    print_info("Spawning ROS2 daemon.")
    if not spawn_daemon(args=[], timeout=daemon_timeout):
        print_error("Failed to start ROS2 daemon")
        return 0

    print_info("Successfully spawned ROS2 daemon.")
    # The ros2 daemon not running could have actually been an issue for commands such as ros2 topic/service/action/...
    return 1


async def graceful_daemon_shutdown() -> bool:
    print_info("Checking status of ROS2 daemon.")
    is_running = await asyncio.to_thread(is_daemon_running, args=[])
    if is_running:
        print_info("ROS2 daemon is running. Attempting graceful shutdown.")
        if not shutdown_daemon(args=[], timeout=daemon_timeout):
            print_warn("Graceful shutdown failed")
            return False
        else:
            print_info("ROS2 daemon shut down gracefully.")
            return True

    print_info("ROS2 daemon is not running.")
    return True  # Daemon was not running, so consider it a success


def fix() -> int:
    print_header("Checking ROS2 daemon")
    while True:
        try:
            return asyncio.run(restart_ros2_daemon())

        except KeyboardInterrupt:
            print_warn(
                "Canceling the restart of the ROS2 daemon might lead to further issues."
            )
            if confirm("Stop anyway?"):
                raise

            print_info("Okay. Trying again.")
