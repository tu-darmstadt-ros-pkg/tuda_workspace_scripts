#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
import shlex
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.robots import *
from tuda_workspace_scripts.tmux import launch_tmux


class RemotePCChoicesCompleter:
    def __call__(self, **_):
        robots = load_robots()
        return list(robots.keys()) + [
            key for robot in robots.values() for key in robot.remote_pcs.keys()
        ]


def main():
    parser = argparse.ArgumentParser()
    target_arg = parser.add_argument(
        "TARGET", nargs=1, help="The robot or pc to ssh to."
    )
    target_arg.completer = RemotePCChoicesCompleter()
    parser.add_argument(
        "--use-windows",
        action="store_true",
        default=False,
        help="Use windows instead of panes.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output.",
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    robots = load_robots()
    target = args.TARGET[0]
    remote_pc = None
    if target in robots:
        robot_name = target
        robot = robots[target]
        remote_pc = "all"
        if args.verbose:
            print("Target is a robot, using all remote PCs.")
    else:
        for robot in robots.values():
            if target in robot.remote_pcs:
                robot_name = robot.name
                remote_pc = target
                break
        if remote_pc is None:
            print_error(f"PC or robot {target} not found!")
            exit(1)
        if args.verbose:
            print(f"Target is a remote PC on robot {robot_name}.")

    if robot_name not in robots:
        print_error(f"Robot {robot_name} not found!")
        exit(1)

    if remote_pc == "all":
        try:
            commands = dict(robot.get_shell_commands("ssh"))
        except ValueError:
            print_error(f"Command ssh not found for any PC on robot {robot_name}!")
            exit(1)
    else:
        if not robot.remote_pcs[remote_pc].has_command("ssh"):
            print_error(
                f"Command ssh not found for PC {remote_pc} on robot {robot_name}!"
            )
            exit(1)
        commands = [robot.get_shell_command(remote_pc, "ssh", {"robot": robot_name})]

    # If single command, launch directly replacing the current process
    # Otherwise, use tmux to split the terminal
    if len(commands) == 1:
        if args.verbose:
            print(f"Executing command: {commands[0]}")
        args = shlex.split(commands[0])
        os.execvp(args[0], args)
    else:
        launch_tmux(
            commands,
            use_windows=args.use_windows,
            keep_open_duration=None,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl-C received! Exiting...")
        exit(0)
