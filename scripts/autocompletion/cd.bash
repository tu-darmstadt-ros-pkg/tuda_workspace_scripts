#!/bin/bash

function _tudawss_cd_complete() {
  # Only one argument possible
  if [ ${#COMP_WORDS[@]} -eq 3 ]; then
    COMPREPLY=( $( compgen -W "$(python3 $TUDA_WSS_BASE_SCRIPTS/helpers/get_package_names_in_workspace.py)" -- "$(_get_cword)" ) )
  fi
  return 0
}

add_tuda_wss_completion "cd" "_tudawss_cd_complete"
