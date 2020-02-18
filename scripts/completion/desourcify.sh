#!/bin/bash

function _desourcify_complete() {
  which register-python-argcomplete 2>&1 > /dev/null
  if [ $? -eq 0 ]; then
    for dir in ${ROSWSS_SCRIPTS//:/ }; do
      if [ -x "$dir/desourcify.py" ]; then
        local IFS=$'\013'
        local SUPPRESS_SPACE=0
        if compopt +o nospace 2> /dev/null; then
          SUPPRESS_SPACE=1
        fi
        local PREFIX_LENGTH=$((${#ROSWSS_PREFIX}+1))
        COMPREPLY=( $(IFS="$IFS" \
                      COMP_LINE="${COMP_LINE:PREFIX_LENGTH}" \
                      COMP_POINT="$(($COMP_POINT-$PREFIX_LENGTH))" \
                      COMP_TYPE="$COMP_TYPE" \
                      _ARGCOMPLETE_COMP_WORDBREAKS="$COMP_WORDBREAKS" \
                      _ARGCOMPLETE=1 \
                      _ARGCOMPLETE_SUPPRESS_SPACE=$SUPPRESS_SPACE \
                      $dir/desourcify.py 8>&1 9>&2 > /dev/null 2>&1 ) )
        if [[ $? != 0 ]]; then
          unset COMPREPLY
        elif [[ $SUPPRESS_SPACE == 1 ]] && [[ "$COMPREPLY" =~ [=/:]$ ]]; then
          compopt -o nospace
        fi
        return
      fi
    done
  else
    echo ""
    echo_note "For autocompletion please install argcomplete using 'pip install --user argcomplete'"
  fi
}

add_completion "desourcify" "_desourcify_complete"
