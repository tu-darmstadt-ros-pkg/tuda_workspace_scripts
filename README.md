# The TUDA Workspace Scripts

The TUDA workspace scripts add convenience scripts to manage a workspace and robots.

## Extending

### Custom prefix

If you prefer a different prefix instead of `tuda_wss`, you can set the `TUDA_WSS_PREFIX` environment
variable before sourcing the workspace containing `tuda_wss`.
This makes all `tuda_wss` commands also available under the alias specified in `TUDA_WSS_PREFIX`.

Example

```bash
export TUDA_WSS_PREFIX=hector
source /path/to/workspace/install/setup.bash
hector status
```

### Add commands

You can add commands either in this repository in the scripts folder or as an overlay in a separate package.
Either way scripts have to be put in a scripts directory and three command forms are supported:

* Executable python files, e.g. command.py: The extension is stripped and the python file executed
* Executable bash/sh files, e.g. command.bash: The extension is stripped and the bash script is executed 
* Non-executable bash/sh files, e.g. command.bash: The file is sourced and may modify the environment

In each case the additional arguments are forwarded to the command.

### Overlay

To create an overlay, create a new package with a scripts folder, create an env-hook-in-file `20.setup.dsv.in` with the following content:

```dsv
prepend-non-duplicate;TUDA_WSS_SCRIPTS;share/@PROJECT_NAME@/scripts
```

> [!NOTE]
> The number should be between 10 and 50 if you want it to be sourced before the command is registered or greater than 50 and smaller than 80 if it should be sourced after.

In your `CMakeLists.txt` install the folder and file as follows:

```cmake
if (WIN32)
  message(FATAL_ERROR "Windows is currently not supported! Feel free to add support :)")
else()
  ament_environment_hooks(20.setup.dsv.in)
endif()

install(DIRECTORY scripts DESTINATION share/${PROJECT_NAME} USE_SOURCE_PERMISSIONS)
```

## Commands

All commands support autocompletion and have a `--help` option listing available options.

| Command |  Description |
| --- | --- |
| build | Build all (or the passed) packages in the workspace. Will automatically build in the workspace root and can be run form anywhere. Use `--this` to build the packages in the current directory. |
| cd PACKAGE | Go to the directory of the given package. |
| clean | Clean all (or the passed) packages. |
| cross_compile | Cross compiles a package for a given target architecture using the `--platform` argument. |
| discovery | Exports a discovery server xml for the selected robot. |
| init | Initializes the current directory as workspace root. Has to be run once per workspace. |
| status | Prints any changes in the git repositories in the workspace. |
| test | Builds and runs the tests for all (or the passed) packages. |
| wtf | Runs some common error checks and fixes in your environment. E.g. if gazebo keeps zombies alive. |

## Python Library

In your commands, you can use the `tuda_workspace_scripts` python module which contains a `print` and a `workspace` submodule.

### config

Provides a workspace configuration mechanism. You can use `load_config()` to obtain the current config.
Variables can be provided using a yaml file (see `config.yaml`), the files have to be registered using

```dsv
prepend-non-duplicate;TUDA_WSS_CONFIGS;share/@PROJECT_NAME@/config.yaml
```

The registered variables can be set using the `tuda_wss config` command.

### print

Provides helpers for printing.

* Colored output using `print_color`, `print_info`, `print_warn` and `print_error`
* Yes/No confirm questions on terminal with `confirm`
* Bounded logging: A limited number of status info lines are writen to the output. When line_count is reached old lines are overwritten.

### workspace

| Command | Description |
| --- | --- |
| get_workspace_root |  Locate workspace directory. If a path is passed, will search the path upwards to find the workspace root, otherwise fill first use the current path and fall back to automatic detection. Returns None if not workspace root was found. |
| find_packages_in_directory | Find all packages contained in the given path recursively and returns their names. |
| find_package_containing | Find the name of the package that contains the given path or None if the path is not in a package. |
| get_packages_in_workspace | Finds all packages in the given workspace. If no workspace is given, it automatically determines the workspace. |
| PackageChoicesCompleter | A choices completer for argcomplete offering the packages in a given path for completion. |
