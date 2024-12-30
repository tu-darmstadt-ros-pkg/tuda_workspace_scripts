#!/usr/bin/env python3
from tuda_workspace_scripts.print import print_header, print_error
import subprocess
import signal
import os


def launch_subprocess(command, cwd=None, stdout=None, stderr=None):
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            preexec_fn=os.setpgrp,
        )
        process.wait()
        return process
    except KeyboardInterrupt:
        if process is not None:
            process.send_signal(signal.SIGINT)
            if process.wait(15) is None:
                print_error("Update did not exit in time! Terminating...")
                process.terminate()
        raise


def update() -> bool:
    print_header("Update system packages")
    update = launch_subprocess(["sudo", "apt", "update"])
    upgrade = launch_subprocess(["sudo", "apt", "upgrade", "-y"])
    return update.returncode == 0 and upgrade.returncode == 0


if __name__ == "__main__":
    update()
