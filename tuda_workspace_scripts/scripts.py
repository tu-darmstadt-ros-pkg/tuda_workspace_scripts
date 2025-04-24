import os
import subprocess
from typing import Generator
import importlib.util


def get_scripts_dirs() -> Generator[str, None, None]:
    for dir in os.environ.get("TUDA_WSS_SCRIPTS", "").split(os.pathsep):
        if os.path.isdir(dir):
            yield dir


def get_hook_dirs() -> Generator[str, None, None]:
    for script_dir in get_scripts_dirs():
        hook_dir = os.path.join(script_dir, "hooks")
        if os.path.isdir(hook_dir):
            yield hook_dir


def get_hooks_for_command(command: str) -> Generator[str, None, None]:
    scripts = set()  # Collect scripts to avoid duplicates
    for hook_dir in get_hook_dirs():
        command_hook = os.path.join(hook_dir, command)
        if os.path.isdir(command_hook):
            for script in os.listdir(command_hook):
                if script in scripts:
                    continue
                script_path = os.path.join(command_hook, script)
                if os.path.isfile(script_path):
                    scripts.add(script)
                    yield script_path


def load_method_from_file(file_path: str, method_name: str):
    spec = importlib.util.spec_from_file_location("module.name", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, method_name)
