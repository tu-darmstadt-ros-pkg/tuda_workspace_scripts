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


class HookExecutionResult(object):
    def __init__(self, exit_code: int, result: any):
        self.success = exit_code == 0
        self.result = result
        self.exit_code = exit_code

    def __str__(self):
        return f"Success: {self.success}, Result: {self.result}"


def execute_hook(
    hook: str,
    py_method_name: str,
    cwd: None | str = None,
    capture_output: bool = False,
    **kwargs,
) -> HookExecutionResult:
    """
    Execute a hook script with the given method name and arguments.
    The hook can be a Python script or a bash/sh script.
    If the hook is a Python script, the method py_method_name will be called with the provided kwargs.
    If the hook is a bash/sh script, it will be executed with the provided kwargs as key=value, e.g., "no_sudo=True".

    @raises ValueError: If the hook is not a Python or bash/sh script.
    """
    result = None
    if hook.endswith(".py"):
        try:
            method = load_method_from_file(hook, py_method_name)
            result = HookExecutionResult(0, method(**kwargs))
        except Exception as e:
            result = HookExecutionResult(1, str(e))
    elif hook.endswith(".bash") or hook.endswith(".sh"):
        # Execute the bash script with the provided arguments
        launch_args = list(f"{k}={v}" for k, v in kwargs.items())
        executable = "bash" if hook.endswith(".bash") else "sh"
        proc = subprocess.run(
            [executable, hook] + list(launch_args),
            stdout=subprocess.PIPE if capture_output else None,
            text=True,
            cwd=cwd,
        )
        result = HookExecutionResult(proc.returncode, proc.stdout)
    else:
        raise ValueError(f"Unknown file type for hook: {hook}")

    return result
