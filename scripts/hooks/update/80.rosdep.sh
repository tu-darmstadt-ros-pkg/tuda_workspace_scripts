#!/bin/sh
. ${TUDA_WSS_BASE_SCRIPTS}/helpers/output.sh

_NO_SUDO=0
_DEFAULT_YES=""
for arg in "$@"; do
  if [ "$arg" = "--no-sudo" ]; then
    _NO_SUDO=1
  fi
  if [ "$arg" = "--default-yes" ] || [ "$arg" = "-y" ]; then
    _DEFAULT_YES="-y"
  fi
done

# Do not pull system update if only specific package is updated
# pull system update
_echo_header "Installing package dependencies"
if [ $_NO_SUDO -eq 1 ]; then
  echo "Skipped because --no-sudo option was specified."
else
  rosdep update
  rosdep install --from-paths src --ignore-src -r ${_DEFAULT_YES}
fi
