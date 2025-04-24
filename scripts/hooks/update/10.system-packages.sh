#!/bin/sh
. ${TUDA_WSS_BASE_SCRIPTS}/helpers/output.sh

_NO_SUDO=0
_DEFAULT_YES=""
for arg in "$@"; do
  if [ "$arg" = "no_sudo=True" ] || [ "$arg" = "--no-sudo" ]; then
    _NO_SUDO=1
  fi
  if [ "$arg" = "default_yes=True" ] || [ "$arg" = "--default-yes" ] || [ "$arg" = "-y" ]; then
    _DEFAULT_YES="-y"
  fi
done

# Do not pull system update if only specific package is updated
# pull system update
_echo_header "Pulling ROS system package updates"
if [ $_NO_SUDO -eq 1 ]; then
  echo "Skipped because --no-sudo option was specified."
else
  sudo apt-get update
  AVAILABLE_SYSTEM_PACKAGE_UPDATES=$(apt-get -qq -s --with-new-pkgs upgrade | grep Inst | cut -d ' ' -f 2 | grep "^[[:blank:]]*ros-")
  if [ -n "${AVAILABLE_SYSTEM_PACKAGE_UPDATES}" ]; then
    sudo apt install ${_DEFAULT_YES} --only-upgrade ${AVAILABLE_SYSTEM_PACKAGE_UPDATES}
  else
    echo "Already up to date."
  fi
fi
