#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.robots import *
from tuda_workspace_scripts.discovery import *
from tuda_workspace_scripts.print import print_warn

class DiscoveryServerChoicesCompleter:
    def __call__(self, prefix, parsed_args, **kwargs):
        complete_args = [var for var in load_robots().keys()]
        # allowing a local server with ID 0 and default port
        complete_args.append("local_server")
        chosen_args = getattr(parsed_args, "discovery_servers", [])

        if not chosen_args:
            complete_args.extend(["off", "all"])
        elif "off" in chosen_args or "all" in chosen_args:
            return []
        else:
          complete_args = list(filter(lambda x: x not in chosen_args, complete_args))

        return complete_args

    
def main():
    parser = argparse.ArgumentParser(prog="discovery", description="Allows to set the discovery settings to fast dds servers on multiple systems.")
    robots = load_robots()
    choices = list(robots.keys())
    choices.extend(["off", "all", "local_server"])
    first_arg = parser.add_argument(
        "discovery_servers",
        nargs="+",
        choices = choices,
        help="Select robots for which discovery servers should be exported. Choose off to disable all discovery servers or all to export all known discovery servers. local_server will set a discovery server on the local host with default settings."
    )
    first_arg.completer = DiscoveryServerChoicesCompleter()
    argcomplete.autocomplete(parser)

    args = parser.parse_args()
    discovery_servers = args.discovery_servers

    if discovery_servers[0] == "off":
        disable_discovery_xml()
        restart_super_client_daemon()
    else:
        create_discovery_xml(discovery_servers)
        restart_super_client_daemon()

    print_warn("Warning: The settings are applied to all terminals and new started ros nodes. Restart old nodes if necessary.")
        

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl-C received! Exiting...")
        exit(0)
