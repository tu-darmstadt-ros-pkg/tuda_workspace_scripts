#!/usr/bin/env python3
try:
    from colcon_core.plugin_system import get_package_identification_extensions
except ImportError:
    from colcon_core.package_identification import get_package_identification_extensions
from colcon_core.package_identification import identify, IgnoreLocationException
from tuda_workspace_scripts.print import print_header, print_info, print_warn
from tuda_workspace_scripts.workspace import get_packages_in_workspace, get_package_path
import re
import os


def fix() -> tuple[int, int]:
    print_header("Checking ament_cmake packages for export")
    identification_extensions = get_package_identification_extensions()
    packages = get_packages_in_workspace()
    buildtool_regex = re.compile(
        r"<buildtool_depend>\s*([a-z0-9_]+)\s*</buildtool_depend>"
    )
    count_warnings = 0
    for package in packages:
        try:
            path = get_package_path(package)
            result = identify(identification_extensions, path)
            if result.type != "ros.catkin":
                continue
            with open(os.path.join(path, "package.xml"), "r") as f:
                content = f.read()

            is_ament_cmake = any(
                [
                    match.group(1) == "ament_cmake"
                    for match in buildtool_regex.finditer(content)
                ]
            )
            if is_ament_cmake:
                print_warn(
                    f"Package {package} is ament_cmake but has no export tag. This leads to the package being incorrectly identified as catkin package which can cause further issues."
                )
                count_warnings += 1
        except IgnoreLocationException:
            continue
    if count_warnings == 0:
        print_info("All good.")
    return count_warnings, 0


if __name__ == "__main__":
    fix()
