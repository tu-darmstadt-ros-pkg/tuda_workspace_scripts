#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.scripts import get_hooks_for_command
import importlib


def load_method_from_file(file_path: str, method_name: str):
    spec = importlib.util.spec_from_file_location("module.name", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, method_name)


def main() -> int:
    hooks = list(sorted(get_hooks_for_command("update")))
    success = True
    for script in hooks:
        update = load_method_from_file(script, "update")
        success &= update()
    if not success:
        print_error("Some updates failed!")
        return 1
    print_success("All updates succeeded!")
    return 0


if __name__ == "__main__":
    try:
        exit(main() or 0)
    except KeyboardInterrupt:
        print_error("Ctrl+C received! Exiting...")
        exit(0)
