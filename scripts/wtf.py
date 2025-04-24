#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
import subprocess
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.scripts import get_hooks_for_command, load_method_from_file
from tuda_workspace_scripts.workspace import get_workspace_root

"""
This script runs all wtf scripts in the hooks/wtf folders of the TUDA_WSS_SCRIPTS environment variable.
A fix script needs to either be a python script with a fix method returning an integer
indicating the number of issues that were fixed, or a bash/sh script which should return the number
of issues that were fixed as exit code.
"""


def main():
    parser = argparse.ArgumentParser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args()
    if get_workspace_root() is None:
        print_workspace_error()
        return 1

    count_fixes = 0
    hooks = list(sorted(get_hooks_for_command("wtf")))
    # Collect all wtf scripts in hooks/wtf folders of TUDA_WSS_SCRIPTS environment variable
    for script in hooks:
        # Load script and run fix command and obtain result
        if script.endswith(".py"):
            fix = load_method_from_file(script, "fix")
            count_fixes += fix()
        elif script.endswith(".bash") or script.endswith(".sh"):
            executable = "bash" if script.endswith(".bash") else "sh"
            proc = subprocess.run([executable, script], cwd=get_workspace_root())
            count_fixes += proc.returncode
        else:
            print_error(f"Unknown file type for hook: {script}")
            continue
    if count_fixes > 0:
        print_success(f"{len(hooks)} checks have fixed {count_fixes} potential issues.")
    else:
        print_success(f"{len(hooks)} checks have found no potential issues.")


if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        print_warn("Stopping per user request.")
        print("Good bye.")
        exit(0)
