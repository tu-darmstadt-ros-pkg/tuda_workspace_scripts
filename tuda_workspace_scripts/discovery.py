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
NDDS_DISCOVERY_PEERS_FILE: str | None = os.getenv(
    "TUDA_WSS_NDDS_DISCOVERY_PEERS_FILE",
    os.path.join(ws_root, ".config", "ndds_discovery_peers"),
)
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
    elif RMW == "rmw_connextdds":
        create_connext_ndds_discovery_peers_file(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def update_discovery_config(selected_robots: list[str], custom_addresses: list[str]):
    available_robots = load_robots()

    if RMW == "rmw_zenoh_cpp":
        update_zenoh_router_config(selected_robots, available_robots, custom_addresses)
    elif RMW == "rmw_cyclonedds_cpp":
        print_warn(
            "Updating Cyclone DDS config is not supported. Overwriting the config file instead."
        )
        create_cyclonedds_router_config_xml(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW == "rmw_connextdds":
        print_warn(
            "Updating RTI Connext discovery peers is done by overwriting the peers file."
        )
        create_connext_ndds_discovery_peers_file(
            selected_robots, available_robots, custom_addresses
        )
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
    elif RMW == "rmw_connextdds":
        return get_connext_connected_robots(available_robots)
    elif RMW:
        raise NotImplementedError(
            f"Listing the currently connected robots is not implemented for RMW {RMW}"
        )
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def _robot_cyclonedds_hosts(robot: Robot) -> list[str]:
    raw = robot.cyclonedds_address
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def collect_unicast_dds_peer_hostnames(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
) -> list[str]:
    """
    Hostnames or IPv4 addresses for unicast DDS discovery (Cyclone DDS peers and
    RTI Connext NDDS_DISCOVERY_PEERS built-in UDPv4 locators).
    """
    peers: list[str] = []

    # Always set localhost, even if the user did not specify it
    peers.append("127.0.0.1")

    for name in selected_robots:
        if name == "off":
            break
        elif name == "all":
            for _, robot_data in available_robots.items():
                hosts = _robot_cyclonedds_hosts(robot_data)
                if not hosts:
                    print_warn(
                        f"No Cyclone/Connext DDS address found for {robot_data.name}"
                    )
                    continue
                peers.extend(hosts)
            break
        elif name in available_robots:
            hosts = _robot_cyclonedds_hosts(available_robots[name])
            if not hosts:
                print_warn(
                    f"No Cyclone/Connext DDS address found for {available_robots[name].name}"
                )
                continue
            peers.extend(hosts)
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

    return peers


def _rti_builtin_udpv4_locators(hosts: list[str]) -> str:
    return ",".join(f"builtin.udpv4://{h}" for h in hosts)


def _parse_ndds_discovery_peer_hosts(peers_value: str) -> list[str]:
    hosts = []
    for raw in peers_value.split(","):
        part = raw.strip()
        if not part:
            continue
        prefix = "builtin.udpv4://"
        if part.startswith(prefix):
            part = part[len(prefix) :]
        hosts.append(part)
    return hosts


def _read_ndds_discovery_peers_locators() -> str | None:
    if not NDDS_DISCOVERY_PEERS_FILE or not os.path.isfile(NDDS_DISCOVERY_PEERS_FILE):
        return None
    with open(NDDS_DISCOVERY_PEERS_FILE, "r", encoding="utf-8") as file:
        lines = file.read().splitlines()
    if not lines:
        return None
    if lines[0].strip() == YAML_MARKER and len(lines) >= 2:
        return lines[1].strip()
    return lines[0].strip()


def create_connext_ndds_discovery_peers_file(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    """
    Write NDDS_DISCOVERY_PEERS-compatible locator list for rmw_connextdds.

    Set in your shell (e.g. workspace setup.bash):

        export NDDS_DISCOVERY_PEERS=$(tail -n 1 "$TUDA_WSS_NDDS_DISCOVERY_PEERS_FILE")

    when using the default path, or read the last line of the file this function writes.
    """
    peers = collect_unicast_dds_peer_hostnames(
        selected_robots, available_robots, custom_addresses
    )
    locators = _rti_builtin_udpv4_locators(peers)
    print("Connecting to peers: ")
    for p in peers:
        print(" -", p)

    if os.path.isfile(NDDS_DISCOVERY_PEERS_FILE):
        with open(NDDS_DISCOVERY_PEERS_FILE, "r", encoding="utf-8") as file:
            first = file.readline().strip()
        if first != YAML_MARKER:
            i = 0
            while os.path.isfile(NDDS_DISCOVERY_PEERS_FILE + f".backup{i}"):
                i += 1
            print_warn(
                f"Existing NDDS discovery peers file found at {NDDS_DISCOVERY_PEERS_FILE}. "
                f"Backing up as {NDDS_DISCOVERY_PEERS_FILE}.backup{i}."
            )
            os.rename(
                NDDS_DISCOVERY_PEERS_FILE, f"{NDDS_DISCOVERY_PEERS_FILE}.backup{i}"
            )

    os.makedirs(os.path.dirname(NDDS_DISCOVERY_PEERS_FILE), exist_ok=True)
    with open(NDDS_DISCOVERY_PEERS_FILE, "w", encoding="utf-8") as file:
        file.write(f"{YAML_MARKER}\n")
        file.write(locators)
        file.write("\n")
    print_info("RTI Connext NDDS_DISCOVERY_PEERS file updated.")
    print_info(
        "Export NDDS_DISCOVERY_PEERS from the last line of this file in your shell, e.g.: "
        f'export NDDS_DISCOVERY_PEERS=$(tail -n 1 "{NDDS_DISCOVERY_PEERS_FILE}")'
    )


def get_connext_connected_robots(available_robots: dict[str, Robot]) -> list[str]:
    locators = _read_ndds_discovery_peers_locators()
    if not locators:
        return []
    peer_hosts = set(_parse_ndds_discovery_peer_hosts(locators))
    connected = []
    for robot_name, robot_data in available_robots.items():
        rh = set(_robot_cyclonedds_hosts(robot_data))
        if rh and rh.intersection(peer_hosts):
            connected.append(robot_name)
    return connected


def create_cyclonedds_router_config_xml(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
    peers = collect_unicast_dds_peer_hostnames(
        selected_robots, available_robots, custom_addresses
    )

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
        print_cyclonedds_discovery_config()
    elif RMW == "rmw_connextdds":
        print_connext_discovery_config()
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


def print_connext_discovery_config():
    print_info(f"NDDS_DISCOVERY_PEERS file: {NDDS_DISCOVERY_PEERS_FILE}")
    if os.path.exists(NDDS_DISCOVERY_PEERS_FILE):
        with open(NDDS_DISCOVERY_PEERS_FILE, "r", encoding="utf-8") as file:
            print(file.read())
        loc = _read_ndds_discovery_peers_locators()
        if loc:
            print_info(
                "Effective NDDS_DISCOVERY_PEERS value (last line / locator list):"
            )
            print(loc)
    else:
        print_warn(f"Configuration file not found: {NDDS_DISCOVERY_PEERS_FILE}")


def print_zenoh_discovery_config():
    if os.path.exists(ZENOH_ROUTER_CONFIG_PATH):
        print_info(f"Configuration file: {ZENOH_ROUTER_CONFIG_PATH}")
        with open(ZENOH_ROUTER_CONFIG_PATH, "r") as file:
            print(file.read())
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
