#!/usr/bin/env python3
from tuda_workspace_scripts.print import *
from ros2cli.node.daemon import is_daemon_running, spawn_daemon, shutdown_daemon
import os


def fix() -> int:
    print_header("Checking ROS2 daemon")
    while True:
        try:
            if is_daemon_running(args=[]):
                print_info("ROS2 daemon is running. Restarting it just to be safe.")
                if not shutdown_daemon(args=[], timeout=10):
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
            if confirm("Stop anyway?"):
                raise
            print_info("Okay. Trying again.")
