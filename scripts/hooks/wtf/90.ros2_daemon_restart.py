#!/usr/bin/env python3
from tuda_workspace_scripts.print import *
from ros2cli.node.daemon import is_daemon_running, spawn_daemon, shutdown_daemon
import os


def fix():
    print_header("Checking ROS2 daemon")
    while True:
        try:
            if is_daemon_running(args=[]):
                print_info("ROS2 daemon is running. Restarting it just to be safe.")
                # ensure that super client dds settings are kept
                super_client_xml_path = "/tmp/tuda_wss/super_client.xml"
                if os.path.exists(super_client_xml_path):
                    print_info("Super Client config found. Restarting client with its dds settings.")
                    os.environ["FASTRTPS_DEFAULT_PROFILES_FILE"] = super_client_xml_path
                if not shutdown_daemon(args=[], timeout=10):
                    print_error("Failed to shutdown ROS2 daemon")
                    return False
                if not spawn_daemon(args=[], timeout=10):
                    print_error("Failed to restart ROS2 daemon after stopping it")
                    return False
                print_info("ROS2 daemon restarted")
                return False
            print_info("ROS2 daemon is not running. Starting it.")
            if not spawn_daemon(args=[], timeout=10):
                print_error("Failed to start ROS2 daemon")
                return False
            # The ros2 daemon not running could have actually been an issue for commands such as ros2 topic/service/action/...
            return True
        except KeyboardInterrupt:
            print_warn(
                "Canceling the restart of the ROS2 daemon might lead to further issues."
            )
            if confirm("Stop anyway?"):
                raise
            print_info("Okay. Trying again.")
