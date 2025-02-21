#!/usr/bin/env python3
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.workspace import get_workspace_root
import subprocess
import signal
import os

try:
    import git
except ImportError:
    print(
        "GitPython is required! Install using 'pip3 install --user gitpython' or 'apt install python3-git'"
    )
    raise


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

# We ignore all args here, because we don't need them
def update(**_) -> bool:
    """
    Update all git repositories in the workspace.
    """
    ws_root_path = get_workspace_root()
    if ws_root_path is None:
        print_workspace_error()
        return False
    ws_src_path = os.path.join(ws_root_path, "src")

    def update_repo(path) -> bool:
        try:
            repo = git.Repo(path, search_parent_directories=True)
            relative_path = path.replace(f"{ws_src_path}/", "")
            if not repo.head.is_valid():
                branch_name = "unknown"
            elif repo.head.is_detached:
                branch_name = f"detached at {repo.head.commit}"
            else:
                branch_name = repo.head.ref.name
            print_subheader(
                f"Updating {relative_path} {Colors.LPURPLE}({branch_name})"
            )
            if not repo.head.is_valid():
                print_warn("Repository has no valid HEAD. Not updating.")
                return True
            if repo.head.is_detached:
                print_info("Repository is in detached HEAD state. Not updating.")
                return True
            return launch_subprocess(["git", "pull"], cwd=path).returncode == 0
        except git.exc.InvalidGitRepositoryError:
            print_error("Failed to obtain git info for: {}".format(path))
            return False
        except Exception as e:
            print_error("Error while updating '{}':\n{}".format(path, str(e)))
            return False

    def update_workspace(path) -> bool:
        if not os.path.isdir(path):
            return True
        try:
            subdirs = os.listdir(path)
        except Exception as e:
            print_error("Error while scanning '{}'!\nMessage: {}".format(path, str(e)))
            return True
        if ".git" in subdirs:
            return update_repo(path)
        result = True
        for subdir in sorted(subdirs):
            result &= update_workspace(os.path.join(path, subdir))
        return result

    print_header(f"Updating workspace {ws_src_path}")
    return update_workspace(ws_src_path)


if __name__ == "__main__":
    update()
