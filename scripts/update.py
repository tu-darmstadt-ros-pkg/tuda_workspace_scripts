#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.scripts import get_hooks_for_command
import importlib
import subprocess
from os.path import basename
from os import environ


def load_method_from_file(file_path: str, method_name: str):
    spec = importlib.util.spec_from_file_location("module.name", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, method_name)


def main(
    no_sudo: bool = False, default_yes: bool = False, verbose: bool = False
) -> int:
    # Get hooks and sort them by their filename
    hooks = list(sorted(get_hooks_for_command("update"), key=basename))
    args = []
    if no_sudo:
        args.append("--no-sudo")
    if default_yes:
        args.append("-y")

    success = True
    for script in hooks:
        if verbose:
            print_info(f"Running update hook: {script}")
        if script.endswith(".py"):
            update = load_method_from_file(script, "update")
            success &= update(no_sudo=no_sudo, default_yes=default_yes)
        elif script.endswith(".bash"):
            proc = subprocess.run(["bash", script] + args)
            success &= proc.returncode == 0
        elif script.endswith(".sh"):
            proc = subprocess.run(["sh", script] + args)
            success &= proc.returncode == 0
        else:
            print_error(f"Unknown file type for hook: {script}")
            success &= False

    if not success:
        print_error("Some updates failed!")
        return 1
    print_success("All updates succeeded!")
    return 0


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--no-sudo",
            action="store_true",
            help="Skip update commands requiring sudo privileges.",
        )
        parser.add_argument(
            "--default-yes",
            "-y",
            action="store_true",
            help="Answer yes to all questions.",
        )
        parser.add_argument(
            "--verbose",
            "-v",
            action="store_true",
            help="Print verbose output.",
        )
        argcomplete.autocomplete(parser)
        args = parser.parse_args()
        verbose = args.verbose or environ.get("TUDA_WSS_DEBUG") == "1"
        result = main(
            no_sudo=args.no_sudo, default_yes=args.default_yes, verbose=verbose
        )
        exit(result or 0)
    except KeyboardInterrupt:
        print_error("Ctrl+C received! Exiting...\033[0m")
        exit(0)
