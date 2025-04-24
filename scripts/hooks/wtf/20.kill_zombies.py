#!/usr/bin/env python3
from psutil import process_iter
from tuda_workspace_scripts.print import confirm, print_header, print_info, print_error


def fix() -> int:
    print_header("Checking for zombies")
    gz_processes = []
    for p in process_iter(["pid", "name", "cmdline"]):
        if p.info["name"] == "ruby" and p.info["cmdline"][0].startswith("gz sim"):
            gz_processes.append(p)
    if len(gz_processes) == 0:
        print_info("No zombies found.")
        return 0
    if confirm("Found gazebo processes. Are you expecting gazebo to be running?"):
        return 0
    print_error("Found gazebo zombies.")
    for p in gz_processes:
        p.kill()
    print_info("Killed all zombies.")
    return 1


if __name__ == "__main__":
    fix()
