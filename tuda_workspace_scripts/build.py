from .config import load_config
from .print import confirm, print_error, print_info, StatusOutput
from .workspace import *
from ament_index_python import get_package_share_path
from datetime import datetime, timezone
from dateutil.parser import parse as parse_date
import os
import shlex
import shutil
import subprocess
import sys

try:
    import colcon_override_check
except ImportError:
    colcon_override_check = None


def build_packages(
    workspace_root: str,
    packages: list[str] | None = None,
    env: dict | None = None,
    build_type: str | None = None,
    no_deps: bool = False,
    continue_on_error: bool = False,
    build_tests: bool = False,
    mixin: list[str] = None,
    verbose: bool = False,
    build_base: str = "build",
    install_base: str = "install",
) -> int:
    os.chdir(workspace_root)
    arguments = []
    if build_base != "build":
        arguments += ["--build-base", build_base]
    if install_base != "install":
        arguments += ["--install-base", install_base]
    if colcon_override_check is not None and any(packages):
        arguments += ["--allow-overriding"] + packages
    if continue_on_error:
        arguments += ["--continue-on-error"]

    cmake_arguments = []
    if build_type is not None:
        cmake_arguments.append(f"-DCMAKE_BUILD_TYPE={build_type}")
    if build_tests:
        cmake_arguments.append("-DBUILD_TESTING=ON")
    if any(cmake_arguments):
        arguments += ["--cmake-args"] + list(
            map(lambda x: f"' {shlex.quote(x)}'", cmake_arguments)
        )
    if mixin and len(mixin) > 0:
        arguments += ["--mixin"] + mixin

    if any(packages):
        arguments += ["--packages-up-to"] if not no_deps else ["--packages-select"]
        arguments += packages

    print_info("Command:")
    print(f"colcon build {' '.join(arguments)}")
    print_info(f">>> Running in {workspace_root}")
    if verbose:
        os.environ["VERBOSE"] = "1"
        arguments += ["--event-handlers", "console_cohesion+", "console_direct+"]
    command = subprocess.run(
        f'colcon build {" ".join(arguments)}',
        stdout=sys.stdout,
        stderr=sys.stderr,
        shell=True,
        env=env,
    )
    return command.returncode


def clean_logs(workspace_root, packages=None, force=False):
    original_path = os.getcwd()
    os.chdir(workspace_root)
    if packages is not None and any(packages):
        print_error("--logs and packages are not compatible!")
        os.chdir(original_path)
        return 1
    print("  {}/log".format(os.getcwd()))
    if force or confirm("Continue?"):
        shutil.rmtree("log", ignore_errors=True)
    else:
        print_info("Not deleted.")

    os.chdir(original_path)


def clean_packages(
    workspace_root,
    packages,
    force=False,
    build_base: str = "build",
    install_base: str = "install",
) -> bool:
    original_path = os.getcwd()
    os.chdir(workspace_root)
    try:
        print("I will delete:")
        if any(packages):
            print(f'  {os.getcwd()}/{build_base}/{{{",".join(packages)}}}')
            print(f'  {os.getcwd()}/{install_base}/{{{",".join(packages)}}}')
        else:
            print(f"  {os.getcwd()}/{build_base}")
            print(f"  {os.getcwd()}/{install_base}")
            print(f"  {os.getcwd()}/log")

        if not force and not confirm("Continue?"):
            print_info("Not deleted.")
            return False

        if any(packages):
            for package in packages:
                shutil.rmtree(f"{build_base}/{package}", ignore_errors=True)
                shutil.rmtree(f"{install_base}/{package}", ignore_errors=True)
            ament_prefix_path = get_ament_prefix_path_without_packages(packages)
            cmake_prefix_path = get_cmake_prefix_path_without_packages(packages)
            print_info(f">>> {len(packages)} package cleaned.")
        else:
            shutil.rmtree(build_base, ignore_errors=True)
            shutil.rmtree(install_base, ignore_errors=True)
            shutil.rmtree("log", ignore_errors=True)
            ament_prefix_path = get_ament_prefix_path_without_workspace(workspace_root)
            cmake_prefix_path = get_cmake_prefix_path_without_workspace(workspace_root)
            print_info(f">>> All packages cleaned.")

        if ament_prefix_path is not None:
            os.environ["AMENT_PREFIX_PATH"] = ament_prefix_path
        if cmake_prefix_path is not None:
            os.environ["CMAKE_PREFIX_PATH"] = cmake_prefix_path
        print()
        return True
    finally:
        os.chdir(original_path)


# docker run --rm -it -v ~/workspaces/noetic/src:/workspace/src:ro -v /tmp/install:/workspace/install:rw --env ROS_DISTRO=noetic --platform arm64 cross-compile-arm64 workspace_scripts


def cross_compile(
    packages: str | list[str],
    ros_distro: str,
    platform: str,
    output_base_dir: str,
    output_dir: str | None = None,
    build_type: str = "RelWithDebInfo",
    clean: bool = False,
    no_cache: bool = False,
    rebuild: bool = False,
    pull: bool = False,
    base_image: str | None = None,
) -> bool:
    import docker

    # if packages is iterable, join them
    if isinstance(packages, list):
        packages = " ".join(packages)
    platform_cleaned = platform.replace(":", "_").replace("/", "_")
    if output_dir is None:
        output_dir = output_base_dir
        output_dir = os.path.join(output_dir, ros_distro, platform_cleaned)
    os.makedirs(output_dir, exist_ok=True)
    if base_image is None:
        tag = f"cross-compile-{ros_distro}-{platform_cleaned}"
        print_info(f">>> Obtain image for {ros_distro} on {platform}")
    else:
        base_image_cleaned = base_image.replace(":", "_").replace("/", "_")
        tag = f"cross-compile-{base_image_cleaned}-{platform_cleaned}"
        print_info(f">>> Obtain image based on {base_image} for {platform}")
    docker_client = docker.from_env()
    if not rebuild:
        try:
            image = docker_client.images.get(tag)
            created = (
                datetime.now(timezone.utc)
                if "Created" not in image.attrs
                else parse_date(image.attrs["Created"])
            )
            if (datetime.now(timezone.utc) - created).days > 14:
                print("Container might be outdated. Rebuilding without cache...")
                rebuild = True
                no_cache = True
        except docker.errors.ImageNotFound:
            rebuild = True
    if rebuild:
        path = get_package_share_path("tuda_workspace_scripts") / "docker/cross_compile"
        if not os.path.isfile(path / "Dockerfile"):
            raise RuntimeError(f"Could not find Dockerfile in {path}")
        if base_image is not None:
            print_info(f">>> Pulling {base_image}")
            result = docker_client.api.pull(
                base_image, platform=platform, stream=True, decode=True
            )
            # Compute total progress from individual progress
            progress = {}
            current = 0
            total = 0
            ids = set()
            for item in result:
                if "id" in item:
                    ids.add(item["id"])
                if "progress" in item:
                    text = item["progress"].strip()
                    detail = item["progressDetail"]
                    if "current" in detail:
                        progress[item["id"]] = {
                            "current": detail["current"],
                            "total": detail["total"],
                        }
                        current = (
                            sum([p["current"] for p in progress.values()]) / 1024 / 1024
                        )
                        total = (
                            sum([p["total"] for p in progress.values()]) / 1024 / 1024
                        )
                    print(
                        f"{int(current / total * 100)}% ({int(current)}MB / {int(total)}MB) [{len(progress)}/{len(ids)} Layers]",
                        end="\r",
                    )
                if "errorDetail" in item:
                    print("\033[K" + item["errorDetail"]["message"], file=sys.stderr)
                    return False
            print("\033[KDone.")
        print_info(">>> Building image")
        result = docker_client.api.build(
            decode=True,
            path=path.as_posix(),
            tag=tag,
            buildargs={
                "BASE_IMAGE": base_image,
                "ROS_DISTRO": ros_distro,
                "USER_ID": f"{os.getuid()}",
                "GROUP_ID": f"{os.getgid()}",
            },
            platform=platform,
            pull=pull,
            rm=True,
            forcerm=True,
            nocache=no_cache,
            use_config_proxy=True,
        )

        output = StatusOutput(12)
        full_log = ""
        for item in result:
            if "stream" in item:
                text = item["stream"].strip()
                if text:
                    full_log += text + "\n"
                    output.status(text)
            if "errorDetail" in item:
                output.clear()
                print(full_log)
                print_error(item["errorDetail"]["message"])
                return False
        output.clear()
        print(f"Done. Built image as {tag}")
    else:
        print(f"Using existing image {tag}")
    print_info(f">>> Cross-compiling {packages}")
    output = StatusOutput(10)
    container = None
    try:
        tmp_path = f"/tmp/tudawss/{tag}"
        if clean:

            def ignore_file_not_found(func, path, exc_info):
                if isinstance(exc_info[1], FileNotFoundError):
                    return
                func(path)

            shutil.rmtree(f"{tmp_path}/build", onexc=ignore_file_not_found)
            shutil.rmtree(f"{tmp_path}/devel", onexc=ignore_file_not_found)
            shutil.rmtree(f"{tmp_path}/install", onexc=ignore_file_not_found)
            shutil.rmtree(f"{tmp_path}/log", onexc=ignore_file_not_found)
        os.makedirs(f"{tmp_path}/build", exist_ok=True)
        os.makedirs(f"{tmp_path}/devel", exist_ok=True)
        os.makedirs(f"{tmp_path}/install", exist_ok=True)
        os.makedirs(f"{tmp_path}/log", exist_ok=True)
        container = docker_client.containers.run(
            tag,
            command=f"{packages}",
            volumes={
                os.path.join(get_workspace_root(), "src"): {
                    "bind": "/workspace/src",
                    "mode": "ro",
                },
                f"{tmp_path}/build": {
                    "bind": "/workspace/build",
                    "mode": "rw",
                },
                f"{tmp_path}/devel": {
                    "bind": "/workspace/devel",
                    "mode": "rw",
                },
                f"{tmp_path}/install": {
                    "bind": "/workspace/install",
                    "mode": "rw",
                },
                f"{tmp_path}/log": {
                    "bind": "/workspace/log",
                    "mode": "rw",
                },
                f"{tmp_path}/log": {
                    "bind": "/workspace/logs",
                    "mode": "rw",
                },
            },
            environment={"BUILD_TYPE": build_type},
            platform=platform,
            detach=True,
            stdout=True,
            stderr=True,
        )
        for line in container.logs(stream=True):
            text: str = line.decode("utf-8").strip()
            if ">>> Building workspace" in text:
                output.clear()
                output.disable_overwrite()
            if text:
                output.status(text)
        result = container.wait()
        if result["StatusCode"] != 0:
            print_error(
                f"Cross-compilation failed with exit code {result['StatusCode']}"
            )
            return False
        print_info(f">>> Copying results")
        # Copy install folder to workspace
        shutil.copytree(f"{tmp_path}/install", output_dir, dirs_exist_ok=True)
        print(f"Copied build results to {output_dir}")
    except docker.errors.ContainerError as e:
        print_error(f"Failed to cross-compile {packages}:")
        print(e.stderr.decode("utf-8"), file=sys.stderr)
        return False
    except KeyboardInterrupt:
        if container is not None:
            container.kill()
            print_info("Container killed.")
    finally:
        if container is not None:
            container.remove()
    return True
