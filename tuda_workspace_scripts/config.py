from collections.abc import Iterator
from .workspace import get_workspace_root
import os
from typing import Any, Iterator
import yaml

# Use the environment variable TUDA_WSS_CONFIG to specify a config file.
# If not specified, default to WORKSPACE_ROOT/.config/tuda_workspace_scripts.yaml
CONFIG_FILE_PATH = os.getenv("TUDA_WSS_CONFIG", None)
if CONFIG_FILE_PATH is None:
    CONFIG_FILE_PATH = get_workspace_root()
    if CONFIG_FILE_PATH is not None:
        CONFIG_FILE_PATH += "/.config/tuda_workspace_scripts.yaml"


class Variable:
    name: str
    default: Any
    description: str
    choices: None | list[Any]

    def __init__(self, name, default=None, description="", choices=None) -> None:
        self.name = name
        self.default = default
        self.description = description
        self.choices = choices


class _ConfigVariables(dict):
    def __init__(self, config) -> None:
        super().__init__(config)

    def __getitem__(self, key):
        if key not in self:
            variable = load_variable(key)
            super().__setitem__(key, variable.default if variable is not None else None)
        return super().__getitem__(key)

    __getattr__ = __getitem__
    __setattr__ = dict.__setitem__


class Config(object):
    def __init__(self, path) -> None:
        self._path = path
        try:
            with open(path, "r") as f:
                self._config = yaml.safe_load(f)
        except FileNotFoundError:
            self._config = None
        if self._config is None:
            self._config = {}
        self.variables = _ConfigVariables(
            self._config["variables"] if "variables" in self._config else {}
        )

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            config = self._config
            config["variables"] = dict(self.variables)
            yaml.safe_dump(config, f)


def load_config() -> Config:
    return Config(CONFIG_FILE_PATH)


def load_variables() -> Iterator[Variable]:
    config_files = os.getenv("TUDA_WSS_CONFIGS")
    if config_files is None:
        return []
    config_files = config_files.split(os.pathsep)
    for path in config_files:
        if not os.path.exists(path):
            continue
        with open(path, "r") as f:
            config = yaml.safe_load(f)
            for variable in config["variables"]:
                yield Variable(**variable)


def load_variable(key) -> Variable | None:
    config_files = os.getenv("TUDA_WSS_CONFIGS")
    if config_files is None:
        return None
    for path in config_files.split(os.pathsep):
        if not os.path.exists(path):
            continue
        with open(path, "r") as f:
            config = yaml.safe_load(f)
            for var in config["variables"]:
                if var["name"] == key:
                    return Variable(**var)
    return None


class VariableChoicesCompleter:
    def __call__(self, **_):
        return [var.name for var in load_variables()]


class ValueChoicesCompleter:
    def __call__(self, parsed_args, **_):
        var = load_variable(parsed_args.VARIABLE)
        return var.choices if var.choices is not None else []
