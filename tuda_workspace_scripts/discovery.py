from ament_index_python.packages import get_package_share_directory
import re
import os
import yaml
from jinja2 import Environment, FileSystemLoader
from .print import print_info, print_warn
from .robots import Robot, ZenohRouter, load_robots
from .workspace import get_workspace_root


ws_root = get_workspace_root()
if not ws_root:
    raise RuntimeError("Workspace root not found")
RMW: str | None = os.getenv("RMW_IMPLEMENTATION", None)
CYCLONEDDS_URI: str | None = os.getenv("CYCLONEDDS_URI", None)
ZENOH_ROUTER_CONFIG_PATH: str | None = os.getenv("ZENOH_ROUTER_CONFIG_URI", None)
XML_MARKER = "<!-- This file is managed by tuda_workspace_scripts. Changes may be overwritten. -->"
YAML_MARKER = (
    "# This file is managed by tuda_workspace_scripts. Changes may be overwritten."
)


def create_discovery_config(selected_robots: list[str], custom_addresses: list[str]):
    available_robots = load_robots()

    if RMW == "rmw_zenoh_cpp":
        create_zenoh_router_config_yaml(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW == "rmw_cyclonedds_cpp":
        create_cyclonedds_router_config_xml(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def create_cyclonedds_router_config_xml(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    peers = []

    # Always set localhost, even if the user did not specify it
    peers.append("127.0.0.1")

    for name in selected_robots:
        if name == "off":
            break
        elif name == "all":
            for _, robot_data in available_robots.items():
                if not robot_data.cyclonedds_address:
                    print_warn(f"No Cyclone DDS address found for {robot_data.name}")
                    continue
                peers.append(robot_data.cyclonedds_address)
            break
        elif name in available_robots:
            if not available_robots[name].cyclonedds_address:
                print_warn(
                    f"No Cyclone DDS address found for {available_robots[name].name}"
                )
                continue
            peers.append(available_robots[name].cyclonedds_address)
        else:
            print_warn(
                f"Couldn't find an entry for {name} in robot configs. Please check if your selected robot is available."
            )

    ipv4_regex = r"^(?:\d{1,3}\.){3}\d{1,3}$"
    hostname_regex = r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*$"
    for address in custom_addresses:
        match = re.match(ipv4_regex, address) or re.match(hostname_regex, address)
        if not match:
            print_warn(
                f"Invalid address '{address}'! Please specify an IP address or hostname."
            )
            continue
        peers.append(address)

    config = _create_cyclonedds_config_xml(peers)
    print("Connecting to peers: ")
    for peer in peers:
        print(" -", peer)

    if os.path.isfile(CYCLONEDDS_URI):
        # Backup existing files if not ours
        with open(CYCLONEDDS_URI, "r") as file:
            if file.readline().strip() != XML_MARKER:
                i = 0
                while os.path.isfile(CYCLONEDDS_URI + f".backup{i}"):
                    i += 1
                print_warn(
                    f"Existing cyclonedds config found at {CYCLONEDDS_URI}. Backing up as {CYCLONEDDS_URI}.backup{i}."
                )
                os.rename(CYCLONEDDS_URI, f"{CYCLONEDDS_URI}.backup{i}")

    with open(CYCLONEDDS_URI, "w", encoding="utf-8") as file:
        file.write(f"{XML_MARKER}\n")
        file.write(config)
    print_info(f"Cyclone DDS config updated.")


def create_zenoh_router_config_yaml(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    routers = []

    # Always set localhost, even if the user did not specify it
    routers.append(ZenohRouter("localhost", "7447", "tcp"))

    for name in selected_robots:
        if name == "off":
            break
        elif name == "all":
            for _, robot_data in available_robots.items():
                routers.extend(robot_data.zenoh_routers)
            break
        elif name in available_robots:
            routers.extend(available_robots[name].zenoh_routers)
        else:
            print_warn(
                f"Couldn't find an entry for {name} in robot configs. Please check if your selected robot is available."
            )

    for address in custom_addresses:
        match = re.match(r"([^:/]+)(:\d+)?(/.*)?$", address)
        if not match:
            print_warn(
                f"Invalid address '{address}'! Please use the format 'IP_OR_HOSTNAME[:PORT][/PROTOCOL]'."
            )
            continue
        name = match.group(1)
        tmp = match.group(2)
        port = int(tmp[1:]) if tmp and tmp[0] == ":" else 7447
        tmp = match.group(3)
        protocol = tmp[1:] if tmp and tmp[0] == "/" else "tcp"

        routers.append(ZenohRouter(name, port, protocol))

    config = _create_zenoh_router_config_yaml(routers)
    print("Connecting to routers:")
    for router in config["connect"]["endpoints"]:
        print(" -", router)

    if os.path.isfile(ZENOH_ROUTER_CONFIG_PATH):
        # Backup existing files if not ours
        with open(ZENOH_ROUTER_CONFIG_PATH, "r") as file:
            if file.readline().strip() != YAML_MARKER:
                i = 0
                while os.path.isfile(ZENOH_ROUTER_CONFIG_PATH + f".backup{i}"):
                    i += 1
                print_warn(
                    f"Existing zenoh router config found at {ZENOH_ROUTER_CONFIG_PATH}. Backing up as {ZENOH_ROUTER_CONFIG_PATH}.backup{i}."
                )
                os.rename(
                    ZENOH_ROUTER_CONFIG_PATH, f"{ZENOH_ROUTER_CONFIG_PATH}.backup{i}"
                )

    # Write new config to file
    with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
        file.write(f"{YAML_MARKER}\n")
        yaml.dump(config, file, default_flow_style=False)


def _create_cyclonedds_config_xml(peers: list[str]) -> str:
    # Get the template directory path from the share directory
    template_dir = os.path.join(
        get_package_share_directory("tuda_workspace_scripts"), "templates"
    )
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("cyclonedds_config.xml.j2")

    # Render the template with the peers list
    return template.render(peers=peers)


def print_discovery_config():
    if RMW == "rmw_zenoh_cpp":
        print_zenoh_discovery_config()
    elif RMW == "rmw_cyclonedds_cpp":
        print_cyclonedds_discovery_config()
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def print_cyclonedds_discovery_config():
    if os.path.exists(CYCLONEDDS_URI):
        print_info(f"Configuration file: {CYCLONEDDS_URI}")
        with open(CYCLONEDDS_URI, "r") as file:
            print_info(file.read())
    else:
        print_warn(f"Configuration file not found: {CYCLONEDDS_URI}")


def print_zenoh_discovery_config():
    if os.path.exists(ZENOH_ROUTER_CONFIG_PATH):
        print_info(f"Configuration file: {ZENOH_ROUTER_CONFIG_PATH}")
        with open(ZENOH_ROUTER_CONFIG_PATH, "r") as file:
            print_info(file.read())
    else:
        print_warn(f"Configuration file not found: {ZENOH_ROUTER_CONFIG_PATH}")


def _create_zenoh_router_config_yaml(routers):
    config = {
        "mode": "router",
        "connect": {
            "endpoints": [router.get_zenoh_router_address() for router in routers]
        },
    }
    return config
