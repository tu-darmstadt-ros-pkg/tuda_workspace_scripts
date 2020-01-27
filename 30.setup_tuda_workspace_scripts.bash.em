#!/bin/bash

# DO NOT REMOVE THIS LINE UNLESS YOU DON'T WANT TO USE CUSTOM SCRIPTS
@[if DEVELSPACE]@
export ROSWSS_SCRIPTS="@(PROJECT_SOURCE_DIR)/scripts:$ROSWSS_SCRIPTS"
@[else]@
export ROSWSS_SCRIPTS="@(CMAKE_INSTALL_PREFIX)/@(CATKIN_PACKAGE_SHARE_DESTINATION)/scripts:$ROSWSS_SCRIPTS"
@[end if]@

# This is meant solely as an overlay for an existing robot scripts environment and does not overwrite
# the required aliases.

# REGISTER CUSTOM COMPLETION SCRIPTS HERE
# Use add_completion to register additional auto completion scripts
# Example:
#   add_completion "my_command" "completion_function"
