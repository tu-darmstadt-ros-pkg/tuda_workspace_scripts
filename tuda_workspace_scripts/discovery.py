import re
import os
import yaml
import xml.etree.ElementTree as ET
from xml.dom import minidom
from .print import print_info, print_warn
from .robots import Robot, ZenohRouter, load_robots
from .workspace import get_workspace_root

ws_root = get_workspace_root()
if not ws_root:
    raise RuntimeError("Workspace root not found")
RMW: str | None = os.getenv("RMW_IMPLEMENTATION", None)
CYCLONEDDS_URI: str | None = os.getenv("CYCLONEDDS_URI", None)
ZENOH_ROUTER_CONFIG_PATH: str | None = os.getenv("ZENOH_ROUTER_CONFIG_URI", None)

YAML_MARKER = (
    "# This file is managed by tuda_workspace_scripts. Changes may be overwritten."
)
XML_MARKER = "<!-- This file is managed by tuda_workspace_scripts. Changes may be overwritten. -->"


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
    xml_str = minidom.parseString(ET.tostring(config)).toprettyxml(indent="    ")
    with open(CYCLONEDDS_URI, "w", encoding="utf-8") as file:
        file.write(f"{XML_MARKER}\n")
        file.write(xml_str)
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
    with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
        file.write(f"{YAML_MARKER}\n")
        yaml.dump(config, file, default_flow_style=False)
    print_info(f"Zenoh router config updated.")


def _create_cyclonedds_config_xml(peers: list[str]) -> ET.Element:
    # Define XML namespaces
    nsmap = {
        "xmlns": "https://cdds.io/config",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "https://cdds.io/config https://raw.githubusercontent.com/eclipse-cyclonedds/cyclonedds/master/etc/cyclonedds.xsd",
    }

    # Create the root element
    root = ET.Element("CycloneDDS", nsmap)

    # Create the Domain element
    domain = ET.SubElement(root, "Domain", {"Id": "any"})

    general = ET.SubElement(domain, "General")
    interfaces = ET.SubElement(general, "Interfaces")
    ET.SubElement(
        interfaces,
        "NetworkInterface",
        {"autodetermine": "true", "priority": "default", "multicast": "default"},
    )
    ET.SubElement(general, "AllowMulticast").text = "false"
    ET.SubElement(general, "MaxMessageSize").text = "65500B"

    # Discovery settings
    discovery = ET.SubElement(domain, "Discovery")
    ET.SubElement(discovery, "EnableTopicDiscoveryEndpoints").text = "true"
    ET.SubElement(discovery, "ParticipantIndex").text = "auto"
    ET.SubElement(discovery, "MaxAutoParticipantIndex").text = "50"

    # Peers list
    peers_element = ET.SubElement(discovery, "Peers")
    for address in peers:
        ET.SubElement(peers_element, "Peer", {"Address": address})

    # Internal settings
    internal = ET.SubElement(domain, "Internal")
    watermarks = ET.SubElement(internal, "Watermarks")
    ET.SubElement(watermarks, "WhcHigh").text = "500kB"

    return root


def _create_zenoh_router_config_yaml(routers):
    config = {
        "mode": "router",
        "connect": {
            "endpoints": [router.get_zenoh_router_address() for router in routers]
        },
    }
    return config
