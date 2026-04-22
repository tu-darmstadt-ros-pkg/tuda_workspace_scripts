from ament_index_python.packages import get_package_share_directory
import re
import os
import json
import json5
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
ZENOH_BRIDGE_CONFIG_PATH: str | None = os.getenv("ZENOH_BRIDGE_CONFIG_URI", None)
XML_MARKER = "<!-- This file is managed by tuda_workspace_scripts. Changes may be overwritten. -->"
YAML_MARKER = (
    "# This file is managed by tuda_workspace_scripts. Changes may be overwritten."
)
JSON_COMMENT_MARKER = (
    "// This file is managed by tuda_workspace_scripts. Changes may be overwritten."
)


def create_discovery_config(selected_robots: list[str], custom_addresses: list[str]):
    available_robots = load_robots()

    if RMW == "rmw_zenoh_cpp":
        create_zenoh_router_config_yaml(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW == "rmw_cyclonedds_cpp":
        create_static_cyclonedds_config_xml()
        create_zenoh_bridge_config(selected_robots, available_robots, custom_addresses)
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def update_discovery_config(selected_robots: list[str], custom_addresses: list[str]):
    available_robots = load_robots()

    if RMW == "rmw_zenoh_cpp":
        update_zenoh_router_config(selected_robots, available_robots, custom_addresses)
    elif RMW == "rmw_cyclonedds_cpp":
        create_static_cyclonedds_config_xml()
        update_zenoh_bridge_config(selected_robots, available_robots, custom_addresses)
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def get_connected_robots() -> list[str]:
    available_robots = load_robots()
    if RMW == "rmw_zenoh_cpp":
        routers = get_zenoh_routers_from_config_file(ZENOH_ROUTER_CONFIG_PATH)
        connected_robots = []
        for router in routers:
            for robot_name, robot_data in available_robots.items():
                if any(
                    router.get_zenoh_router_address() == r.get_zenoh_router_address()
                    for r in robot_data.zenoh_routers
                ):
                    connected_robots.append(robot_name)
        return connected_robots
    elif RMW == "rmw_cyclonedds_cpp":
        if not ZENOH_BRIDGE_CONFIG_PATH or not os.path.isfile(ZENOH_BRIDGE_CONFIG_PATH):
            return []
        routers = get_zenoh_routers_from_config_file(ZENOH_BRIDGE_CONFIG_PATH)
        connected_robots = []
        for router in routers:
            for robot_name, robot_data in available_robots.items():
                if any(
                    router.get_zenoh_router_address() == r.get_zenoh_router_address()
                    for r in robot_data.zenoh_routers
                ):
                    connected_robots.append(robot_name)
        return connected_robots
    elif RMW:
        raise NotImplementedError(
            f"Listing the currently connected robots is not implemented for RMW {RMW}"
        )
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def create_static_cyclonedds_config_xml():
    """Create the static CycloneDDS config with only localhost as peer.
    When using rmw_cyclonedds_cpp with a zenoh bridge, CycloneDDS only communicates
    locally and the bridge handles remote communication.
    """
    if not CYCLONEDDS_URI:
        print_warn("CYCLONEDDS_URI is not set. Cannot write Cyclone DDS config.")
        return

    config = _create_cyclonedds_config_xml(["127.0.0.1"])

    with open(CYCLONEDDS_URI, "w", encoding="utf-8") as file:
        file.write(f"{XML_MARKER}\n")
        file.write(config)
    print_info("Cyclone DDS static config written.")


def create_zenoh_bridge_config(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    if not ZENOH_BRIDGE_CONFIG_PATH:
        print_warn(
            "ZENOH_BRIDGE_CONFIG_URI is not set. Cannot write zenoh bridge config."
        )
        return
    if not ZENOH_BRIDGE_CONFIG_PATH.endswith((".json", ".json5")):
        print_warn(
            f"Unsupported config file format: {ZENOH_BRIDGE_CONFIG_PATH}. Supported formats are .json and .json5."
        )
        return

    routers = _create_zenoh_router_list(
        selected_robots, available_robots, custom_addresses
    )
    config = _create_zenoh_bridge_config_dict(routers)

    if os.path.isfile(ZENOH_BRIDGE_CONFIG_PATH):
        with open(ZENOH_BRIDGE_CONFIG_PATH, "r") as file:
            if file.readline().strip() != JSON_COMMENT_MARKER:
                i = 0
                while os.path.isfile(ZENOH_BRIDGE_CONFIG_PATH + f".backup{i}"):
                    i += 1
                print_warn(
                    f"Existing zenoh bridge config found at {ZENOH_BRIDGE_CONFIG_PATH}. Backing up as {ZENOH_BRIDGE_CONFIG_PATH}.backup{i}."
                )
                os.rename(
                    ZENOH_BRIDGE_CONFIG_PATH, f"{ZENOH_BRIDGE_CONFIG_PATH}.backup{i}"
                )

    with open(ZENOH_BRIDGE_CONFIG_PATH, "w") as file:
        file.write(f"{JSON_COMMENT_MARKER}\n")
        json5.dump(config, file, indent=2)
    print_info("Zenoh bridge config updated.")


def update_zenoh_bridge_config(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    if not ZENOH_BRIDGE_CONFIG_PATH:
        print_warn(
            "ZENOH_BRIDGE_CONFIG_URI is not set. Cannot update zenoh bridge config."
        )
        return
    if not ZENOH_BRIDGE_CONFIG_PATH.endswith((".json", ".json5")):
        print_warn(
            f"Unsupported config file format: {ZENOH_BRIDGE_CONFIG_PATH}. Supported formats are .json and .json5."
        )
        return

    routers = _create_zenoh_router_list(
        selected_robots, available_robots, custom_addresses
    )

    config = _create_zenoh_bridge_config_dict(routers)
    if not os.path.isfile(ZENOH_BRIDGE_CONFIG_PATH):
        print_warn(
            f"Zenoh bridge config file not found at {ZENOH_BRIDGE_CONFIG_PATH}. Creating new config file."
        )
    else:
        with open(ZENOH_BRIDGE_CONFIG_PATH, "r") as file:
            existing = json5.load(file)
        # Preserve user settings, only update connect endpoints
        existing.setdefault("connect", {})["endpoints"] = [
            router.get_zenoh_router_address() for router in routers
        ]
        config = existing

    with open(ZENOH_BRIDGE_CONFIG_PATH, "w") as file:
        file.write(f"{JSON_COMMENT_MARKER}\n")
        json5.dump(config, file, indent=2)
    print_info("Zenoh bridge config updated.")


def _create_zenoh_bridge_config_dict(routers: list[ZenohRouter]) -> dict:
    return {
        "mode": "router",
        "listen": {"endpoints": ["tcp/0.0.0.0:7448"]},
        "connect": {
            "endpoints": [router.get_zenoh_router_address() for router in routers]
        },
        "scouting": {"multicast": {"enabled": False}},
        "plugins": {"ros2dds": {"domain": 0}},
    }


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


def _create_zenoh_router_list(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
) -> list[ZenohRouter]:
    routers = []

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
        routers.append(ZenohRouter.from_string(address))

    return routers


def get_zenoh_routers_from_config_file(config_path: str) -> list[ZenohRouter]:
    if config_path.endswith((".yaml", ".yml")):
        with open(config_path, "r") as file:
            config = yaml.safe_load(file)
        routers = []
        for endpoint in config.get("connect", {}).get("endpoints", []):
            routers.append(ZenohRouter.from_string(endpoint))
        return routers
    elif config_path.endswith((".json", ".json5")):
        with open(config_path, "r") as file:
            config = json5.load(file)
        routers = []
        for endpoint in config.get("connect", {}).get("endpoints", []):
            routers.append(ZenohRouter.from_string(endpoint))
        return routers
    raise ValueError(
        f"Unsupported config file format: {config_path}. Supported formats are .yaml, .yml, .json, and .json5."
    )


def create_zenoh_router_config_yaml(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    routers = _create_zenoh_router_list(
        selected_robots, available_robots, custom_addresses
    )

    config = _create_zenoh_router_config_yaml(routers)

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

    with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
        file.write(f"{YAML_MARKER}\n")
        yaml.dump(config, file, default_flow_style=False)
    print_info(f"Zenoh router config updated.")


def update_zenoh_router_config(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    if not ZENOH_ROUTER_CONFIG_PATH:
        print_warn("ZENOH_ROUTER_CONFIG_URI is not set. Cannot update config file.")
        return
    if not ZENOH_ROUTER_CONFIG_PATH.endswith((".yaml", ".yml", ".json", ".json5")):
        print_warn(
            f"Unsupported config file format: {ZENOH_ROUTER_CONFIG_PATH}. Supported formats are .yaml, .yml, .json, and .json5. Cannot update config file."
        )
        return
    routers = _create_zenoh_router_list(
        selected_robots, available_robots, custom_addresses
    )

    config = {
        "mode": "router",
        "connect": {"endpoints": []},
    }
    if not os.path.isfile(ZENOH_ROUTER_CONFIG_PATH):
        print_warn(
            f"Zenoh router config file not found at {ZENOH_ROUTER_CONFIG_PATH}. Creating new config file."
        )
    if ZENOH_ROUTER_CONFIG_PATH.endswith((".yaml", ".yml")):
        if os.path.isfile(ZENOH_ROUTER_CONFIG_PATH):
            with open(ZENOH_ROUTER_CONFIG_PATH, "r") as file:
                config = yaml.safe_load(file)
        if not config["connect"]:
            config["connect"] = {}
        config["connect"]["endpoints"] = [
            router.get_zenoh_router_address() for router in routers
        ]
        with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
            yaml.dump(config, file, default_flow_style=False)
    elif ZENOH_ROUTER_CONFIG_PATH.endswith((".json", ".json5")):
        if os.path.isfile(ZENOH_ROUTER_CONFIG_PATH):
            with open(ZENOH_ROUTER_CONFIG_PATH, "r") as file:
                config = json5.load(file)
        if not config["connect"]:
            config["connect"] = {}
        config["connect"]["endpoints"] = [
            router.get_zenoh_router_address() for router in routers
        ]
        with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
            if ZENOH_ROUTER_CONFIG_PATH.endswith(".json5"):
                json5.dump(config, file, indent=2)
            else:
                json.dump(config, file, indent=2)


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
    print_info(f"RMW Implementation: {RMW}")
    if RMW == "rmw_zenoh_cpp":
        print_zenoh_discovery_config()
    elif RMW == "rmw_cyclonedds_cpp":
        print_zenoh_bridge_discovery_config()
        print_cyclonedds_discovery_config()
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def print_cyclonedds_discovery_config():
    if os.path.exists(CYCLONEDDS_URI):
        print_info(f"Configuration file: {CYCLONEDDS_URI}")
        with open(CYCLONEDDS_URI, "r") as file:
            print(file.read())
    else:
        print_warn(f"Configuration file not found: {CYCLONEDDS_URI}")


def print_zenoh_discovery_config():
    if os.path.exists(ZENOH_ROUTER_CONFIG_PATH):
        print_info(f"Configuration file: {ZENOH_ROUTER_CONFIG_PATH}")
        with open(ZENOH_ROUTER_CONFIG_PATH, "r") as file:
            print(file.read())
    else:
        print_warn(f"Configuration file not found: {ZENOH_ROUTER_CONFIG_PATH}")


def print_zenoh_bridge_discovery_config():
    if not ZENOH_BRIDGE_CONFIG_PATH:
        print_warn("ZENOH_BRIDGE_CONFIG_URI is not set.")
        return
    if os.path.exists(ZENOH_BRIDGE_CONFIG_PATH):
        print_info(f"Zenoh bridge configuration file: {ZENOH_BRIDGE_CONFIG_PATH}")
        with open(ZENOH_BRIDGE_CONFIG_PATH, "r") as file:
            print(file.read())
    else:
        print_warn(
            f"Zenoh bridge configuration file not found: {ZENOH_BRIDGE_CONFIG_PATH}"
        )


def _create_zenoh_router_config_yaml(routers):
    config = {
        "mode": "router",
        "connect": {
            "endpoints": [router.get_zenoh_router_address() for router in routers]
        },
    }
    return config
