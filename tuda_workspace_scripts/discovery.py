from .workspace import get_workspace_root
from robots import DiscoveryServer, load_robots
from tuda_workspace_scripts import print_warn
from ros2cli.node.daemon import is_daemon_running, spawn_daemon, shutdown_daemon
import os
import xml.etree.ElementTree as ET


# dedicated place for temporary files
tmp_directory = "/tmp/tuda_wss"
discovery_xml_path = os.path.join(tmp_directory, "discovery_client.xml")
super_client_xml_path = os.path.join(tmp_directory, "super_client.xml")

def create_discovery_xml(discovery_server_names: list[str]):
  if not os.path.exists(tmp_directory):
    os.mkdir(tmp_directory)

  discovery_servers = []
  robots = load_robots()
  for name in discovery_server_names:
    if name == "local_server":
      discovery_servers.append(DiscoveryServer("127.0.0.1", 11811, "44.53.00.5f.45.50.52.4f.53.49.4d.41"))
    elif name == "all":
      for __, robot in robots.items():
        discovery_servers.extend(robot.discovery_servers)
      # This is currently unclean because there should be a better toggle/standard
      discovery_servers.append(DiscoveryServer("127.0.0.1", 11811, "44.53.00.5f.45.50.52.4f.53.49.4d.41"))
      # No servers can be added anymore, so all other arguments are ignored
      break
    else:
      # Only adding if there is exactly one robot, else the robots xml is probably misformed ore the robot is missing.
      # check for robots with correct name
      filtered_robots = []
      for robot_name, robot_data in robots.items():
        if robot_name == name:
          filtered_robots.append(robot_data)
      if len(filtered_robots) == 1:
        discovery_servers.extend(filtered_robots[0].discovery_servers)
      elif len(filtered_robots) == 0:
        print_warn(f"Couldn't find correct entry for {name} in robot configs. Please check if your selected robot is available.")
      else:
        print_warn(f"Found multiple robot entries for {name} in robot configs. Your configs seem to be misformed.")
  
  root = _create_dds_xml(discovery_servers)

  # pretty printing
  ET.indent(root, '    ')

  # Create temporary file so it is removed on reboot
  tree = ET.ElementTree(root)
  tree.write(discovery_xml_path, encoding="utf-8", xml_declaration=True)

  # Create Super client xml
  protocol = root.findall(f".//discoveryProtocol")[0]
  protocol.text = "SUPER_CLIENT"
  tree.write(super_client_xml_path, encoding="utf-8", xml_declaration=True)

def _create_dds_xml(discovery_servers: list[DiscoveryServer]) -> ET.Element:
  # There is options to parse more settings here
  root = ET.Element("dds")
  namespace = "http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles"
  profiles = ET.SubElement(root, "profiles", xmlns=namespace)
  participant = ET.SubElement(profiles, "participant", 
                              profile_name="discovery_server_profile", 
                              is_default_profile="true")
  rtps = ET.SubElement(participant, "rtps")
  builtin = ET.SubElement(rtps, "builtin")
  discovery_config = ET.SubElement(builtin, "discovery_config")
  discovery_protocol = ET.SubElement(discovery_config, "discoveryProtocol")
  discovery_protocol.text = "CLIENT"

  discovery_server_list = ET.SubElement(discovery_config, "discoveryServersList")

  for discovery_server in discovery_servers:
    discovery_server_list.append(_create_client_xml(discovery_server))

  return root


def _create_empty_discovery_xml() -> ET.Element:
  if not os.path.exists(tmp_directory):
    os.mkdir(tmp_directory)

  root = ET.Element("dds")
  namespace = "http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles"
  profiles = ET.SubElement(root, "profiles", xmlns=namespace)
  ET.SubElement(profiles, "participant", 
                              profile_name="empty_profile", 
                              is_default_profile="true")
  
  return root
  

def _create_client_xml(server: DiscoveryServer) -> ET.Element:
  discovery_server = ET.Element("RemoteServer", prefix=server.guid_prefix)
  meta_traffic = ET.SubElement(discovery_server, "metatrafficUnicastLocatorList")
  locator = ET.SubElement(meta_traffic, "locator")
  udpv4 = ET.SubElement(locator, "udpv4")
  address = ET.SubElement(udpv4, "address")
  address.text = server.address
  port = ET.SubElement(udpv4, "port")
  port.text = str(server.port)

  return discovery_server


def disable_discovery_xml():
  # Create empty file so it is automatically changed in all terminals
  root = _create_empty_discovery_xml()
  # pretty printing
  ET.indent(root, '    ')
  tree = ET.ElementTree(root)
  # Writing empty xmls so default discovery settings are used
  tree.write(discovery_xml_path, encoding="utf-8", xml_declaration=True)
  tree.write(super_client_xml_path, encoding="utf-8", xml_declaration=True)
  print(super_client_xml_path)
  print(discovery_xml_path)


def restart_super_client_daemon():
  os.environ["FASTRTPS_DEFAULT_PROFILES_FILE"] = super_client_xml_path
  if is_daemon_running([]):
    if not shutdown_daemon([], timeout=10):
      print_warn("daemon shutdown failed")
  if not spawn_daemon([], timeout=10):
    print_warn("daemon spawn failed")
