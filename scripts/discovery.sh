#!/bin/sh
tmp_directory="/tmp/tuda_wss"

for arg in "$@"; do
  if [ "$arg" = "--help" ] || [ "$arg" = "-h" ]; then
    $TUDA_WSS_BASE_SCRIPTS/_discovery.py "$@"
    return 0
  fi
done

$TUDA_WSS_BASE_SCRIPTS/_discovery.py "$@"

if [[ -f "${tmp_directory}/discovery_client.xml" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="${tmp_directory}/discovery_client.xml"
else
    unset FASTRTPS_DEFAULT_PROFILES_FILE
fi