#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
from tuda_workspace_scripts.discovery import *
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.robots import *
from tuda_workspace_scripts.scripts import get_hooks_for_command, load_method_from_file
from os.path import basename
import subprocess


class RobotChoicesCompleter:
    def __call__(self, prefix, parsed_args, **kwargs):
        complete_args = [var for var in load_robots().keys()]
        complete_args.append("off")
        chosen_args = getattr(parsed_args, "connections", [])

        if not chosen_args:
            complete_args.extend(["all"])
        elif "all" in chosen_args:
            return []
        else:
            complete_args = list(filter(lambda x: x not in chosen_args, complete_args))

        return complete_args


def main():
    parser = argparse.ArgumentParser(
        prog="discovery",
        description="""
Enables the discovery of other ROS2 machines.

You can also specify custom addresses to connect to.
The format depends on the used middleware.

Zenoh
=====
IP_OR_HOSTNAME[:PORT][/PROTOCOL]
Port defaults to 7447 and protocol to tcp.
Examples: hostname:8443 10.0.10.3:8231/tcp

CycloneDDS
==========
IP_OR_HOSTNAME
Examples: hostname 10.0.10.3
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    robots = load_robots()

    # Add print-config option
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the current discovery configuration and exit.",
    )

    # Add configuration options
    choices = list(robots.keys())
    choices.extend(["off", "all"])
    first_arg = parser.add_argument(
        "robots",
        nargs="*",
        choices=choices,
        help="Select robots which should be discovered by your machine. "
        "Choose 'off' to limit discovery to the localhost or 'all' to discover all known robots.",
    )
    first_arg.completer = RobotChoicesCompleter()

    # Add optional address argument
    parser.add_argument(
        "--address",
        nargs="+",
        type=str,
        help="Specify one or more custom addresses for discovery.",
    )

    argcomplete.autocomplete(parser)

    args = parser.parse_args()

    # Check for mutually exclusive usage
    if args.print_config and args.robots:
        parser.error("--print-config cannot be used with robot selection")

    if args.print_config:
        print_discovery_config()
        return

    selected_robots = args.robots
    custom_addresses = args.address or []

    # Validation logic
    if not selected_robots and not custom_addresses:
        parser.error("You must specify either 'robots' or '--address'.")

    if "off" in selected_robots and len(selected_robots) > 1:
        parser.error("'off' cannot be combined with other robots.")

    # Disallow "all" with any other options
    if "all" in selected_robots and len(selected_robots) > 1:
        parser.error("'all' cannot be combined with other robots.")

    create_discovery_config(selected_robots, custom_addresses)

    # Get hooks and sort them by their filename
    hooks = list(sorted(get_hooks_for_command("discovery"), key=basename))
    for hook in hooks:
        if hook.endswith(".py"):
            on_discovery_updated = load_method_from_file(hook, "on_discovery_updated")
            if on_discovery_updated is None:
                print_error(
                    f"Hook {hook} does not contain a valid on_discovery_updated method."
                )
                continue
            on_discovery_updated()
        elif hook.endswith(".bash") or hook.endswith(".sh"):
            executable = "bash" if hook.endswith(".bash") else "sh"
            subprocess.run([executable, hook], cwd=get_workspace_root())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl-C received! Exiting...")
        exit(0)
