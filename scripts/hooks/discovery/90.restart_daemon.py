#!/usr/bin/env python3
from ros2cli.node.daemon import is_daemon_running, spawn_daemon, shutdown_daemon
from tuda_workspace_scripts.print import *


def on_discovery_updated(**_):
    print_header("Restarting ROS2 daemon")
    if is_daemon_running(args=[]):
        if not shutdown_daemon(args=[], timeout=10):
            print_error("Failed to shutdown ROS2 daemon")
            return
        if not spawn_daemon(args=[], timeout=10):
            print_error("Failed to restart ROS2 daemon after stopping it")
            return
        print_info("ROS2 daemon restarted")
    else:
        print_info("ROS2 daemon is not running. No need to restart it.")
