#!/bin/bash

source $ROSWSS_ROOT/setup.bash ""
source $ROSWSS_BASE_SCRIPTS/helper/helper.sh

_NO_SUDO=0
packages=()
for arg in $@; do
    # Exclude arguments passed with -*, e.g., --no-sudo
    if [[ $arg != "-"* && ! -z "$arg" ]]; then
        packages+=("$arg")
    elif [[ $arg == "--no-sudo" ]]; then
        _NO_SUDO=1
    fi
done

# Do not pull system update if only specific package is updated
if [[ -z "${packages[@]}" ]]; then
  # pull system update
  echo_info ">>> Pulling system package updates"
  if [[ $_NO_SUDO == 1 ]]; then
    echo "Skipped because --no-sudo option was specified."
  else
    sudo apt-get update -qq
    AVAILABLE_SYSTEM_PACKAGE_UPDATES=$(apt-get -qq -s upgrade | grep Inst | cut -d ' ' -f 2 | grep "^[[:blank:]]*${ROSWSS_PREFIX}-\|^[[:blank:]]*ros-")
    if [ ! -z "${AVAILABLE_SYSTEM_PACKAGE_UPDATES[@]}" ]; then
      sudo apt install -qq --only-upgrade ${AVAILABLE_SYSTEM_PACKAGE_UPDATES[@]}
    else
      echo "Already up to date."
    fi
  fi
fi
