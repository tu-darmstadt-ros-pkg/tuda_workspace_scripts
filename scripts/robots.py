#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
import shlex
from tuda_workspace_scripts.print import *
from tuda_workspace_scripts.robots import *
from tuda_workspace_scripts.tmux import launch_tmux


class RobotChoicesCompleter:
    def __call__(self, **_):
        return [var for var in load_robots()]


class RemotePCChoicesCompleter:
    def __call__(self, parsed_args, **_):
        robot_arg = parsed_args.ROBOT[0]
        try:
            robot = get_robot(robot_arg)
            return list(robot.remote_pcs.keys()) + ["all"]
        except ValueError:
            return []


class RobotCommandCompleter:
    def __call__(self, parsed_args, **_):
        commands = set()
        robot_arg = parsed_args.ROBOT[0]
        remote_pc_arg = parsed_args.REMOTE_PC[0]

        try:
            robot = get_robot(robot_arg)
            for pc in robot.remote_pcs.values():
                if remote_pc_arg != "all" and pc.name != remote_pc_arg:
                    continue
                for command in pc.commands:
                    commands.add(command.name)
        except ValueError:
            pass
        return list(commands)


def main():
    parser = argparse.ArgumentParser()
    robots = load_robots()
    robot_arg = parser.add_argument(
        "ROBOT", nargs=1, choices=robots.keys(), help="The robot to communicate with."
    )
    robot_arg.completer = RobotChoicesCompleter()
    remote_pc_arg = parser.add_argument(
        "REMOTE_PC", nargs=1, help="The pc(s) to run this command on."
    )
    remote_pc_arg.completer = RemotePCChoicesCompleter()
    command_arg = parser.add_argument(
        "COMMAND", nargs=1, help="The command to execute."
    )
    command_arg.completer = RobotCommandCompleter()
    parser.add_argument(
        "--keep_open_duration",
        type=int,
        default=5,
        help="Time in seconds to keep each pane or window open after the command completes. Defaults to 5.",
    )
    parser.add_argument(
        "--use-windows",
        action="store_true",
        default=False,
        help="Use windows instead of panes.",
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    robot_name = args.ROBOT[0]
    remote_pc = args.REMOTE_PC[0]
    command_name = args.COMMAND[0]

    if robot_name not in robots:
        print_error(f"Robot {robot_name} not found!")
        exit(1)
    robot = robots[robot_name]
    if remote_pc != "all" and remote_pc not in robot.remote_pcs:
        print_error(f"PC {remote_pc} not found for robot {robot_name}!")
        exit(1)

    if remote_pc == "all":
        try:
            commands = dict(robot.get_shell_commands(command_name))
        except ValueError:
            print_error(
                f"Command {command_name} not found for any PC on robot {robot_name}!"
            )
            exit(1)
    else:
        if not robot.remote_pcs[remote_pc].has_command(command_name):
            print_error(
                f"Command {command_name} not found for PC {remote_pc} on robot {robot_name}!"
            )
            exit(1)
        commands = [
            robot.get_shell_command(remote_pc, command_name, {"robot": robot_name})
        ]

    # If single command, launch directly replacing the current process
    # Otherwise, use tmux to split the terminal
    if len(commands) == 1:
        args = shlex.split(commands[0])
        os.execvp(args[0], args)
    else:
        launch_tmux(
            commands,
            use_windows=args.use_windows,
            keep_open_duration=args.keep_open_duration,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl-C received! Exiting...")
        exit(0)
