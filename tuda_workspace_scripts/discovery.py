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
ZENOH_BRIDGE_CONFIG_URI: str | None = os.getenv("ZENOH_BRIDGE_CONFIG_URI", None)
CYCLONEDDS_URI: str | None = os.getenv("CYCLONEDDS_URI", None)
ZENOH_ROUTER_CONFIG_PATH: str | None = os.getenv("ZENOH_ROUTER_CONFIG_URI", None)
XML_MARKER = "<!-- This file is managed by tuda_workspace_scripts. Changes may be overwritten. -->"
YAML_MARKER = (
    "# This file is managed by tuda_workspace_scripts. Changes may be overwritten."
)
JSON5_MARKER = (
    "// This file is managed by tuda_workspace_scripts. Changes may be overwritten."
)


def create_discovery_config(selected_robots: list[str], custom_addresses: list[str]):
    available_robots = load_robots()

    if RMW == "rmw_zenoh_cpp":
        create_zenoh_router_config_yaml(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW == "rmw_cyclonedds_cpp":
        create_zenoh_bridge_config_json5(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def create_zenoh_bridge_config_json5(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
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
        match = re.match(r"([^:/]+)(:\d+)?(/.*)?$", address)
        if not match:
            print_warn(
                f"Invalid address '{address}'! Please use the format 'IP_OR_HOSTNAME[:PORT][/PROTOCOL]'."
            )
            continue
        name = match.group(1)
        tmp = match.group(2)
        port = int(tmp[1:]) if tmp and tmp[0] == ":" else 7448
        tmp = match.group(3)
        protocol = tmp[1:] if tmp and tmp[0] == "/" else "tcp"
        routers.append(ZenohRouter(name, port, protocol))

    endpoints = [router.get_zenoh_router_address() for router in routers]
    config = _create_zenoh_bridge_config_json5(endpoints)
    print("Zenoh bridge connecting to endpoints:")
    for endpoint in endpoints:
        print(" -", endpoint)

    if os.path.isfile(ZENOH_BRIDGE_CONFIG_URI):
        # Backup existing files if not ours
        with open(ZENOH_BRIDGE_CONFIG_URI, "r") as file:
            if file.readline().strip() != JSON5_MARKER:
                i = 0
                while os.path.isfile(ZENOH_BRIDGE_CONFIG_URI + f".backup{i}"):
                    i += 1
                print_warn(
                    f"Existing Zenoh bridge config found at {ZENOH_BRIDGE_CONFIG_URI}. Backing up as {ZENOH_BRIDGE_CONFIG_URI}.backup{i}."
                )
                os.rename(ZENOH_BRIDGE_CONFIG_URI, f"{ZENOH_BRIDGE_CONFIG_URI}.backup{i}")

    with open(ZENOH_BRIDGE_CONFIG_URI, "w", encoding="utf-8") as file:
        file.write(f"{JSON5_MARKER}\n")
        file.write(config)
    print_info(f"Zenoh bridge config updated.")

def create_zenoh_router_config_yaml(
    selected_robots: list[str],
    available_robots: dict[str, Robot],
    custom_addresses: list[str],
):
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



def _create_zenoh_bridge_config_json5(endpoints: list[str]) -> str:
    # Get the template directory path from the share directory
    template_dir = os.path.join(
        get_package_share_directory("tuda_workspace_scripts"), "templates"
    )
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("zenoh-bridge-config.json5")

    # Render the template with the endpoints list
    return template.render(endpoints=endpoints)


def print_discovery_config():
    print_info(f"RMW Implementation: {RMW}")
    if RMW == "rmw_zenoh_cpp":
        print_zenoh_discovery_config()
    elif RMW == "rmw_cyclonedds_cpp":
        print_zenoh_bridge_discovery_config()
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def print_zenoh_bridge_discovery_config():
    if os.path.exists(ZENOH_BRIDGE_CONFIG_URI):
        print_info(f"Configuration file: {ZENOH_BRIDGE_CONFIG_URI}")
        with open(ZENOH_BRIDGE_CONFIG_URI, "r") as file:
            print(file.read())
    else:
        print_warn(f"Configuration file not found: {ZENOH_BRIDGE_CONFIG_URI}")


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
