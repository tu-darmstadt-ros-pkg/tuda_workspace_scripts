#!/bin/bash

# Create empty config on first usage
tmp_directory="/tmp/tuda_wss"

if [[ ! -d ${tmp_directory} ]]; then
  mkdir ${tmp_directory}
fi

if [[ ! -f "${tmp_directory}/discovery_client.xml" ]]; then
  echo "<?xml version='1.0' encoding='utf-8'?>
<dds><profiles xmlns=\"http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles\"><participant profile_name=\"empty_profile\" is_default_profile=\"true\" /></profiles></dds>" > ${tmp_directory}/discovery_client.xml
fi
export FASTRTPS_DEFAULT_PROFILES_FILE="${tmp_directory}/discovery_client.xml"

