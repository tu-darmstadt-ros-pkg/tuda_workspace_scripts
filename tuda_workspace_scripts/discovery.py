from robots import ZenohRouter, load_robots
from tuda_workspace_scripts import print_warn
import os
import yaml

CONFIG_DIR = os.path.expanduser("~/.config")
RMW = os.getenv("RMW_IMPLEMENTATION", None)
ZENOH_ROUTER_CONFIG_PATH = os.path.join(CONFIG_DIR, "zenoh_router_config.yaml")

def create_discovery_config(connections: list[str]):

  if not os.path.exists(CONFIG_DIR):
    os.mkdir(CONFIG_DIR)

  robots = load_robots()

  if RMW == "rmw_zenoh_cpp":
    create_zenoh_router_config_yaml(connections, robots)
  elif RMW:
    raise NotImplementedError(f"Discovery is not implemented for RMW {RMW}")
  else:
    raise RuntimeError("RMW_IMPLEMENTATION is not set.")


def create_zenoh_router_config_yaml(connections: list[str], robots: dict):
  routers = []

  # Always set localhost, even if the user did not specify it
  routers.append(ZenohRouter("localhost","7447","tcp"))

  for name in connections:
    if name == "off":
      break
    elif name == "all":
      for _, robot_data in robots.items():
        routers.extend(robot_data.zenoh_routers)
      break
    else:
      filtered_robots = []
      for robot_name, robot_data in robots.items():
        if robot_name == name:
          filtered_robots.append(robot_data)      
      if len(filtered_robots) == 1:
        routers.extend(filtered_robots[0].zenoh_routers)
      else:
        print_warn(f"Couldn't find correct entry for {name} in robot configs. Please check if your selected robot is available.")
  config = _create_zenoh_router_config_yaml(routers)
  print("Connecting to routers:")
  for router in config["connect"]["endpoints"]:
    print(" -", router)

  with open(ZENOH_ROUTER_CONFIG_PATH, "w") as file:
    yaml.dump(config, file, default_flow_style=False)


def _create_zenoh_router_config_yaml(routers):
    config = {
        "mode": "router",
        "connect": {
            "endpoints": [router.get_zenoh_router_address() for router in routers]
        }
    }
    return config