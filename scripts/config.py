#!/usr/bin/env python3
import argparse
import argcomplete
from tuda_workspace_scripts.config import (
    CONFIG_FILE_PATH,
    load_config,
    load_variable,
    load_variables,
    VariableChoicesCompleter,
    ValueChoicesCompleter,
)
from tuda_workspace_scripts.print import TableOutput, print_workspace_error
from tuda_workspace_scripts.workspace import get_workspace_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub_parsers = parser.add_subparsers(dest="command", help="The command to execute.")
    sub_parsers.add_parser("show", help="Show the current configuration.")
    sub_parsers.add_parser("list", help="List all variables.")
    get_parser = sub_parsers.add_parser("get", help="Get a variable.")
    get_parser.add_argument(
        "VARIABLE", help="The variable to get."
    ).completer = VariableChoicesCompleter()
    get_parser.add_argument(
        "--value-only",
        default=False,
        action="store_true",
        help="Only print the value of the variable.",
    )
    set_parser = sub_parsers.add_parser("set", help="Set a variable.")
    set_parser.add_argument(
        "VARIABLE", help="The variable to set."
    ).completer = VariableChoicesCompleter()
    set_parser.add_argument(
        "VALUE", help="The value to set."
    ).completer = ValueChoicesCompleter()
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if get_workspace_root() is None:
        print_workspace_error()
        exit(1)

    if args.command == "list":
        vars = load_variables()
        table = TableOutput(["Name", "Default", "Description"])
        for var in vars:
            table.add_row([var.name, str(var.default), var.description])
        table.print()

    config = load_config()
    if args.command is None or args.command == "show":
        print(f"Config path: {CONFIG_FILE_PATH}")
        print("Config:")
        if not any(config.variables):
            print(
                "  No variables set. Run tuda_wss config list to see all variables and their defaults."
            )
        for key, value in config.variables.items():
            print(f"  {key}: {value}")
    elif args.command == "get":
        var = load_variable(args.VARIABLE)
        if var is None:
            if not args.value_only:
                print(f"Variable {args.VARIABLE} does not exist.")
            exit(1)  # Exit with error code if variable does not exist.
        else:
            value = config.variables[var.name]
            if args.value_only:
                print(value)
            else:
                print(f"{var.name}: {value}")
                print("Description:")
                print(var.description or "No description.")
    elif args.command == "set":
        config.variables[args.VARIABLE] = args.VALUE
        config.save()
    elif args.command == "unset":
        del config.variables[args.VARIABLE]
        config.save()
