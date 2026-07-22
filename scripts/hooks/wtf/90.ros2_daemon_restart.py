#!/usr/bin/env python3
import psutil

from tuda_workspace_scripts.print import *
from ros2cli.node.daemon import is_daemon_running, spawn_daemon, shutdown_daemon
import os


def find_ros2_daemon() -> int:
    print_info("ROS2 daemon not responding to shutdown request. Killing it.")
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if cmdline and "ros2-daemon" in cmdline:
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def kill_ros2_daemon() -> int:
    ros2_daemon_pid = find_ros2_daemon()
    if ros2_daemon_pid:
        try:
            proc = psutil.Process(ros2_daemon_pid)
            proc.kill()
            # Make sure the process has terminated and xmlrpc server port is released
            proc.wait(timeout=1)
            print_info(f"Killed ROS2 daemon with PID {ros2_daemon_pid}.")
            return 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print_error(f"Failed to kill ROS2 daemon with PID {ros2_daemon_pid}: {e}")
            return 0
    else:
        print_info("No ROS2 daemon process found to kill.")
        return 1


def fix() -> int:
    print_header("Checking ROS2 daemon")
    while True:
        try:
            if is_daemon_running(args=[]):
                print_info("ROS2 daemon is running. Restarting it just to be safe.")
                if not shutdown_daemon(args=[], timeout=5):
                    if not kill_ros2_daemon():
                        print_error("Failed to shutdown ROS2 daemon")
                        return 0
                if not spawn_daemon(args=[], timeout=10):
                    print_error("Failed to restart ROS2 daemon after stopping it")
                    return 0
                print_info("ROS2 daemon restarted")
                return 0
            print_info("ROS2 daemon is not running. Starting it.")
            if not spawn_daemon(args=[], timeout=10):
                print_error("Failed to start ROS2 daemon")
                return 0
            # The ros2 daemon not running could have actually been an issue for commands such as ros2 topic/service/action/...
            return 1
        except KeyboardInterrupt:
            print_warn(
                "Canceling the restart of the ROS2 daemon might lead to further issues."
            )
            if confirm(
                "Stop anyway? If ros2 daemon stopping fails, fallback can be enabled."
            ):
                raise
            print_info("Okay. Trying again.")

            if confirm("Use fallback to stop daemon?"):
                if not kill_ros2_daemon():
                    print_error("Failed to kill ROS2 daemon")
