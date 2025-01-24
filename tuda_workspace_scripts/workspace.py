#!/usr/bin/env python3
try:
    from colcon_core.plugin_system import get_package_identification_extensions
except ImportError:
    from colcon_core.package_identification import get_package_identification_extensions
from colcon_core.package_identification import identify, IgnoreLocationException
import os


def get_workspace_root(directory=None) -> str | None:
    """
    The workspace root is the directory containing the src, install and build directories.
    :param directory: Directory from which to search the workspace root. If None will try to find from current and if that fails from the COLCON_PREFIX_PATH
    :return: The path to the workspace root or None if no workspace found.
    """
    if directory is None:
        root = get_workspace_root(os.getcwd())
        if root is not None:
            return root
        colcon_prefix_path = os.environ.get("COLCON_PREFIX_PATH", None)
        return (
            get_workspace_root(colcon_prefix_path)
            if colcon_prefix_path is not None
            else None
        )
    content = os.listdir(directory)
    if ".ros2_workspace" in content:
        return directory
    parent = os.path.dirname(directory)
    return None if parent == directory else get_workspace_root(parent)


def find_packages_in_directory(directory) -> list[str]:
    """
    :param directory: The directory to search for packages.
    :return: A list of package names found in the directory.
    """
    packages = []
    identification_extensions = get_package_identification_extensions()
    visited_paths = set()
    for dirpath, dirnames, _ in os.walk(directory, followlinks=True):
        real_dirpath = os.path.realpath(dirpath)
        if real_dirpath in visited_paths:
            del dirnames[:]
            continue
        visited_paths.add(real_dirpath)
        try:
            result = identify(identification_extensions, dirpath)
        except IgnoreLocationException:
            del dirnames[:]
            continue
        if result:
            packages.append(result)
            del dirnames[:]
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

    return [p.name for p in packages]


def find_package_containing(path, identification_extensions=None):
    """
    :param path: The path to search for a package.
    :param identification_extensions: The identification extensions to use. If None will use get_package_identification_extensions().
    :return: The name of the package containing the path or None if path is not in a package.
    """
    if identification_extensions is None:
        identification_extensions = get_package_identification_extensions()
    while path is not None and path != "/":
        try:
            result = identify(identification_extensions, path)
            if result:
                return result.name
        except IgnoreLocationException:
            pass
        path = os.path.realpath(os.path.dirname(path))
    return None


def get_packages_in_workspace(workspace_path=None):
    """
    Looks for packages in the src folder of a workspace.
    :param workspace_path: Path to the workspace root (The parent directory of the src folder).
        If None will use get_workspace_root() to try to find it.
    """
    if workspace_path is None:
        workspace_path = get_workspace_root()
        if workspace_path is None:
            return []
    return find_packages_in_directory(os.path.join(workspace_path, "src"))


def get_package_path(package_name, workspace_path=None):
    """
    :param package_name: The name of the package to find.
    :param workspace_path: Path to the workspace root (The parent directory of the src folder).
        If None will use get_workspace_root() to try to find it.
    :return: The path to the package or None if not found.
    """
    if workspace_path is None:
        workspace_path = get_workspace_root()
        if workspace_path is None:
            return None
    identification_extensions = get_package_identification_extensions()
    visited_paths = set()
    for dirpath, dirnames, _ in os.walk(workspace_path, followlinks=True):
        real_dirpath = os.path.realpath(dirpath)
        if real_dirpath in visited_paths:
            del dirnames[:]
            continue
        visited_paths.add(real_dirpath)
        try:
            result = identify(identification_extensions, dirpath)
        except IgnoreLocationException:
            del dirnames[:]
            continue
        if result:
            if result.name == package_name:
                return dirpath
            del dirnames[:]
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
    return None


def get_ament_prefix_path_without_packages(packages):
    ament_prefix_path = os.environ.get("AMENT_PREFIX_PATH", None)
    if ament_prefix_path is None:
        return None
    paths = ament_prefix_path.split(os.pathsep)
    paths = filter(lambda x: x.split(os.path.sep)[-1] not in packages, paths)
    return os.pathsep.join(paths)


def get_ament_prefix_path_without_workspace(workspace_root):
    ament_prefix_path = os.environ.get("AMENT_PREFIX_PATH", None)
    if ament_prefix_path is None:
        return None
    paths = ament_prefix_path.split(os.pathsep)
    paths = filter(lambda x: not x.startswith(workspace_root), paths)
    return os.pathsep.join(paths)


def get_cmake_prefix_path_without_packages(packages):
    cmake_prefix_path = os.environ.get("CMAKE_PREFIX_PATH", None)
    if cmake_prefix_path is None:
        return None
    paths = cmake_prefix_path.split(os.pathsep)
    paths = filter(lambda x: x.split(os.path.sep)[-1] not in packages, paths)
    return os.pathsep.join(paths)


def get_cmake_prefix_path_without_workspace(workspace_root):
    cmake_prefix_path = os.environ.get("CMAKE_PREFIX_PATH", None)
    if cmake_prefix_path is None:
        return None
    paths = cmake_prefix_path.split(os.pathsep)
    paths = filter(lambda x: not x.startswith(workspace_root), paths)
    return os.pathsep.join(paths)


class PackageChoicesCompleter:
    """
    Looks for packages in the src subdirectory of the workspace located at workspace_path.
    """

    def __init__(self, workspace_path):
        self.workspace_path = workspace_path

    def __call__(self, **kwargs):
        if self.workspace_path is None:
            return []
        return get_packages_in_workspace(self.workspace_path)


if __name__ == "__main__":
    print(get_workspace_root())
