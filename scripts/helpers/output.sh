#!/bin/sh

_echoc() {
  if [ $# -lt 2 ]; then
    echo "echoc usage: _echoc <COLOR> <TEXT>"
    return
  fi

  case "$1" in
    RED) COLOR='\033[0;31m' ;;
    GREEN) COLOR='\033[0;32m' ;;
    ORANGE) COLOR='\033[0;33m' ;;
    BLUE) COLOR='\033[0;34m' ;;
    PURPLE) COLOR='\033[0;35m' ;;
    CYAN) COLOR='\033[0;36m' ;;
    LGRAY) COLOR='\033[0;37m' ;;
    DGRAY) COLOR='\033[1;30m' ;;
    LRED) COLOR='\033[1;31m' ;;
    LGREEN) COLOR='\033[1;32m' ;;
    YELLOW) COLOR='\033[1;33m' ;;
    LBLUE) COLOR='\033[1;34m' ;;
    LPURPLE) COLOR='\033[1;35m' ;;
    LCYAN) COLOR='\033[1;36m' ;;
    WHITE) COLOR='\033[1;37m' ;;
    *) COLOR='\033[0m' ;; # Default to no color
  esac

  shift
  printf "%b" "${COLOR}"
  printf "%b\n" "${*}\033[0m"
}

_echo_error() {
  _echoc RED "$@"
}

_echo_warn() {
  _echoc ORANGE "$@"
}

_echo_debug() {
  _echoc LGREEN "$@"
}

_echo_info() {
  _echoc BLUE "$@"
}

_echo_note() {
  _echoc LGRAY "$@"
}

_echo_header() {
  _echoc LBLUE ">>> $@"
}