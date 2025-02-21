import os
import yaml
from .print import confirm, print_warn
from .robots import Robot, ZenohRouter, load_robots
from .workspace import get_workspace_root

ws_root = get_workspace_root()
if not ws_root:
    raise RuntimeError("Workspace root not found")
RMW: str | None = os.getenv("RMW_IMPLEMENTATION", None)
ZENOH_ROUTER_CONFIG_PATH: str | None = os.getenv("ZENOH_ROUTER_CONFIG_URI", None)


def create_discovery_config(selected_robots: list[str], custom_addresses: list[str]):
    available_robots = load_robots()

    if RMW == "rmw_zenoh_cpp":
        create_zenoh_router_config_yaml(
            selected_robots, available_robots, custom_addresses
        )
    elif RMW:
        raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
    else:
        raise RuntimeError("RMW_IMPLEMENTATION is not set.")


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

    routers.extend(ZenohRouter(address, "7447", "tcp") for address in custom_addresses)

    config = _create_zenoh_router_config_yaml(routers)
    print("Connecting to routers:")
    for router in config["connect"]["endpoints"]:
        print(" -", router)

    if os.path.isfile(ZENOH_ROUTER_CONFIG_PATH) and not confirm(
        "I will overwrite the existing zenoh router config. Continue?"
    ):
        return
    with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
        yaml.dump(config, file, default_flow_style=False)


def _create_zenoh_router_config_yaml(routers):
    config = {
        "mode": "router",
        "connect": {
            "endpoints": [router.get_zenoh_router_address() for router in routers]
        },
    }
    return config
