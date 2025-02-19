#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.robots import *
from tuda_workspace_scripts.discovery import *
from tuda_workspace_scripts.print import print_warn

class RouterChoicesCompleter:
    def __call__(self, prefix, parsed_args, **kwargs):
        complete_args = [var for var in load_robots().keys()]
        # allowing a local server with ID 0 and default port
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
    parser = argparse.ArgumentParser(prog="discovery", description="Allows to set the zenoh router to other routers on multiple systems. TODO make this rmw independent")
    robots = load_robots()

    choices = list(robots.keys())
    choices.extend(["off","all"])    
    first_arg = parser.add_argument(
        "connections",
        nargs="+",
        choices = choices,
        help="Select robots which should be discovered by your machine. Choose 'off' to limit discovery to the localhost or 'all' to discover all known robots."
    )
    first_arg.completer = RouterChoicesCompleter()
    argcomplete.autocomplete(parser)

    args = parser.parse_args()
    connections = args.connections

    if "off" in connections and len(connections) > 1:
        parser.error("'off' cannot be combined with other robots.")
    
    # Disallow "all" with any other options
    if "all" in connections and len(connections) > 1:
        parser.error("'all' cannot be combined with other robots.")

    create_discovery_config(connections)

    print_warn("Warning: The settings are applied to all terminals and new started ros nodes. Restart old nodes if necessary.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl-C received! Exiting...")
        exit(0)