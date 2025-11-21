#!/usr/bin/env python3
from pyroute2 import IPRoute
import subprocess

def on_discovery_updated(robots, selected_robots, **_):
    ip = IPRoute()

    routes_to_add = ""

    for robot_name, robot in robots.items():
        if robot_name not in selected_robots:
            continue

        for pc_name in robot.remote_pcs:
            pc = robot.remote_pcs[pc_name]
            if not pc.address:
                print(f"Robot {pc.name} has no address configured for its , skipping pc")
                continue
            else:
                pc_ip = pc.address
                netmask = pc.netmask
                break
        
        if not pc_ip:
            print(f"Robot {robot_name} has no address configured for its pcs, skipping robot")
            continue
        parts = pc_ip.split('.')[:-1]
        net_ip = '.'.join(parts + ['0'])
        host_ip = '.'.join(parts[:2] + ['0', parts[2]])
        
        existing_routes = ip.get_routes(dst=net_ip + '/' + str(netmask))

        valid_route = False
        if existing_routes:
            gateway = next((value for key, value in existing_routes[0]['attrs'] if key == 'RTA_GATEWAY'), None)
            if gateway == host_ip:
                valid_route = True
            
        if not valid_route:
            print(f"Adding route to {net_ip}/{netmask} via host pc")
            command = f"ip.route('add', dst='{net_ip}/{netmask}', gateway='{host_ip}')\n"
            routes_to_add += command
    
    if routes_to_add != "":
        ip_route_code = f"""from pyroute2 import IPRoute
ip = IPRoute()
{routes_to_add}
"""
        print("Privilege escalation required to add routes, running commands with sudo...")
        subprocess.run(
                ["sudo", "python3", "-c", ip_route_code],
                check=True
        )
