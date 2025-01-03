#!/bin/bash

function _tudawss_discovery_complete() {
  if ! which register-python-argcomplete > /dev/null 2>&1 && ! which register-python-argcomplete3 > /dev/null 2>&1; then
    echo ""
    echo "For autocompletion please install argcomplete using 'pip3 install --user argcomplete'"
  fi
  local IFS=$'\013'
  local SUPPRESS_SPACE=0
  if compopt +o nospace 2> /dev/null; then
    SUPPRESS_SPACE=1
  fi
  COMP_LINE=${COMP_LINE#${COMP_WORDS[0]} } # Remove prefix
  (( COMP_POINT -= ${#COMP_WORDS[0]} + 1 ))
  COMPREPLY=( $(IFS="$IFS" \
                COMP_LINE="$COMP_LINE" \
                COMP_POINT="$COMP_POINT" \
                COMP_TYPE="$COMP_TYPE" \
                _ARGCOMPLETE_COMP_WORDBREAKS="$COMP_WORDBREAKS" \
                _ARGCOMPLETE=1 \
                _ARGCOMPLETE_SUPPRESS_SPACE=$SUPPRESS_SPACE \
                $TUDA_WSS_BASE_SCRIPTS/_discovery.py 8>&1 9>&2 > /dev/null 2>&1) )
  if [[ $? != 0 ]]; then
    unset COMPREPLY
  elif [[ $SUPPRESS_SPACE == 1 ]] && [[ "$COMPREPLY" =~ [=/:]$ ]]; then
    compopt -o nospace
  fi
  return
}

add_tuda_wss_completion "discovery" "_tudawss_discovery_complete"
