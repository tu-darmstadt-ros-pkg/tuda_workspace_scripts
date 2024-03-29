#!/bin/bash

_NO_SUDO=0
for arg in $@; do
    # Exclude arguments passed with -*, e.g., --no-sudo
    if [[ $arg == "--no-sudo" ]]; then
        _NO_SUDO=1
    fi
done

_DEFAULT_YES=""
for arg in $@; do
  if [[ $arg == "--default-yes" ]] || [[ $arg == "-y" ]]; then
    _DEFAULT_YES="-y"
  fi
done

# Do not pull system update if only specific package is updated
# pull system update
echo_info ">>> Pulling system package updates"
if [[ $_NO_SUDO == 1 ]]; then
    echo "Skipped because --no-sudo option was specified."
else
    sudo apt-get update
    AVAILABLE_SYSTEM_PACKAGE_UPDATES=$(apt-get -qq -s upgrade | grep Inst | cut -d ' ' -f 2 | grep "^[[:blank:]]*${ROSWSS_PREFIX}-\|^[[:blank:]]*ros-")
    if [ ! -z "${AVAILABLE_SYSTEM_PACKAGE_UPDATES[@]}" ]; then
        sudo apt install ${_DEFAULT_YES} --only-upgrade ${AVAILABLE_SYSTEM_PACKAGE_UPDATES[@]}
    else
        echo "Already up to date."
    fi
fi
