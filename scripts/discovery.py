#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.robots import *
from tuda_workspace_scripts.discovery import *


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
        prog="discovery", description="Allows to discover other ROS2 machines"
    )
    robots = load_robots()

    choices = list(robots.keys())
    choices.extend(["off", "all"])
    first_arg = parser.add_argument(
        "robots",
        nargs="*",
        choices=choices,
        help="Select robots which should be discovered by your machine. Choose 'off' to limit discovery to the localhost or 'all' to discover all known robots.",
    )
    first_arg.completer = RobotChoicesCompleter()

    # Add optional address argument
    parser.add_argument(
        "--address",
        nargs="+",
        type=str,
        help="Specify one or more custom addresses (e.g., IP or hostname) for discovery.",
    )

    argcomplete.autocomplete(parser)

    args = parser.parse_args()
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

    print_warn(
        "Warning: The settings are applied to all terminals and new started ros nodes. Restart old nodes if necessary."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl-C received! Exiting...")
        exit(0)
